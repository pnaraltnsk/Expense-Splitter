from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
import json
import os
from pathlib import Path
from secrets import token_urlsafe
from typing import Any
from uuid import uuid4

from sqlalchemy import JSON, ForeignKey, String, create_engine, delete, event, select
from sqlalchemy.engine import URL, make_url
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def new_id() -> str:
    return str(uuid4())


class Base(DeclarativeBase):
    pass


class GroupRecord(Base):
    __tablename__ = "groups"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    data: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class AccessTokenRecord(Base):
    __tablename__ = "access_tokens"

    token: Mapped[str] = mapped_column(String(128), primary_key=True)
    group_id: Mapped[str] = mapped_column(ForeignKey("groups.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    member_id: Mapped[str | None] = mapped_column(String(36), nullable=True)


class DatabaseStore:
    """SQLAlchemy-backed persistence for group documents and bearer-token lookup."""

    def __init__(self, database_url: str | URL | Path | None = None) -> None:
        self._compat_groups: dict[str, dict] | None = None
        self._engine = None
        self._session_factory = None
        self._configured_url: URL | None = None
        self.configure(database_url)

    @staticmethod
    def _resolve_url(database_url: str | URL | Path | None) -> URL:
        if isinstance(database_url, Path):
            url = URL.create("sqlite", database=str(database_url.expanduser().resolve()))
        elif database_url is not None:
            url = make_url(str(database_url))
        elif os.environ.get("DATABASE_URL"):
            url = make_url(os.environ["DATABASE_URL"])
        else:
            default_path = Path(__file__).resolve().parent.parent / "data" / "owesome.db"
            url = URL.create("sqlite", database=str(default_path))

        if url.get_backend_name() == "sqlite":
            database = url.database
            if database and database != ":memory:":
                Path(database).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)
        return url

    def configure(self, database_url: str | URL | Path | None = None) -> None:
        """Select a SQLAlchemy URL, create the engine, and initialize tables."""
        if self._engine is not None:
            self._engine.dispose()
        url = self._resolve_url(database_url)
        connect_args = {"check_same_thread": False} if url.get_backend_name() == "sqlite" else {}
        engine = create_engine(url, connect_args=connect_args, pool_pre_ping=True)
        if url.get_backend_name() == "sqlite":
            @event.listens_for(engine, "connect")
            def _enable_sqlite_foreign_keys(dbapi_connection, _connection_record) -> None:
                cursor = dbapi_connection.cursor()
                cursor.execute("PRAGMA foreign_keys=ON")
                cursor.close()

        Base.metadata.create_all(engine)
        self._engine = engine
        self._session_factory = sessionmaker(bind=engine, expire_on_commit=False)
        self._configured_url = url
        self._compat_groups = None
        if database_url is None and not os.environ.get("DATABASE_URL"):
            self._migrate_legacy_json()

    def _migrate_legacy_json(self, legacy_path: Path | None = None) -> None:
        """Import the old JSON store once, leaving its source file untouched."""
        legacy_path = legacy_path or Path(__file__).resolve().parent.parent / "data" / "groups.json"
        if not legacy_path.exists():
            return
        try:
            legacy_groups = json.loads(legacy_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return
        if not isinstance(legacy_groups, dict) or not legacy_groups:
            return
        with self._session_factory.begin() as session:
            if session.scalar(select(GroupRecord.id).limit(1)) is not None:
                return
            migrated_groups = []
            for group_id, group in legacy_groups.items():
                if not isinstance(group, dict) or not group.get("_ownerToken") or not group.get("_memberToken"):
                    continue
                session.add(GroupRecord(id=group_id, data=group))
                migrated_groups.append(group)
            session.flush()
            for group in migrated_groups:
                session.add_all(self._tokens_for_group(group))

    @property
    def database_url(self) -> str:
        return self._configured_url.render_as_string(hide_password=True)

    @property
    def storage_path(self) -> Path:
        """Compatibility property used by local scripts and older tests."""
        if self._configured_url.get_backend_name() != "sqlite" or self._configured_url.database == ":memory:":
            raise RuntimeError("storage_path is only available when using a file-backed SQLite database")
        return Path(self._configured_url.database)

    @storage_path.setter
    def storage_path(self, path: Path) -> None:
        self.configure(Path(path))

    def reset(self) -> None:
        with self._session_factory.begin() as session:
            session.execute(delete(AccessTokenRecord))
            session.execute(delete(GroupRecord))
        self._compat_groups = None

    @property
    def groups(self) -> dict[str, dict]:
        """A temporary compatibility view for older development helpers."""
        if self._compat_groups is None:
            with self._session_factory() as session:
                rows = session.scalars(select(GroupRecord)).all()
                self._compat_groups = {row.id: deepcopy(row.data) for row in rows}
        return self._compat_groups

    @property
    def token_to_group(self) -> dict[str, str]:
        with self._session_factory() as session:
            return {row.token: row.group_id for row in session.scalars(select(AccessTokenRecord)).all()}

    @property
    def token_to_member(self) -> dict[str, str]:
        with self._session_factory() as session:
            return {row.token: row.member_id for row in session.scalars(select(AccessTokenRecord)).all() if row.member_id is not None}

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
        self.save(group)
        return deepcopy(group)

    def group_for_token(self, token: str) -> dict | None:
        with self._session_factory() as session:
            token_record = session.get(AccessTokenRecord, token)
            if token_record is None:
                return None
            record = session.get(GroupRecord, token_record.group_id)
            return deepcopy(record.data) if record is not None else None

    def group_by_id(self, group_id: str) -> dict | None:
        with self._session_factory() as session:
            record = session.get(GroupRecord, group_id)
            return deepcopy(record.data) if record is not None else None

    def delete_group(self, group_id: str) -> None:
        with self._session_factory.begin() as session:
            session.execute(delete(AccessTokenRecord).where(AccessTokenRecord.group_id == group_id))
            session.execute(delete(GroupRecord).where(GroupRecord.id == group_id))
        self._compat_groups = None

    def member_id_for_token(self, token: str) -> str | None:
        with self._session_factory() as session:
            record = session.get(AccessTokenRecord, token)
            return record.member_id if record is not None else None

    def add_member(self, group: dict, name: str) -> dict:
        member_id = new_id()
        access_token = token_urlsafe(32)
        member = {"id": member_id, "name": name.strip(), "_accessToken": access_token}
        group["members"].append(member)
        self.save(group)
        return {"id": member_id, "name": name.strip(), "accessToken": access_token}

    def ensure_member_access_token(self, group: dict, member_id: str) -> str:
        member = next((item for item in group["members"] if item["id"] == member_id), None)
        if member is None:
            raise KeyError(member_id)
        access_token = member.get("_accessToken")
        if not access_token:
            access_token = token_urlsafe(32)
            member["_accessToken"] = access_token
        self.save(group)
        return access_token

    def public_group(self, group: dict) -> dict:
        result = deepcopy(group)
        result.pop("_ownerToken", None)
        result.pop("_memberToken", None)
        for member in result["members"]:
            member.pop("_accessToken", None)
        return result

    def save(self, group: dict | None = None) -> None:
        """Persist a modified group document and refresh its indexed credentials."""
        groups = [group] if group is not None else list(self.groups.values())
        if not groups:
            return
        with self._session_factory.begin() as session:
            for group_data in groups:
                group_id = group_data["id"]
                data = deepcopy(group_data)
                record = session.get(GroupRecord, group_id)
                if record is None:
                    record = GroupRecord(id=group_id, data=data)
                    session.add(record)
                else:
                    record.data = data
                session.execute(delete(AccessTokenRecord).where(AccessTokenRecord.group_id == group_id))
                session.add_all(self._tokens_for_group(data))
                if self._compat_groups is not None:
                    self._compat_groups[group_id] = data

    @staticmethod
    def _tokens_for_group(data: dict) -> list[AccessTokenRecord]:
        group_id = data["id"]
        tokens = [
            AccessTokenRecord(token=data["_ownerToken"], group_id=group_id, role="owner", member_id=data["ownerMemberId"]),
            AccessTokenRecord(token=data["_memberToken"], group_id=group_id, role="member", member_id=None),
        ]
        tokens.extend(
            AccessTokenRecord(token=member["_accessToken"], group_id=group_id, role="member", member_id=member["id"])
            for member in data["members"] if member.get("_accessToken")
        )
        return tokens


# Keep the old import name so existing app entry points and maintenance scripts remain valid.
MockStore = DatabaseStore


store = DatabaseStore()
