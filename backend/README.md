# Owesome API

FastAPI backend for the contract in the repository-root `openapi.yaml`. The current repository is an in-memory mock: all group data is lost when the process restarts. Replace `app.store.MockStore` with a persistent repository when adding PostgreSQL.

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
