# Architecture map

**Backend** (`backend/app`): FastAPI. `main.py` builds the app and includes routers; `auth.py` guards `/api/*` when `LIVINGDOC_ADMIN_PASSWORD` is set (allow-list `PUBLIC`); `security.py` adds headers; `database.py` holds the SQLite schema (applied at every start, `IF NOT EXISTS`).

| Area | Service (`app/services`) | Routes |
|---|---|---|
| Stock, notes, promises, risks | `inventory.py`, `ledger.py`, `catalog.py`, `document.py`, `extraction.py`, `scanner.py`, `sync.py`, `seed.py` | `api.py` |
| Forecast, pricing, scorecard | `forecasting.py` (+ `foresight/` package) | `forecast_api.py` (incl. `/api/forecast/chart.png`) |
| Trust ledger, proofs, cash flow | `trust.py`, `proofs.py`, `cashflow.py` | `trust_api.py` |
| Public page, AI helper (drafts only) | `presence.py`, `demo_storefront.py` | `presence_api.py` |
| Sign up / sign in / invites | `accounts.py` (+ `auth.py` guard) | `auth.py` (`/api/auth/*`) |
| **Feedback** (owner to developer, customer to owner) | `feedback.py` | `feedback_api.py` |

**Auth tables** `users(id,email,name,role owner|staff,pw_hash,created_at,last_login)`, `invites(code_hash,role,expires_at,used_by,hint)`; session secret in `meta.session_secret`. Routes: `POST /api/auth/signup|login|logout|password`, `GET /api/auth/status|users`, `POST/DELETE /api/auth/invites`, `DELETE /api/auth/users/{id}`.

**Feedback table** `feedback(id, branch, source owner|customer, category bug|idea|confusing|praise, rating, text, name, contact, lang, screen, created_at, status new|seen|planned|done|dismissed, dev_note)`.
Routes: `GET/POST /api/feedback`, `PATCH /api/feedback/{id}`, `GET /api/feedback/export.md` (owner suggestions only), public `POST /api/presence/public/{slug}/feedback`.

**Frontend** (`frontend/`, no build step): `index.html` (app), `shop.html` (public page), `party.html` (counterparty page). `js/main.js` boots and routes (`#/overview|stock|money|forecast|trust|found`); `js/components/*` are screens; `js/api.js` is the only place that calls the backend; strings live in `js/i18n*.js` (EN, HI, GU all required for every key); `h()` in `js/dom.js` builds DOM from text nodes.

**Tests:** `backend/tests` (pytest, fresh seeded DB per test via `conftest.py`), `e2e/browser_smoke.py` (Playwright, starts its own servers).

**Env:** `LIVINGDOC_DB`, `LIVINGDOC_ADMIN_PASSWORD`, `LIVINGDOC_DEMO_STOREFRONT`, `LIVINGDOC_CSP`, LLM keys in `.env.example`.
