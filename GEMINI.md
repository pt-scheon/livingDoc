# LivingDoc: notes for Gemini (and any coding agent)

Read this first, then `notes/README.md`. These files are the shared memory between the owner, the developer and the agents.

**What it is:** "The self-updating business brain" for small shops. FastAPI + SQLite backend, vanilla-JS frontend (no build step), English / Hindi / Gujarati.

## Where to look
| You want to know | Read |
|---|---|
| What changed and when (newest first) | `notes/CHANGELOG.md` |
| How the code is laid out, what each module owns | `notes/ARCHITECTURE.md` |
| What the shop owner asked the developer for | `notes/FEEDBACK.md` (generated, do not hand-edit) |
| Deploy / hosting | `DEPLOY.md`, `HANDOFF.md` |

## Run and test (do this before and after any change)
```bash
cd backend && pip install -r requirements-dev.txt
python -m app.engine && python -m pytest -q tests       # 134 tests expected
uvicorn app.main:app --port 8000                          # app at http://localhost:8000
pip install playwright && playwright install chromium && python e2e/browser_smoke.py   # browser checks
```

## Keep these rules (the product depends on them)
1. User text goes into the page as **text nodes only** (`h()` in `frontend/js/dom.js`). Never `innerHTML` with data.
2. **Private by default.** Ledger entries and public-page fields count only when the owner opts in. Proofs carry bands, never names or amounts.
3. The AI helper **only drafts**. It never publishes, edits the profile or spends.
4. Customer comments, names and contacts are visible **only to the owner**. They never reach the public page or `notes/FEEDBACK.md`.
5. Numbers resting on guesses are labelled as assumptions in the UI.
6. Never commit `.env`, `*.db`, passwords or `scanner_inbox/`.

## How to record your work (so the next agent can see it)
- After every change add an entry **at the top** of `notes/CHANGELOG.md`: date, what changed, files touched, tests run, anything left undone.
- If you change a module's job or add a route/table, update `notes/ARCHITECTURE.md`.
- Refresh the owner's requests with `python scripts/export_feedback.py` (writes `notes/FEEDBACK.md`), or `GET /api/feedback/export.md` while signed in. Mark a suggestion `planned` / `done` with `PATCH /api/feedback/{id}` and a short `dev_note`, so the owner sees progress in the app.
- Do not rewrite working features. Fix the failing thing, say what you changed.
