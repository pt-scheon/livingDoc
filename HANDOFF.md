# Handoff for a coding agent (Antigravity or similar)

Goal: review this finished project, commit it to a Git remote, and deploy it. Do not rewrite features.

## State of the repo
- Complete, tested product: FastAPI + SQLite backend, vanilla-JS frontend, EN/HI/GU. `git log` already holds the history. The working tree should be clean; if it is not, commit the changes as one commit.
- Backend tests: `cd backend && pip install -r requirements-dev.txt && python -m app.engine && python -m pytest -q tests` (127 tests expected).
- Browser test: `pip install playwright && playwright install chromium && python e2e/browser_smoke.py` (42 checks, starts its own servers on ports 8799 and 8800).
- Container: `Dockerfile`, `docker-compose.yml`, `render.yaml`, `fly.toml`, `.env.example`. CI in `.github/workflows/ci.yml` runs tests, the browser test and a Docker smoke test.

## Do this, in order
1. Run both test commands above. If anything fails, fix only that and say what you changed.
2. Create an empty GitHub repository (private is fine), then:
   ```bash
   git remote add origin https://github.com/<owner>/<repo>.git
   git branch -M main
   git push -u origin main
   ```
3. Never commit: `.env`, `*.db`, `*.db-wal`, `scanner_inbox/`. `.gitignore` already excludes them; check `git status` before every commit.
4. Deploy with `DEPLOY.md` (Render blueprint is the shortest path). `LIVINGDOC_ADMIN_PASSWORD` is **required**: ask the owner for it or generate a long random one and give it to them once. Never write it into a file in the repo.
5. After deploy, verify: `/api/health` returns `{"status":"ok"}`; `/api/document` returns 401 without a session; the site loads and sign-in works; `/shop.html?s=main-store` shows "not available" until the owner publishes it.

## Rules the code depends on (keep them)
- User text is inserted as text nodes only (`h()` helper); never use `innerHTML` with data.
- Private by default: trust-ledger entries and public-page fields count only when the owner opts in; proofs hold only bands, never names or amounts.
- The AI helper may only draft. It must never publish, edit the profile or spend.
- Forecast and pricing numbers that rest on guesses are labelled as assumptions in the UI.

## Known limits (do not hide them in docs)
- One shared owner password, no per-user accounts. The proof is a signed, spot-checkable attestation, not zero-knowledge. No ad platform is connected. SQLite means one instance and a persistent volume.

## Suggested commit message if one is needed
`Polish: new interface, owner login, container and hosting config`
