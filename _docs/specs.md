# Owesome — Project Specification

## 1. Overview

A general-purpose expense splitting application supporting multiple independent groups (trips, households, one-off events). Each group manages its own members, currency, and expenses, with a lightweight owner/member permission model instead of full user accounts.

**Goal:** A solid, day-to-day usable app — not just a throwaway prototype.

---

## 2. Tech Stack

| Layer | Choice | Notes |
|---|---|---|
| Backend | **Python + FastAPI** | Managed with `uv` for dependency/environment management |
| Database | **SQLite via SQLAlchemy** | Uses `DATABASE_URL` for configuration and SQLAlchemy's portable types so PostgreSQL can be added later |
| Frontend | **React** | |
| Styling | **Tailwind CSS** | Lightweight, no component-library overhead |
| Hosting | **Cloud platform** (e.g. Railway, Render, Vercel for frontend + Railway/Render for backend+DB) | Proper deployment, not just local dev |

---

## 3. Access Model (No Auth)

There is no traditional login (no email/password, no user accounts). Instead:

- Each group, on creation, generates **two secret links (tokens)**:
  - **Owner link** — full group management access; the creator can confirm receipt only when they are the payment recipient
  - **Member invite link** — shared access to view the group and join by name
  - **Individual member access link** — private access for one participant to report their own payments and confirm payments owed to them
- Anyone with a link has the corresponding access level — access is via possession of the secret link/token, not identity verification.
- The shared member invite link identifies the group, not a participant. Joining creates a private, unguessable member access link tied to that participant; save and keep it private. This lets the backend verify which member is acting without adding accounts or passwords.
- The app remembers groups opened in the current browser so they can be reopened without pasting the link again.
- The welcome screen must offer an **Open an existing group** option that accepts a full owner/member invite link or a token. Opening an owner link restores creator access; opening a member link restores member access.
- Group data and token mappings must survive backend process restarts. The backend stores them in SQLAlchemy-managed tables using the database selected by `DATABASE_URL` (SQLite by default). The first default startup imports groups from the previous local JSON store if the new database is empty.
- Without accounts, a group cannot be recovered by its name. A member can regain member access using their private member link; only the owner link can restore owner access or delete the group. If all links and browser-saved credentials are lost, recovery is not possible. A future recovery-code flow (or optional accounts) could address this; group-name lookup must never grant access.
- Group changes should appear on other open clients through periodic refresh. Durable database storage preserves changes across restarts, but live updates still require polling or a push channel such as server-sent events/websockets.
- Members are represented as **named participants** within a group (not system-wide user accounts). A person picks/is assigned their name within the group context.
- Links should be unguessable (e.g. UUID or long random token) and shareable (copy link / QR code optional nice-to-have).

### Permission Summary

| Action | Owner | Member |
|---|---|---|
| Create/edit/delete group | ✅ | ❌ |
| Add/edit/delete expenses | ✅ | ❌ |
| View expenses & balances | ✅ | ✅ |
| Mark a debt as "I paid" | ✅ | ✅ (for themself) |
| Confirm receipt of a reported payment | ✅ (only when the owner is the recipient) | ✅ (only when this member is the recipient) |
| Manage members (add/remove) | ✅ | ❌ |
| Toggle debt-simplification setting | ✅ | ❌ |

---

## 4. Groups

- A group has: name, currency, creation date, owner link, shared member invite link, individual member access links, list of members, list of expenses.
- **Currency:** set per group (each group has its own single currency — no multi-currency conversion within a group).
- **Debt simplification:** togglable per group.
  - Off: shows raw pairwise balances resulting from expense splits.
  - On: simplifies balances into the minimum number of suggested transactions (Splitwise-style greedy settlement algorithm).

---

## 5. Members

- Members are simple named entities scoped to a group (no login).
- Owner adds/removes members via the owner link.
- Members use their own individual access link. The shared invite link does not identify a participant.

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
  3. The **recipient of the payment confirms receipt** before it counts as paid and balances update.
- Owner permissions alone do not allow confirming a payment owed to another member. The member access link proves the recipient's identity for this action.
- Pending reports cannot collectively exceed the current debt between the two participants. The matching settle action displays **Pending** while a report awaits receipt confirmation.
- A pending report disables the matching settle action for that debtor/creditor pair. Repeated reports are rejected, and the total of pending reports cannot exceed the outstanding balance.
- When a recipient confirms a report, any legacy pending claims that are no longer covered by the remaining balance are rejected so they cannot be confirmed a second time.

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
- `DELETE /groups/{token}` — permanently delete a group and all its data (owner token only)
- `GET /groups/{owner_token}/links` — owner-only retrieval of the member invite token, so an owner reopening from a saved owner link can still invite participants
- `GET /groups/{owner_token}/members/{id}/access-link` — owner-only issuance or retrieval of an individual member access token, including for members created before individual links were introduced
- `POST /groups/{owner_token}/members` — add member
- `DELETE /groups/{owner_token}/members/{id}` — remove member
- `POST /groups/{owner_token}/expenses` — create expense
- `PUT /groups/{owner_token}/expenses/{id}` — edit expense
- `DELETE /groups/{owner_token}/expenses/{id}` — delete expense
- `GET /groups/{token}/balances` — get current balances (raw or simplified per group setting)
- `POST /groups/{member_token}/settlements` — identified member reports their own debt as paid
- `POST /groups/{member_token}/settlements/{id}/confirm` — payment recipient confirms settlement using their individual member access link (the owner may confirm only if they are the recipient)
- `PATCH /groups/{owner_token}/settings` — toggle debt simplification, etc.

Token access uses unguessable owner/member link tokens as Bearer credentials. API path tokens must match the supplied Bearer token. The GET group response reports the access role granted by that token; owner tokens are never returned by group-read or invite-link retrieval responses.

---

## 11. Open Questions for Implementation Phase

- Exact behavior of recurring expenses: auto-post vs. generate-and-confirm.
- Token delivery/security: link format, whether tokens should be rotatable, QR code sharing.
- Predefined category list — finalize the set.
- Debt simplification algorithm specifics (standard greedy minimum-transaction approach recommended).
