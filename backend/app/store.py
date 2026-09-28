from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
import json
import os
from pathlib import Path
from secrets import token_urlsafe
from uuid import uuid4


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def new_id() -> str:
    return str(uuid4())


class MockStore:
    """JSON-backed mock store. Replace this class with a database repository later."""

    def __init__(self, storage_path: Path | None = None) -> None:
        default_path = Path(__file__).resolve().parent.parent / "data" / "groups.json"
        self.storage_path = Path(os.environ.get("OWESOME_DATA_FILE", default_path)) if storage_path is None else Path(storage_path)
        self.groups: dict[str, dict] = {}
        self.token_to_group: dict[str, str] = {}
        self.token_to_member: dict[str, str] = {}
        self._load()

    def reset(self) -> None:
        self.groups: dict[str, dict] = {}
        self.token_to_group: dict[str, str] = {}
        self.token_to_member: dict[str, str] = {}
        self._persist()

    def _load(self) -> None:
        try:
            groups = json.loads(self.storage_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return
        except (json.JSONDecodeError, OSError):
            return
        if not isinstance(groups, dict):
            return
        self.groups = groups
        self.token_to_group = {}
        self.token_to_member = {}
        for group_id, group in self.groups.items():
            owner_token = group.get("_ownerToken")
            member_token = group.get("_memberToken")
            if owner_token:
                self.token_to_group[owner_token] = group_id
                self.token_to_member[owner_token] = group.get("ownerMemberId")
            if member_token:
                self.token_to_group[member_token] = group_id
            for member in group.get("members", []):
                access_token = member.get("_accessToken")
                if access_token:
                    self.token_to_group[access_token] = group_id
                    self.token_to_member[access_token] = member["id"]

    def _persist(self) -> None:
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = self.storage_path.with_suffix(f"{self.storage_path.suffix}.tmp")
        temporary_path.write_text(json.dumps(self.groups, ensure_ascii=False), encoding="utf-8")
        temporary_path.replace(self.storage_path)

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
        self.token_to_member[owner_token] = owner_member_id
        self.token_to_group[member_token] = group_id
        self._persist()
        return deepcopy(group)

    def group_for_token(self, token: str) -> dict | None:
        group_id = self.token_to_group.get(token)
        return self.groups.get(group_id) if group_id else None

    def delete_group(self, group_id: str) -> None:
        self.groups.pop(group_id, None)
        for token, mapped_group_id in list(self.token_to_group.items()):
            if mapped_group_id == group_id:
                self.token_to_group.pop(token, None)
                self.token_to_member.pop(token, None)
        self.save()

    def member_id_for_token(self, token: str) -> str | None:
        return self.token_to_member.get(token)

    def add_member(self, group: dict, name: str) -> dict:
        member_id = new_id()
        access_token = token_urlsafe(32)
        member = {"id": member_id, "name": name.strip(), "_accessToken": access_token}
        group["members"].append(member)
        group_id = group["id"]
        self.token_to_group[access_token] = group_id
        self.token_to_member[access_token] = member_id
        self.save()
        return {"id": member_id, "name": name.strip(), "accessToken": access_token}

    def ensure_member_access_token(self, group: dict, member_id: str) -> str:
        member = next((item for item in group["members"] if item["id"] == member_id), None)
        if member is None:
            raise KeyError(member_id)
        access_token = member.get("_accessToken")
        if not access_token:
            access_token = token_urlsafe(32)
            member["_accessToken"] = access_token
        self.token_to_group[access_token] = group["id"]
        self.token_to_member[access_token] = member_id
        self.save()
        return access_token

    def public_group(self, group: dict) -> dict:
        result = deepcopy(group)
        result.pop("_ownerToken", None)
        result.pop("_memberToken", None)
        for member in result["members"]:
            member.pop("_accessToken", None)
        return result

    def save(self) -> None:
        """Persist in-place group changes made by API handlers."""
        self._persist()


store = MockStore()
