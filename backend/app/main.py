from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Annotated
from uuid import UUID

from fastapi import Depends, FastAPI, HTTPException, Path, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.middleware.cors import CORSMiddleware

from app.schemas import (
    AddMemberRequest,
    CreateGroupRequest,
    ExpenseInput,
    GroupSettingsPatch,
    RecurringExpenseInput,
    ReportSettlementRequest,
    decimal_json,
    serialize_expense,
    serialize_recurring,
)
from app.store import new_id, now_iso, store

app = FastAPI(title="Owesome Expense Splitter API", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)
bearer = HTTPBearer(auto_error=False)
CENT = Decimal("0.01")


@app.exception_handler(HTTPException)
async def http_error_handler(_: Request, exc: HTTPException) -> JSONResponse:
    detail = exc.detail
    if isinstance(detail, dict) and "code" in detail:
        body = detail
    else:
        body = {"code": "unauthorized" if exc.status_code == 401 else "not_found" if exc.status_code == 404 else "request_error", "message": str(detail)}
    return JSONResponse(status_code=exc.status_code, content=body, headers=exc.headers)


@app.exception_handler(RequestValidationError)
async def validation_error_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
    errors = exc.errors()
    message = errors[0].get("msg", "Invalid request") if errors else "Invalid request"
    return JSONResponse(status_code=400, content={"code": "bad_request", "message": message})


def fail(status_code: int, code: str, message: str) -> None:
    raise HTTPException(status_code, {"code": code, "message": message})


def authenticated_group(
    path_token: str,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    *,
    required_role: str | None = None,
) -> tuple[dict, str]:
    if credentials is None or credentials.scheme.lower() != "bearer":
        fail(401, "unauthorized", "A valid Bearer token is required")
    supplied_token = credentials.credentials
    if supplied_token != path_token:
        fail(401, "unauthorized", "Bearer token must match the group token in the path")
    group = store.group_for_token(path_token)
    if group is None:
        fail(401, "unauthorized", "Invalid group token")
    role = "owner" if path_token == group["_ownerToken"] else "member"
    if required_role and role != required_role:
        fail(401, "unauthorized", "Owner access is required")
    return group, role


def group_by_id(group_id: UUID) -> dict:
    group = store.groups.get(str(group_id))
    if group is None:
        fail(404, "not_found", "Group not found")
    return group


def member_by_id(group: dict, member_id: UUID | str) -> dict | None:
    wanted = str(member_id)
    return next((member for member in group["members"] if member["id"] == wanted), None)


def validate_expense(group: dict, expense: ExpenseInput) -> None:
    participant_ids = [str(member_id) for member_id in expense.participants]
    if len(set(participant_ids)) != len(participant_ids):
        fail(400, "bad_request", "Participants must be unique")
    if any(member_by_id(group, member_id) is None for member_id in participant_ids):
        fail(400, "bad_request", "Every participant must belong to this group")
    if any(member_by_id(group, payer.memberId) is None for payer in expense.payers):
        fail(400, "bad_request", "Every payer must belong to this group")
    if sum((payer.amount for payer in expense.payers), Decimal(0)) != expense.amount:
        fail(400, "bad_request", "Payer amounts must sum to the expense amount")
    if expense.splitType == "equal":
        if expense.shares is not None:
            fail(400, "bad_request", "Equal splits must not include shares")
        return
    if expense.shares is None or {str(key) for key in expense.shares} != set(participant_ids):
        fail(400, "bad_request", "Provide one share value for every participant")
    if any(value < 0 for value in expense.shares.values()):
        fail(400, "bad_request", "Share values cannot be negative")
    total = sum(expense.shares.values(), Decimal(0))
    expected = Decimal(100) if expense.splitType == "percentage" else expense.amount
    if total != expected:
        fail(400, "bad_request", f"{expense.splitType.title()} shares must sum to {expected}")


def participant_shares(expense: dict) -> dict[str, Decimal]:
    amount = Decimal(str(expense["amount"]))
    ids = expense["participants"]
    if expense["splitType"] == "exact":
        return {member_id: Decimal(str(expense["shares"][member_id])) for member_id in ids}
    if expense["splitType"] == "percentage":
        shares = {member_id: amount * Decimal(str(expense["shares"][member_id])) / 100 for member_id in ids}
    else:
        shares = {member_id: amount / len(ids) for member_id in ids}
    rounded = {member_id: value.quantize(CENT, rounding=ROUND_HALF_UP) for member_id, value in shares.items()}
    remainder = amount - sum(rounded.values(), Decimal(0))
    if remainder:
        rounded[ids[-1]] += remainder
    return rounded


def calculate_balances(group: dict) -> list[dict]:
    pairwise: dict[tuple[str, str], Decimal] = {}
    for expense in group["expenses"]:
        shares = participant_shares(expense)
        payers = expense["payers"]
        paid_total = sum((Decimal(str(payer["amount"])) for payer in payers), Decimal(0))
        for participant_id, share in shares.items():
            remaining = share
            # Allocate this participant's expense share across payers proportionally.
            for payer in payers:
                payer_id = payer["memberId"]
                allocation = share * Decimal(str(payer["amount"])) / paid_total
                if payer_id == participant_id:
                    remaining -= allocation
                    continue
                key = (participant_id, payer_id)
                pairwise[key] = pairwise.get(key, Decimal(0)) + allocation
                remaining -= allocation
            # `remaining` only absorbs allocation rounding; values are quantized below.
            if remaining and payers and payers[-1]["memberId"] != participant_id:
                key = (participant_id, payers[-1]["memberId"])
                pairwise[key] = pairwise.get(key, Decimal(0)) + remaining
    if not group["simplifyDebts"]:
        for settlement in group["settlements"]:
            if settlement["status"] != "confirmed":
                continue
            key = (settlement["fromMemberId"], settlement["toMemberId"])
            pairwise[key] = max(Decimal(0), pairwise.get(key, Decimal(0)) - Decimal(str(settlement["amount"])))
    pairwise = {key: value.quantize(CENT, rounding=ROUND_HALF_UP) for key, value in pairwise.items() if value > Decimal("0.004")}
    if not group["simplifyDebts"]:
        net_pairs: dict[tuple[str, str], Decimal] = {}
        for (debtor, creditor), amount in pairwise.items():
            ordered = tuple(sorted((debtor, creditor)))
            direction = Decimal(1) if ordered == (debtor, creditor) else Decimal(-1)
            net_pairs[ordered] = net_pairs.get(ordered, Decimal(0)) + direction * amount
        output = []
        for (first, second), amount in net_pairs.items():
            if amount > Decimal("0.004"):
                output.append({"fromMemberId": first, "toMemberId": second, "amount": decimal_json(amount.quantize(CENT))})
            elif amount < Decimal("-0.004"):
                output.append({"fromMemberId": second, "toMemberId": first, "amount": decimal_json((-amount).quantize(CENT))})
        return output
    nets = {member["id"]: Decimal(0) for member in group["members"]}
    for (debtor, creditor), amount in pairwise.items():
        nets[debtor] -= amount
        nets[creditor] += amount
    for settlement in group["settlements"]:
        if settlement["status"] != "confirmed":
            continue
        amount = Decimal(str(settlement["amount"]))
        nets[settlement["fromMemberId"]] += amount
        nets[settlement["toMemberId"]] -= amount
    debtors = [[member_id, -amount] for member_id, amount in nets.items() if amount < -Decimal("0.004")]
    creditors = [[member_id, amount] for member_id, amount in nets.items() if amount > Decimal("0.004")]
    debtors.sort(key=lambda item: item[1], reverse=True)
    creditors.sort(key=lambda item: item[1], reverse=True)
    output: list[dict] = []
    while debtors and creditors:
        debtor_id, debt = debtors[0]
        creditor_id, credit = creditors[0]
        amount = min(debt, credit).quantize(CENT, rounding=ROUND_HALF_UP)
        if amount > 0:
            output.append({"fromMemberId": debtor_id, "toMemberId": creditor_id, "amount": decimal_json(amount)})
        debtors[0][1] -= amount
        creditors[0][1] -= amount
        if debtors[0][1] <= Decimal("0.004"):
            debtors.pop(0)
        if creditors[0][1] <= Decimal("0.004"):
            creditors.pop(0)
    return output


@app.post("/groups", status_code=status.HTTP_201_CREATED, operation_id="createGroup")
def create_group(payload: CreateGroupRequest) -> dict:
    group = store.create_group(payload.name, payload.currency, payload.creatorName)
    response = store.public_group(group)
    response["ownerToken"] = group["_ownerToken"]
    response["memberToken"] = group["_memberToken"]
    return response


@app.get("/groups/{token}", operation_id="getGroup")
def get_group(token: Annotated[str, Path(min_length=32)], credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]) -> dict:
    group, role = authenticated_group(token, credentials)
    response = store.public_group(group)
    response["accessRole"] = role
    return response


@app.get("/groups/{ownerToken}/links", operation_id="getGroupInviteLinks")
def get_group_invite_links(ownerToken: str, credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]) -> dict:
    group, _ = authenticated_group(ownerToken, credentials, required_role="owner")
    return {"memberToken": group["_memberToken"]}


@app.post("/groups/{ownerToken}/members", status_code=status.HTTP_201_CREATED, operation_id="addMember")
def add_member(ownerToken: str, payload: AddMemberRequest, credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]) -> dict:
    group, _ = authenticated_group(ownerToken, credentials, required_role="owner")
    if any(member["name"].casefold() == payload.name.casefold() for member in group["members"]):
        fail(400, "bad_request", "A member with this name already exists")
    member = {"id": new_id(), "name": payload.name}
    group["members"].append(member)
    store.save()
    return member


@app.post("/groups/{memberToken}/join", status_code=status.HTTP_201_CREATED, operation_id="joinGroup")
def join_group(memberToken: str, payload: AddMemberRequest, credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]) -> dict:
    group, role = authenticated_group(memberToken, credentials)
    if role != "member":
        fail(401, "unauthorized", "Use the member invite link to join this group")
    member = {"id": new_id(), "name": payload.name}
    group["members"].append(member)
    store.save()
    return member


@app.delete("/groups/{ownerToken}/members/{memberId}", status_code=status.HTTP_204_NO_CONTENT, operation_id="removeMember")
def remove_member(ownerToken: str, memberId: UUID, credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]) -> Response:
    group, _ = authenticated_group(ownerToken, credentials, required_role="owner")
    member = member_by_id(group, memberId)
    if member is None:
        fail(404, "not_found", "Member not found")
    group["members"] = [item for item in group["members"] if item["id"] != str(memberId)]
    # Remove expenses involving the removed participant to keep payer and split totals coherent.
    group["expenses"] = [
        expense for expense in group["expenses"]
        if str(memberId) not in expense["participants"]
        and all(payer["memberId"] != str(memberId) for payer in expense["payers"])
    ]
    group["settlements"] = [
        item for item in group["settlements"]
        if item["fromMemberId"] != str(memberId) and item["toMemberId"] != str(memberId)
    ]
    store.save()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.post("/groups/{ownerToken}/expenses", status_code=status.HTTP_201_CREATED, operation_id="createExpense")
def create_expense(ownerToken: str, payload: ExpenseInput, credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]) -> dict:
    group, _ = authenticated_group(ownerToken, credentials, required_role="owner")
    validate_expense(group, payload)
    created = now_iso()
    expense = serialize_expense(payload, UUID(new_id()), created, created)
    group["expenses"].insert(0, expense)
    store.save()
    return expense


@app.put("/groups/{ownerToken}/expenses/{expenseId}", operation_id="updateExpense")
def update_expense(ownerToken: str, expenseId: UUID, payload: ExpenseInput, credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]) -> dict:
    group, _ = authenticated_group(ownerToken, credentials, required_role="owner")
    validate_expense(group, payload)
    existing = next((item for item in group["expenses"] if item["id"] == str(expenseId)), None)
    if existing is None:
        fail(404, "not_found", "Expense not found")
    expense = serialize_expense(payload, expenseId, existing["createdAt"], now_iso())
    group["expenses"][group["expenses"].index(existing)] = expense
    store.save()
    return expense


@app.delete("/groups/{ownerToken}/expenses/{expenseId}", status_code=status.HTTP_204_NO_CONTENT, operation_id="deleteExpense")
def delete_expense(ownerToken: str, expenseId: UUID, credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]) -> Response:
    group, _ = authenticated_group(ownerToken, credentials, required_role="owner")
    existing = next((item for item in group["expenses"] if item["id"] == str(expenseId)), None)
    if existing is None:
        fail(404, "not_found", "Expense not found")
    group["expenses"].remove(existing)
    store.save()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.get("/groups/{token}/balances", operation_id="getBalances")
def get_balances(token: str, credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]) -> dict:
    group, _ = authenticated_group(token, credentials)
    return {"currency": group["currency"], "simplifyDebts": group["simplifyDebts"], "balances": calculate_balances(group)}


@app.post("/groups/{memberToken}/settlements", status_code=status.HTTP_201_CREATED, operation_id="reportSettlement")
def report_settlement(memberToken: str, payload: ReportSettlementRequest, credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]) -> dict:
    group, _ = authenticated_group(memberToken, credentials)
    from_member = member_by_id(group, payload.fromMemberId)
    to_member = member_by_id(group, payload.toMemberId)
    if from_member is None or to_member is None or payload.fromMemberId == payload.toMemberId:
        fail(400, "bad_request", "Settlement members must be different members of this group")
    balance = next((item for item in calculate_balances(group) if item["fromMemberId"] == str(payload.fromMemberId) and item["toMemberId"] == str(payload.toMemberId)), None)
    if balance is None or Decimal(str(balance["amount"])) < payload.amount:
        fail(400, "bad_request", "Settlement exceeds the outstanding balance between these members")
    settlement = {
        "id": new_id(),
        "fromMemberId": str(payload.fromMemberId),
        "toMemberId": str(payload.toMemberId),
        "amount": decimal_json(payload.amount),
        "status": "pending",
        "createdAt": now_iso(),
        "confirmedAt": None,
    }
    group["settlements"].append(settlement)
    store.save()
    return settlement


@app.post("/groups/{ownerToken}/settlements/{settlementId}/confirm", operation_id="confirmSettlement")
def confirm_settlement(ownerToken: str, settlementId: UUID, credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]) -> dict:
    group, _ = authenticated_group(ownerToken, credentials, required_role="owner")
    settlement = next((item for item in group["settlements"] if item["id"] == str(settlementId)), None)
    if settlement is None:
        fail(404, "not_found", "Settlement not found")
    if settlement["status"] == "confirmed":
        fail(400, "bad_request", "Settlement has already been confirmed")
    balance = next(
        (
            item for item in calculate_balances(group)
            if item["fromMemberId"] == settlement["fromMemberId"]
            and item["toMemberId"] == settlement["toMemberId"]
        ),
        None,
    )
    if balance is None or Decimal(str(balance["amount"])) < Decimal(str(settlement["amount"])):
        fail(400, "bad_request", "Settlement is no longer covered by the outstanding balance")
    settlement["status"] = "confirmed"
    settlement["confirmedAt"] = now_iso()
    store.save()
    return settlement


@app.patch("/groups/{ownerToken}/settings", operation_id="updateGroupSettings")
def update_settings(ownerToken: str, payload: GroupSettingsPatch, credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]) -> dict:
    group, _ = authenticated_group(ownerToken, credentials, required_role="owner")
    if not payload.model_fields_set or payload.simplifyDebts is None:
        fail(400, "bad_request", "At least one supported setting must be provided")
    group["simplifyDebts"] = payload.simplifyDebts
    store.save()
    return {"simplifyDebts": group["simplifyDebts"]}


@app.post("/groups/{ownerToken}/recurring-expenses", status_code=status.HTTP_201_CREATED, operation_id="createRecurringExpense")
def create_recurring_expense(ownerToken: str, payload: RecurringExpenseInput, credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]) -> dict:
    group, _ = authenticated_group(ownerToken, credentials, required_role="owner")
    schedule = serialize_recurring(payload, UUID(new_id()), now_iso())
    group["recurringExpenses"].append(schedule)
    store.save()
    return schedule


@app.delete("/groups/{ownerToken}/recurring-expenses/{recurringExpenseId}", status_code=status.HTTP_204_NO_CONTENT, operation_id="deleteRecurringExpense")
def delete_recurring_expense(ownerToken: str, recurringExpenseId: UUID, credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]) -> Response:
    group, _ = authenticated_group(ownerToken, credentials, required_role="owner")
    schedule = next((item for item in group["recurringExpenses"] if item["id"] == str(recurringExpenseId)), None)
    if schedule is None:
        fail(404, "not_found", "Recurring expense not found")
    group["recurringExpenses"].remove(schedule)
    store.save()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
