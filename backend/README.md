# Owesome API

FastAPI backend for the contract in the repository-root `openapi.yaml`. Group data is stored through SQLAlchemy. By default, the app uses SQLite at `backend/data/owesome.db`; the first startup imports groups from the previous `backend/data/groups.json` file if the database is empty.

Set `DATABASE_URL` to select a different SQLAlchemy-supported database. For example, from this directory in PowerShell:

```powershell
$env:DATABASE_URL = "sqlite:///./data/owesome.db"
uv run uvicorn app.main:app --reload
```

For PostgreSQL later, configure a SQLAlchemy URL such as `postgresql+psycopg://user:password@host:5432/database` and add the matching PostgreSQL driver with `uv add psycopg[binary]`. The models use SQLAlchemy's portable JSON type; no SQLite-specific query syntax is used by the repository.

## Run locally

From this directory, with `uv` installed:

```powershell
uv sync
uv run uvicorn app.main:app --reload
```

The API is available at `http://127.0.0.1:8000`; interactive docs are at `/docs` and the generated OpenAPI document is at `/openapi.json`.

## Run endpoint tests

```powershell
uv run pytest
```

Owner and member tokens are returned only when a group is created. Supply the same token in the route and as `Authorization: Bearer <token>`. Member credentials can read group data and balances and report settlements; owner credentials can also manage members, expenses, settings, recurring schedules, and confirm settlements.
