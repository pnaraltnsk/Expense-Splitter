from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
from secrets import token_urlsafe
from uuid import uuid4


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def new_id() -> str:
    return str(uuid4())


class MockStore:
    """Small in-memory store. Replace this class with a database repository later."""

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.groups: dict[str, dict] = {}
        self.token_to_group: dict[str, str] = {}

    def create_group(self, name: str, currency: str, creator_name: str) -> dict:
        group_id = new_id()
        owner_token = token_urlsafe(32)
        member_token = token_urlsafe(32)
        owner_member_id = new_id()
        group = {
            "id": group_id,
            "name": name.strip(),
            "currency": currency,
            "simplifyDebts": True,
            "createdAt": now_iso(),
            "ownerMemberId": owner_member_id,
            "members": [{"id": owner_member_id, "name": creator_name.strip()}],
            "expenses": [],
            "settlements": [],
            "recurringExpenses": [],
            "_ownerToken": owner_token,
            "_memberToken": member_token,
        }
        self.groups[group_id] = group
        self.token_to_group[owner_token] = group_id
        self.token_to_group[member_token] = group_id
        return deepcopy(group)

    def group_for_token(self, token: str) -> dict | None:
        group_id = self.token_to_group.get(token)
        return self.groups.get(group_id) if group_id else None

    def public_group(self, group: dict) -> dict:
        result = deepcopy(group)
        result.pop("_ownerToken", None)
        result.pop("_memberToken", None)
        return result


store = MockStore()
