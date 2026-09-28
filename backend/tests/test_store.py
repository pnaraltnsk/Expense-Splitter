import json

from sqlalchemy.engine import URL

from app.store import DatabaseStore


def test_database_url_environment_selects_persistent_database(tmp_path, monkeypatch) -> None:
    database_path = tmp_path / "configured.db"
    database_url = URL.create("sqlite", database=str(database_path)).render_as_string()
    monkeypatch.setenv("DATABASE_URL", database_url)

    first_store = DatabaseStore()
    created = first_store.create_group("Configured", "EUR", "Pat")
    restarted_store = DatabaseStore(database_url)

    assert first_store.storage_path == database_path
    assert restarted_store.group_for_token(created["_ownerToken"])["id"] == created["id"]


def test_legacy_json_groups_are_imported_with_their_credentials(tmp_path) -> None:
    legacy_store = DatabaseStore(tmp_path / "legacy-source.db")
    created = legacy_store.create_group("Legacy", "EUR", "Pat")
    legacy_file = tmp_path / "groups.json"
    legacy_file.write_text(json.dumps({created["id"]: created}), encoding="utf-8")
    migrated_store = DatabaseStore(tmp_path / "new-database.db")

    migrated_store._migrate_legacy_json(legacy_file)

    recovered = migrated_store.group_for_token(created["_ownerToken"])
    assert recovered is not None
    assert recovered["name"] == "Legacy"
    assert migrated_store.group_for_token(created["_memberToken"])["id"] == created["id"]
    assert legacy_file.exists()


def test_legacy_import_does_not_overwrite_an_initialized_database(tmp_path) -> None:
    legacy_store = DatabaseStore(tmp_path / "legacy-source.db")
    legacy_group = legacy_store.create_group("Legacy", "EUR", "Pat")
    legacy_file = tmp_path / "groups.json"
    legacy_file.write_text(json.dumps({legacy_group["id"]: legacy_group}), encoding="utf-8")
    current_store = DatabaseStore(tmp_path / "current.db")
    current_group = current_store.create_group("Current", "USD", "Alex")

    current_store._migrate_legacy_json(legacy_file)

    assert current_store.group_for_token(current_group["_ownerToken"])["name"] == "Current"
    assert current_store.group_for_token(legacy_group["_ownerToken"]) is None
