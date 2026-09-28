# Owesome — Project Specification

## 1. Overview

A general-purpose expense splitting application supporting multiple independent groups (trips, households, one-off events). Each group manages its own members, currency, and expenses, with a lightweight owner/member permission model instead of full user accounts.

**Goal:** A solid, day-to-day usable app — not just a throwaway prototype.

---

## 2. Tech Stack

| Layer | Choice | Notes |
|---|---|---|
| Backend | **Python + FastAPI** | Managed with `uv` for dependency/environment management |
| Database | **PostgreSQL** | Better fit than SQLite for cloud deployment (managed Postgres on Railway/Render is easy; avoids ephemeral filesystem issues) |
| Frontend | **React** | |
| Styling | **Tailwind CSS** | Lightweight, no component-library overhead |
| Hosting | **Cloud platform** (e.g. Railway, Render, Vercel for frontend + Railway/Render for backend+DB) | Proper deployment, not just local dev |

---

## 3. Access Model (No Auth)

There is no traditional login (no email/password, no user accounts). Instead:

- Each group, on creation, generates **two secret links (tokens)**:
  - **Owner link** — full access (create/edit/delete expenses, manage members, edit group settings, approve settlements)
  - **Member link** — restricted access (view expenses/balances, add themselves as a payer/participant on new expenses per group rules, mark their own debts as "paid")
- Anyone with a link has the corresponding access level — access is via possession of the secret link/token, not identity verification.
- The app remembers groups opened in the current browser so they can be reopened without pasting the link again.
- The welcome screen must offer an **Open an existing group** option that accepts a full owner/member invite link or a token. Opening an owner link restores creator access; opening a member link restores member access.
- Group data and token mappings must survive backend process restarts. The mock backend stores them in a local JSON file during development; production must store them in the configured persistent database.
- Without accounts, a group cannot be recovered by its name. If a user loses every copy of its invite links and clears the browser's saved data, recovery is not possible. The owner link should be treated as the creator's recovery credential and kept somewhere safe.
- Members are represented as **named participants** within a group (not system-wide user accounts). A person picks/is assigned their name within the group context.
- Links should be unguessable (e.g. UUID or long random token) and shareable (copy link / QR code optional nice-to-have).

### Permission Summary

| Action | Owner | Member |
|---|---|---|
| Create/edit/delete group | ✅ | ❌ |
| Add/edit/delete expenses | ✅ | ❌ |
| View expenses & balances | ✅ | ✅ |
| Mark a debt as "I paid" | ✅ | ✅ (for themself) |
| Approve/confirm a payment as settled | ✅ | ❌ |
| Manage members (add/remove) | ✅ | ❌ |
| Toggle debt-simplification setting | ✅ | ❌ |

---

## 4. Groups

- A group has: name, currency, creation date, owner link, member link, list of members, list of expenses.
- **Currency:** set per group (each group has its own single currency — no multi-currency conversion within a group).
- **Debt simplification:** togglable per group.
  - Off: shows raw pairwise balances resulting from expense splits.
  - On: simplifies balances into the minimum number of suggested transactions (Splitwise-style greedy settlement algorithm).

---

## 5. Members

- Members are simple named entities scoped to a group (no login).
- Owner adds/removes members via the owner link.
- A member "acts as" themselves within the group (e.g. via the member link, they identify which participant they are to mark payments).

---

## 6. Expenses

### Core fields
- Description
- Amount
- Category (tag: e.g. Food, Transport, Accommodation, Utilities, Other — predefined list, extensible)
- Date
- Payer(s) — who actually paid the money
- Participants — who the expense is split among (defaults to all group members, adjustable per expense)
- Split type (see below)
- Recurring flag/settings (see below)

### Split types
- **Equal** — split evenly among selected participants
- **Exact amounts** — specify exact amount per participant (must sum to total)
- **Percentages** — specify % per participant (must sum to 100%)

### Split scope
- Defaults to equally among **all** group members.
- Adjustable per expense: owner can select a subset of participants and/or change split type for that expense.

### Recurring expenses
- Supports recurring expenses (e.g. monthly rent, subscriptions).
- Owner defines: base expense details + recurrence interval (e.g. weekly/monthly).
- System auto-generates new expense instances on schedule (or generates the next upcoming instance for confirmation — implementation detail to decide during build).

### Editing rules
- Owner can edit or delete any expense at any time, no restrictions/locking.
- Members cannot edit or delete expenses.

---

## 7. Settlements

- Balances are calculated from expenses (who paid vs. who owes what share).
- **Settle-up flow:**
  1. A member marks a debt as "I paid" (self-reported, no proof required).
  2. This creates a **pending settlement** — it does **not** immediately affect balances.
  3. The **owner must confirm/approve** the settlement before it counts as paid and balances update.
- This gives the owner a checkpoint against mistaken or false "paid" claims.
- A pending report disables the matching settle action for that debtor/creditor pair. Repeated reports are rejected, and the total of pending reports cannot exceed the outstanding balance.
- When an owner confirms a report, any legacy pending claims that are no longer covered by the remaining balance are rejected so they cannot be confirmed a second time.

---

## 8. Non-Goals (for this version)

- No multi-currency conversion within a single group.
- No user accounts / passwords / email verification.
- No activity/notification feed (kept minimal for now).
- No data export (CSV/PDF) in this version.
- No receipt photo upload in this version (category tags only).

These are reasonable candidates for a future iteration but are explicitly out of scope for v1.

---

## 9. High-Level Data Model (draft)

```
Group
 - id
 - name
 - currency
 - owner_token
 - member_token
 - simplify_debts (bool)
 - created_at

Member
 - id
 - group_id (FK)
 - name

Expense
 - id
 - group_id (FK)
 - description
 - amount
 - category
 - date
 - split_type (equal | exact | percentage)
 - is_recurring (bool)
 - recurrence_interval (nullable)
 - created_at
 - updated_at

ExpensePayer
 - expense_id (FK)
 - member_id (FK)
 - amount_paid

ExpenseParticipant
 - expense_id (FK)
 - member_id (FK)
 - share_amount / share_percentage

Settlement
 - id
 - group_id (FK)
 - from_member_id (FK)
 - to_member_id (FK)
 - amount
 - status (pending | confirmed)
 - created_at
 - confirmed_at
```

---

## 10. API Design (high-level, REST via FastAPI)

- `POST /groups` — create group (returns owner_token + member_token)
- `GET /groups/{token}` — get group details/expenses/balances (behavior depends on owner vs member token)
- `GET /groups/{owner_token}/links` — owner-only retrieval of the member invite token, so an owner reopening from a saved owner link can still invite participants
- `POST /groups/{owner_token}/members` — add member
- `DELETE /groups/{owner_token}/members/{id}` — remove member
- `POST /groups/{owner_token}/expenses` — create expense
- `PUT /groups/{owner_token}/expenses/{id}` — edit expense
- `DELETE /groups/{owner_token}/expenses/{id}` — delete expense
- `GET /groups/{token}/balances` — get current balances (raw or simplified per group setting)
- `POST /groups/{member_token}/settlements` — member marks a debt as paid
- `POST /groups/{owner_token}/settlements/{id}/confirm` — owner confirms settlement
- `PATCH /groups/{owner_token}/settings` — toggle debt simplification, etc.

Token access uses unguessable owner/member link tokens as Bearer credentials. API path tokens must match the supplied Bearer token. The GET group response reports the access role granted by that token; owner tokens are never returned by group-read or invite-link retrieval responses.

---

## 11. Open Questions for Implementation Phase

- Exact behavior of recurring expenses: auto-post vs. generate-and-confirm.
- Token delivery/security: link format, whether tokens should be rotatable, QR code sharing.
- Predefined category list — finalize the set.
- Debt simplification algorithm specifics (standard greedy minimum-transaction approach recommended).
