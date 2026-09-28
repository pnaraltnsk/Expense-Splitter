from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.store import store


@pytest.fixture(autouse=True)
def reset_store() -> Iterator[None]:
    store.reset()
    yield
    store.reset()


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client


def create_group(client: TestClient) -> dict:
    response = client.post("/groups", json={"name": "Weekend away", "currency": "EUR"})
    assert response.status_code == 201
    return response.json()


def owner_headers(group: dict) -> dict[str, str]:
    return {"Authorization": f"Bearer {group['ownerToken']}"}


def member_headers(group: dict) -> dict[str, str]:
    return {"Authorization": f"Bearer {group['memberToken']}"}


def test_create_group_returns_group_and_two_secret_tokens(client: TestClient) -> None:
    response = client.post("/groups", json={"name": "Weekend away", "currency": "EUR"})

    assert response.status_code == 201
    group = response.json()
    assert group["name"] == "Weekend away"
    assert group["currency"] == "EUR"
    assert group["ownerToken"] != group["memberToken"]
    assert group["members"][0]["name"] == "You"
    assert group["expenses"] == []
    assert group["simplifyDebts"] is True


def test_create_group_rejects_invalid_currency(client: TestClient) -> None:
    response = client.post("/groups", json={"name": "Weekend away", "currency": "EURO"})
    assert response.status_code == 400


def test_get_group_allows_owner_or_member_and_hides_tokens(client: TestClient) -> None:
    group = create_group(client)

    for token, headers in ((group["ownerToken"], owner_headers(group)), (group["memberToken"], member_headers(group))):
        response = client.get(f"/groups/{token}", headers=headers)
        assert response.status_code == 200
        assert response.json()["id"] == group["id"]
        assert "ownerToken" not in response.json()
        assert "memberToken" not in response.json()


def test_get_group_requires_valid_token(client: TestClient) -> None:
    group = create_group(client)
    assert client.get(f"/groups/{group['ownerToken']}").status_code == 401
    assert client.get(f"/groups/{group['ownerToken']}", headers={"Authorization": "Bearer wrong"}).status_code == 401


def test_owner_can_add_and_remove_member_but_member_cannot(client: TestClient) -> None:
    group = create_group(client)
    path = f"/groups/{group['ownerToken']}/members"
    denied = client.post(path, headers=member_headers(group), json={"name": "Alex"})
    assert denied.status_code == 401

    created = client.post(path, headers=owner_headers(group), json={"name": "Alex"})
    assert created.status_code == 201
    member_id = created.json()["id"]
    removed = client.delete(f"{path}/{member_id}", headers=owner_headers(group))
    assert removed.status_code == 204
    assert all(m["id"] != member_id for m in client.get(f"/groups/{group['ownerToken']}", headers=owner_headers(group)).json()["members"])


def test_owner_can_create_update_and_delete_expense(client: TestClient) -> None:
    group = create_group(client)
    headers = owner_headers(group)
    members = group["members"]
    payload = {
        "description": "Dinner",
        "amount": 30,
        "category": "Food",
        "date": "2026-09-28",
        "payers": [{"memberId": members[0]["id"], "amount": 30}],
        "participants": [m["id"] for m in members],
        "splitType": "equal",
    }
    denied = client.post(f"/groups/{group['ownerToken']}/expenses", headers=member_headers(group), json=payload)
    assert denied.status_code == 401
    created = client.post(f"/groups/{group['ownerToken']}/expenses", headers=headers, json=payload)
    assert created.status_code == 201
    expense_id = created.json()["id"]
    update = {**payload, "description": "Dinner updated", "amount": 40, "payers": [{"memberId": members[0]["id"], "amount": 40}]}
    updated = client.put(f"/groups/{group['ownerToken']}/expenses/{expense_id}", headers=headers, json=update)
    assert updated.status_code == 200
    assert updated.json()["description"] == "Dinner updated"
    assert client.delete(f"/groups/{group['ownerToken']}/expenses/{expense_id}", headers=headers).status_code == 204


def test_exact_and_percentage_splits_must_reconcile(client: TestClient) -> None:
    group = create_group(client)
    headers = owner_headers(group)
    members = group["members"]
    base = {
        "description": "Custom split",
        "amount": 20,
        "category": "Other",
        "date": "2026-09-28",
        "payers": [{"memberId": members[0]["id"], "amount": 20}],
        "participants": [m["id"] for m in members],
    }
    bad_exact = {**base, "splitType": "exact", "shares": {members[0]["id"]: 9}}
    assert client.post(f"/groups/{group['ownerToken']}/expenses", headers=headers, json=bad_exact).status_code == 400
    bad_percent = {**base, "splitType": "percentage", "shares": {members[0]["id"]: 50}}
    assert client.post(f"/groups/{group['ownerToken']}/expenses", headers=headers, json=bad_percent).status_code == 400


def test_balances_include_expense_shares_and_ignore_pending_settlement(client: TestClient) -> None:
    group = create_group(client)
    owner_id = group["members"][0]["id"]
    other = client.post(f"/groups/{group['ownerToken']}/members", headers=owner_headers(group), json={"name": "Alex"}).json()
    expense = {
        "description": "Lunch",
        "amount": 20,
        "category": "Food",
        "date": "2026-09-28",
        "payers": [{"memberId": owner_id, "amount": 20}],
        "participants": [owner_id, other["id"]],
        "splitType": "equal",
    }
    client.post(f"/groups/{group['ownerToken']}/expenses", headers=owner_headers(group), json=expense)
    response = client.get(f"/groups/{group['memberToken']}/balances", headers=member_headers(group))
    assert response.status_code == 200
    assert response.json()["balances"] == [{"fromMemberId": other["id"], "toMemberId": owner_id, "amount": 10.0}]


def test_settlement_requires_authentication_and_owner_confirmation(client: TestClient) -> None:
    group = create_group(client)
    first = group["members"][0]
    second = client.post(f"/groups/{group['ownerToken']}/members", headers=owner_headers(group), json={"name": "Alex"}).json()
    client.post(
        f"/groups/{group['ownerToken']}/expenses",
        headers=owner_headers(group),
        json={
            "description": "Shared lunch",
            "amount": 10,
            "category": "Food",
            "date": "2026-09-28",
            "payers": [{"memberId": first["id"], "amount": 10}],
            "participants": [first["id"], second["id"]],
            "splitType": "equal",
        },
    )
    path = f"/groups/{group['memberToken']}/settlements"
    payload = {"fromMemberId": second["id"], "toMemberId": first["id"], "amount": 5}
    assert client.post(path, json=payload).status_code == 401
    reported = client.post(path, headers=member_headers(group), json=payload)
    assert reported.status_code == 201
    assert reported.json()["status"] == "pending"
    settlement_id = reported.json()["id"]
    confirm_path = f"/groups/{group['ownerToken']}/settlements/{settlement_id}/confirm"
    assert client.post(confirm_path, headers=member_headers(group)).status_code == 401
    confirmed = client.post(confirm_path, headers=owner_headers(group))
    assert confirmed.status_code == 200
    assert confirmed.json()["status"] == "confirmed"
    balances = client.get(f"/groups/{group['ownerToken']}/balances", headers=owner_headers(group)).json()
    assert balances["balances"] == []
    assert client.post(confirm_path, headers=owner_headers(group)).status_code == 400


def test_owner_cannot_confirm_overlapping_pending_claims(client: TestClient) -> None:
    group = create_group(client)
    first = group["members"][0]
    second = client.post(f"/groups/{group['ownerToken']}/members", headers=owner_headers(group), json={"name": "Alex"}).json()
    client.post(
        f"/groups/{group['ownerToken']}/expenses",
        headers=owner_headers(group),
        json={
            "description": "Shared lunch",
            "amount": 10,
            "category": "Food",
            "date": "2026-09-28",
            "payers": [{"memberId": first["id"], "amount": 10}],
            "participants": [first["id"], second["id"]],
            "splitType": "equal",
        },
    )
    payload = {"fromMemberId": second["id"], "toMemberId": first["id"], "amount": 5}
    path = f"/groups/{group['memberToken']}/settlements"
    claims = [client.post(path, headers=member_headers(group), json=payload).json() for _ in range(2)]
    confirm = f"/groups/{group['ownerToken']}/settlements/{claims[0]['id']}/confirm"
    assert client.post(confirm, headers=owner_headers(group)).status_code == 200
    overlapping = f"/groups/{group['ownerToken']}/settlements/{claims[1]['id']}/confirm"
    assert client.post(overlapping, headers=owner_headers(group)).status_code == 400


def test_unsimplified_balances_net_opposing_pairwise_debts(client: TestClient) -> None:
    group = create_group(client)
    headers = owner_headers(group)
    members = group["members"]
    for payer in members:
        payload = {
            "description": f"Paid by {payer['name']}",
            "amount": 10,
            "category": "Food",
            "date": "2026-09-28",
            "payers": [{"memberId": payer["id"], "amount": 10}],
            "participants": [m["id"] for m in members],
            "splitType": "equal",
        }
        client.post(f"/groups/{group['ownerToken']}/expenses", headers=headers, json=payload)
    client.patch(f"/groups/{group['ownerToken']}/settings", headers=headers, json={"simplifyDebts": False})
    balances = client.get(f"/groups/{group['ownerToken']}/balances", headers=headers).json()
    assert balances["balances"] == []


def test_owner_can_change_debt_simplification(client: TestClient) -> None:
    group = create_group(client)
    path = f"/groups/{group['ownerToken']}/settings"
    assert client.patch(path, headers=member_headers(group), json={"simplifyDebts": False}).status_code == 401
    changed = client.patch(path, headers=owner_headers(group), json={"simplifyDebts": False})
    assert changed.status_code == 200
    assert changed.json()["simplifyDebts"] is False


def test_owner_can_manage_recurring_expense_schedules(client: TestClient) -> None:
    group = create_group(client)
    path = f"/groups/{group['ownerToken']}/recurring-expenses"
    payload = {"description": "Rent", "amount": 1000, "category": "Accommodation", "interval": "monthly"}
    assert client.post(path, headers=member_headers(group), json=payload).status_code == 401
    created = client.post(path, headers=owner_headers(group), json=payload)
    assert created.status_code == 201
    schedule_id = created.json()["id"]
    assert client.delete(f"{path}/{schedule_id}", headers=owner_headers(group)).status_code == 204
