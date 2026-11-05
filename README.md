# POS Metropolitano API

Python 3.12 / FastAPI backend for the POS Metropolitano web and mobile apps.
Spec: `API_ENDPOINTS.md` (base path `/api/v1`).

**Implemented so far:** Module 1 Auth & Session, Module 2 Settings, Module 3 Users (admin) — 9 endpoints.

| Endpoint | Auth |
|---|---|
| `POST /auth/login` | none |
| `POST /auth/logout` | any |
| `GET /auth/me` | any |
| `GET /settings` | any |
| `PUT /settings` | admin |
| `GET /users`, `POST /users` | admin |
| `PATCH /users/{id}/active` | admin |
| `PUT /users/{id}/password` | admin |

## Setup

Requires Python **3.12**.

```bash
python3.12 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
cp .env.example .env     # optional
.venv/bin/uvicorn app.main:app --reload
```

Interactive docs: http://localhost:8000/docs · health check: `GET /health`.

## Configuration (env vars / `.env`)

| Variable | Default | Notes |
|---|---|---|
| `POS_DB_PATH` | `data/pos.db` | Same variable the Node app uses; point both at one file to share data. `DATABASE_PATH` also works. |
| `COOKIE_SECURE` | `false` | Set `true` behind HTTPS. |
| `CORS_ORIGINS` | *(empty)* | Comma-separated web origins; enables credentialed CORS. |
| `SEED_ADMIN_*`, `SEED_CASHIER_*`, `SEED_COOK_*` | `admin`/`admin123`, `cashier`/`cashier123`, `kitchen`/`kitchen123` (role `cook`) | Created only if the `users` table is empty. **Change the passwords.** |

## Database

The schema in `app/db.py` mirrors the Node app's `src/lib/db/schema.ts` (all 11 tables), including its
column migrations and the `users.role` rebuild for databases that predate the `cook` role, so either app can
open and upgrade the same SQLite file. Keep the two in sync when the schema changes.

On first start (empty `users` table) the API creates `admin`, `cashier` and `kitchen`. To also load the sample
menu, ingredients and Ham Sandwich recipe from the Node app's `seed.ts` (safe to re-run):

```bash
.venv/bin/python -m app.seed
```

## Tests

```bash
.venv/bin/pytest
```

## Behaviour worth knowing

- **Auth** accepts `Authorization: Bearer <token>` (mobile) or the `pos_session` cookie (web); Bearer wins if both are sent. Tokens are 32 random bytes (hex); only their SHA-256 is stored. Sessions last 7 days.
- **Compatibility with the Node app:** `sessions.expires_at` is written as a JS-style ISO string (`…T…:…:….mmmZ`) because it is compared as text; passwords use bcrypt cost 10 (`$2b$`, readable by `bcryptjs`), and are truncated to 72 bytes like `bcryptjs`.
- **Errors** are always `{"error": "message"}`. Login and `PUT /settings` return the fixed 422 messages from the spec; other 422s return the first validation message.
- **Decisions where the spec offered a choice:**
  - Changing your own `active` flag → `403`.
  - `PATCH /users/{id}/active` and `PUT /users/{id}/password` for an unknown user → `404 User not found`.
  - Resetting a password revokes all of that user's sessions, including the admin's own if they reset themselves.
  - `taxRatePercent` must be a JSON number (strings/booleans are rejected).
- The "last admin" guard in `set_user_active` can't be hit over HTTP (the caller is always another active admin), but is kept and unit-tested for concurrent callers.

## Layout

```
app/
  main.py        app factory, CORS, routers
  config.py      env settings, constants
  db.py          SQLite connection, transactions, full schema, migrations, seed users
  seed.py        sample menu/ingredients/recipe (`python -m app.seed`)
  security.py    bcrypt + token hashing
  errors.py      ApiError + {"error": ...} handlers
  schemas.py     camelCase Pydantic models
  deps.py        auth / role guards (AnyUser, AdminUser)
  services/      sessions, settings, users (business logic)
  routers/       auth, settings, users
tests/           pytest suite
```

Modules 4–13 only need a router and services each (the tables already exist); `deps.py` still needs a `cashier+` guard for Module 6+.

## License

[MIT](LICENSE)
