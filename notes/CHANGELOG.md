# Changelog (newest first)

Format: date, what, files, tests, left undone.

## 2026-10-17: Feedback system and agent notes
- **Owner to developer:** new "Feedback" tab in *Be found* where the shop owner sends a bug, idea, confusing screen or praise to the developer, and sees its status (sent / seen / planned / done / not now) plus the developer's note.
- **Customer to owner:** the public shop page has a rating + comment form (name and contact optional). Only the owner reads these (new tab shows average rating and comments). Honeypot field and 8-comments-per-shop-per-hour limit. Never exported to the developer notes.
- **Notes for agents:** `GEMINI.md`, `AGENTS.md`, `notes/`, `scripts/export_feedback.py`, `GET /api/feedback/export.md`.
- Files: `backend/app/services/feedback.py`, `feedback_api.py`, `database.py` (table `feedback`), `auth.py` (public POST `/api/presence/public/{slug}/feedback`), `frontend/js/components/presence.js`, `shop.js`, `api.js`, `i18n_presence.js`, `e2e/browser_smoke.py`.
- Tests: 134 backend (5 new in `tests/test_feedback.py`), 46 browser checks.
- Left undone: no email/WhatsApp notification to the owner when a comment arrives; one shared password means the owner and developer use the same sign-in.

## 2026-10-16: Public demo storefront, forecast chart image, free Render plan
- `LIVINGDOC_DEMO_STOREFRONT=1` seeds a sample published shop once (`services/demo_storefront.py`) and makes `/api/forecast/chart.png` public.
- New `GET /api/forecast/chart.png` (matplotlib). `render.yaml` now uses the free plan, no disk.

## 2026-10-16: Polish, login, hosting
- New interface ("Neel & Haldi" indigo/turmeric), optional owner login (`LIVINGDOC_ADMIN_PASSWORD`), security headers, Dockerfile, docker-compose, render.yaml, fly.toml, DEPLOY.md, HANDOFF.md.

## 2026-10-16: Be found, stay in control
- Owner-controlled public page and a drafts-only AI helper with audit log and spend cap (`services/presence.py`).

## 2026-10-16: Trust ledger, proof without exposure, promise-to-cashflow
- Two-sided ledger, signed band-level proofs (Merkle + Ed25519), Monte Carlo cash-flow predictor (`services/trust.py`, `proofs.py`, `cashflow.py`).

## 2026-10-16: Foresight and the FastAPI rebuild
- Demand forecast, pricing plan, owner factors, scorecard. Backend rebuilt as FastAPI + modular JS frontend.

## 2026-10-17 (upstream): Groq / OpenAI-compatible LLM config, `.env` support, README engineering-challenges section.
