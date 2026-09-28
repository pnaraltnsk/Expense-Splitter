# Expense Splitter

Expense Splitter (Owesome) helps a group track shared expenses, see who owes whom, and report and confirm repayments. It supports separate groups, multiple currencies, equal or custom expense splits, recurring expense schedules, and simplified balances.

The app has a React frontend and a FastAPI backend. Backend data is stored with SQLAlchemy, using SQLite by default. Groups do not require accounts: private owner and member links grant access, so keep those links confidential.

## Requirements

- Python 3.11 or newer
- [uv](https://docs.astral.sh/uv/)
- Node.js and npm
- GNU Make is optional; on Windows, use the PowerShell commands below if Make is not installed

## Run locally

Start the backend in one terminal from the repository root:

```powershell
uv --directory backend sync
uv --directory backend run uvicorn app.main:app --reload
```

Or, on Windows PowerShell, run the included helper:

```powershell
.\run-backend.ps1
```

Start the frontend in a second terminal:

```powershell
cd frontend
npm install
npm run dev
```

Open the URL Vite prints, usually `http://localhost:5173`. The frontend calls the backend at `http://127.0.0.1:8000` by default. To use a different API address, set `VITE_API_BASE_URL` before starting Vite:

```powershell
$env:VITE_API_BASE_URL = "http://127.0.0.1:8000"
npm run dev
```

Interactive API documentation is available at `http://127.0.0.1:8000/docs`.

## Database configuration

The backend reads `DATABASE_URL`, a SQLAlchemy database URL. With no value set, it uses SQLite at `backend/data/owesome.db`. For example, from the repository root in PowerShell:

```powershell
$env:DATABASE_URL = "sqlite:///./data/owesome.db"
uv --directory backend run uvicorn app.main:app --reload
```

The previous local JSON data file (`backend/data/groups.json`) is imported on first startup when using the default database and the database has no groups. The source file is left in place. Both the database and JSON data directory are ignored by Git.

The repository uses SQLAlchemy's portable JSON type. To configure PostgreSQL later, install a compatible driver and set a URL such as `postgresql+psycopg://user:password@host:5432/database`.

## Tests

Run all backend endpoint and database tests from the repository root:

```powershell
uv --directory backend run pytest
```

Or from `backend/`:

```powershell
uv run pytest
```

GNU Make is also supported where installed:

```sh
make test
```

## Build the frontend

```sh
cd frontend
npm run build
```

## Project layout

```text
frontend/       React app and centralized backend API client
backend/app/    FastAPI routes, SQLAlchemy store, and request schemas
backend/tests/  API and database tests
openapi.yaml    Backend API contract
_docs/specs.md  Product requirements and access rules
```

## Access and privacy

There are no user accounts or password recovery. Anyone with an owner link has full control of that group; member links provide member-level access. Keep these links private. Without a saved browser session or a valid link, a group cannot currently be recovered by its name.
