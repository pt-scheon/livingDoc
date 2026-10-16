# LivingDoc: The Self-Updating Business Brain

**A small business runs on memory, favours and one person's long days. LivingDoc turns the owner's messy notes and the
scanner's stock events into a live business page, and warns about shortages (including festival surges and supplier
shutdowns) before they happen.**

It is a real client/server application: a **FastAPI + SQLite backend** exposing a documented REST API, and a
**modular JavaScript frontend** (no build step) that talks to it. The interface works in **English, Hindi and Gujarati**.

```
┌───────────────────────── Browser: frontend/ ─────────────────────────┐
│  notes · scanner feed · inventory · cash · promises · forecast · risks│
│  store (state) · api client · i18n (EN/HI/GU) · safe DOM rendering    │
└───────────────────────────────┬───────────────────────────────────────┘
                                │ REST / JSON  (OpenAPI docs at /docs)
┌───────────────────────────────▼───────────────────────────────────────┐
│ Backend: FastAPI  (backend/app/api.py, validation with pydantic)      │
│                                                                       │
│  services/extraction   LLM → JSON deltas only → validated → applied   │
│  services/scanner      folder inbox + HTTP events, idempotent         │
│  services/inventory    deterministic stock math + audit               │
│  services/ledger       cash (FIFO debt settlement) + promises         │
│  services/document     state → structured JSON / Markdown             │
│  services/sync         hourly multi-branch sync via a shared hub      │
│  engine.py             festive prediction engine (pure Python)        │
│  workers.py            background loop: scanner inbox + hourly sync   │
└───────────────────────────────┬───────────────────────────────────────┘
                                │
                        SQLite (WAL, one file)
```

**The AI never rewrites the document.** The LLM only extracts events as JSON
(`inventory_deltas`, `cash_events`, `promises`, `quiet_risk`). The output is validated and sanitised, then plain code
adds and subtracts in SQLite, and the page is rebuilt from the database every time. If no LLM is reachable, a
deterministic English rule parser takes over, so the app keeps working.

## Features

| Area | What it does |
|---|---|
| **Notes → page** | Type or speak a ramble ("sold 4 coffees, Dave paid ₹500 cash, remind me to order beans"). Stock, cash and promises update, and the extracted JSON is shown so nothing is a black box. |
| **Inventory** | Live counts, ⚠️ low-stock alerts, days left from real usage, add/edit items, physical counts that log a correction. |
| **Cash & invoices** | Total collected, collected today, pending debts per customer. A payment settles that customer's oldest debt first. |
| **Handshakes & promises** | Checklist (`[ ]` / `[x]`) created from notes, tick them off in the page. |
| **Quiet breakage warnings** | Automatic detection: out of stock, will run out before the supplier can deliver, overdue debts, one customer holding most of the unpaid money, stale promises, silent scanner, lagging branch sync, sales drop, placeholder items awaiting review. Warnings noted from your notes can be marked done. |
| **Festive predictions** | Surge multiplier, supplier blackout buffer, reorder deadline so stock arrives 48 h before the surge, perishable overstock guard. Editable festival calendar and lead time. |
| **Scanner** | Accepts files (`.json`, `.jsonl`, `.csv`) dropped in a folder **or** JSON posted to the API. Duplicate-safe, never lets stock go negative, flags problems instead of crashing. |
| **Multi-branch** | Stock movements upload hourly to a shared hub and are pulled by every other branch. Repeat syncs change nothing. |
| **Languages** | English, हिन्दी, ગુજરાતી for the whole interface and for generated warnings. |
| **Voice input** | A microphone button uses the browser's built-in speech recognition (where the browser supports it) in the selected language. |

## Quick start

You need Python 3.10 or newer. No Node.js, no database server, no build step.

```bash
git clone <your-repo-url> livingdoc
cd livingdoc/backend
python3 -m venv .venv && source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python -m uvicorn app.main:app --port 8000
```

Open **http://localhost:8000**. The first start creates `livingdoc.db` with starter data (a sweet shop and café with two
branches, 3 weeks of stock history, customers who owe money, open promises and a festival calendar).
Interactive API docs are at **http://localhost:8000/docs**.

Run it with a single worker (the default). The background loop (scanner inbox and hourly sync) runs inside the app process.
`make install`, `make run` and `make test` do the same from the repository root.

### Try it in two minutes

1. In **Talk or type your day**, paste: `Sold 4 milks, used 2 coffee beans, Dave paid Rs 500 cash, reminded me to order beans` and click **Update my business page**. Milk and coffee go down, Dave's debt drops by ₹500, and the promise appears.
2. Open **Simulate a scan**, pick *Ghee*, quantity 3, direction *Out*, and scan. The stock and the movement feed update.
3. Look at **Early Shortage Predictions**. Click **Why** on a row to read the explanation.
4. Switch language with the buttons at the top. Open **Settings** to edit the festival calendar and supplier lead time, then watch the order-by dates move.

### Connect an LLM (recommended, needed for Hindi/Gujarati notes)

Any OpenAI-compatible endpoint works. The default is a local [Ollama](https://ollama.com):

```bash
ollama pull llama3.1
python -m uvicorn app.main:app --port 8000      # defaults: LLM_BASE_URL=http://localhost:11434/v1
```

For OpenAI instead:

```bash
export LLM_BASE_URL=https://api.openai.com/v1 LLM_API_KEY=sk-... LLM_MODEL=gpt-4o-mini
```

The header badge shows whether the AI is online. Each note shows which reader handled it and the exact JSON it produced.
Without an LLM, the simple reader understands English only.

## Configuration (environment variables)

| Variable | Default | Meaning |
|---|---|---|
| `LIVINGDOC_DB` | `livingdoc.db` | Local database file |
| `LIVINGDOC_HUB` | `livingdoc_hub.db` | Shared hub for branch sync (put it on a path every branch can reach) |
| `LIVINGDOC_SCANNER_INBOX` | `scanner_inbox` | Folder the scanner writes to |
| `LIVINGDOC_SCANNER_POLL_SECONDS` | `10` | How often the inbox is checked |
| `LIVINGDOC_SYNC_SECONDS` | `3600` | Branch sync interval |
| `LIVINGDOC_LEAD_DAYS` | `3` | Default supplier lead time (editable in Settings) |
| `LIVINGDOC_WORKERS` | `1` | `0` disables the background loop |
| `LIVINGDOC_CORS_ORIGINS` | `*` | Allowed origins when the frontend is hosted elsewhere |
| `LIVINGDOC_FRONTEND` | `../frontend` | Folder served at `/` |
| `LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL`, `LLM_TIMEOUT` | Ollama / `llama3.1` / 45 s | LLM connection |

## REST API

Full, interactive reference at `/docs` (Swagger) and `/redoc`. Summary:

| Method & path | Purpose |
|---|---|
| `GET /api/health`, `GET /api/config`, `GET /api/branches` | Status, settings (incl. AI online/offline), branch list |
| `GET /api/document?branch=&lang=` | The whole page as structured JSON |
| `GET /api/document.md?branch=&lang=` | The same page as Markdown |
| `POST /api/notes` | Submit a note: LLM extraction, then deterministic update |
| `GET /api/notes`, `GET /api/movements` | Recent notes (with extracted JSON), recent stock movements |
| `GET /api/items`, `PUT /api/items` | List items; create/update an item and optionally record a physical count |
| `POST /api/scanner/events` | Push scanner events as JSON |
| `POST /api/scanner/poll` | Process the scanner inbox folder now |
| `POST /api/sync`, `GET /api/sync/status` | Branch sync now / status |
| `GET/POST/DELETE /api/festivals`, `PUT /api/settings/lead-days` | Festival calendar and supplier lead time |
| `PATCH /api/promises/{id}`, `POST /api/risks/{id}/resolve` | Tick a promise, mark a noted warning done |
| `GET /api/audit` | Check that every stock count equals the sum of its movement log |

## Connecting the scanner

The scanner hardware is assumed to already work. It only has to deliver events in one of two ways.

**1. Files:** write a `.json`, `.jsonl` or `.csv` file into `backend/scanner_inbox/` (write under a temporary name, then rename).
Examples are in [`examples/`](examples).

**2. HTTP:**

```bash
curl -X POST localhost:8000/api/scanner/events -H 'Content-Type: application/json' \
  -d '{"branch":"Main Store","events":[{"event_id":"scan-0001","sku":"ITM-GHEE","qty":3,"direction":"out"}]}'
```

| Field | Notes |
|---|---|
| `sku` and/or `item` | Barcode and/or item name (at least one) |
| `qty` | Positive number, default 1 |
| `direction` | `in` or `out` |
| `event_id` | Recommended: makes re-delivery harmless |
| `branch`, `ts` | Optional |

| Problem | What happens |
|---|---|
| Same event delivered twice | Ignored (by `event_id`) |
| Stock would go below zero | Clamped to 0 and flagged: a delivery was probably never scanned |
| Unknown barcode, known item name | The barcode is learned for next time |
| Unknown barcode, no name | Placeholder item created and flagged for review |
| Bad quantity, bad direction, malformed event | That event is skipped and shown as a warning; the rest of the batch is applied |
| Unreadable file | Moved to `scanner_inbox/failed/` with an `.error.txt`, and a warning is shown |
| LLM down or returns junk | Output is validated; the rule parser takes over |
| Same note submitted twice within a minute | Not applied twice |

## The festive prediction engine

[`backend/app/engine.py`](backend/app/engine.py) is a standalone module. Run `python -m app.engine` from `backend/` to see the
self-test printing normal versus festive reorder dates.

1. **Surge:** burn rate × `surge_multiplier` for the 7 days before the festival and on the festival day.
2. **Blackout buffer:** adjusted lead time = standard lead time + `supplier_blackout_days`.
3. **Reorder deadline:** stock must arrive at least 48 hours before the surge begins and before the shelf runs empty; the earlier date wins.
4. **Perishable guard:** if a batch would outlive its shelf life after the festival, the order is capped and staged deliveries are suggested.

```python
from app.engine import predict_inventory
predict_inventory({"Gift Boxes": 30}, {"Gift Boxes": 2.0},
                  [{"name": "Diwali", "date": "2026-11-01", "surge_multiplier": 2.8, "supplier_blackout_days": 4}],
                  lead_time_days=3, today="2026-10-16")
```

For that input the engine reports a festive burn of 5.6/day, 5.3 days of stock instead of 15, an adjusted lead time of
7 days (3 + 4) and an order-by date of **16 Oct 2026 (today)**, versus 28 Oct without the festival.

## Tests

```bash
cd backend && pip install -r requirements-dev.txt && python -m pytest -q tests     # 27 tests
pip install playwright && playwright install chromium && python ../e2e/browser_smoke.py   # real browser, 9 checks
```

The backend tests cover the engine, extraction and validation (including a fake LLM and garbage LLM output), stock math,
FIFO debt settlement, scanner edge cases, branch sync convergence, and every API route (including 40 parallel scanner requests
leaving the stock exactly consistent). The browser test drives the real UI: submits a note, scans, switches language, edits
the festival calendar, checks that markup in a note is shown as text rather than executed, and checks for no horizontal
scrolling on a phone-sized screen.

## Project layout

```
backend/
  app/
    main.py          app factory: API + static frontend + background workers
    api.py           REST routes (thin: validate, call a service, return JSON)
    schemas.py       request validation (pydantic)
    config.py        environment settings
    database.py      SQLite schema and connection helpers
    engine.py        festive prediction engine
    i18n.py          server-side translations (EN/HI/GU)
    workers.py       background loop (scanner inbox + hourly sync)
    services/        extraction · inventory · ledger · scanner · sync · document · catalog · seed
  tests/             pytest suite
frontend/
  index.html  config.js  css/
  js/                main.js · api.js · store.js · i18n.js · format.js · dom.js · toast.js
  js/components/     header · notes · scanner · inventory · cash · promises · forecast · risks · settings
e2e/                 browser smoke test (Playwright)
examples/            sample scanner files and notes
```

## Hosting the frontend separately

By default the backend serves the frontend at `/`, so one command runs everything. To host the frontend elsewhere (any
static host), set `window.LIVINGDOC_API` in [`frontend/config.js`](frontend/config.js) to the API's address and start the backend with
`LIVINGDOC_CORS_ORIGINS=https://your-frontend-origin`.

## Limitations (please read before using it for a real shop)

- **No login.** Anyone who can reach the server can read and change the data. Keep it on `127.0.0.1` or inside the shop's network, and put it behind a reverse proxy with authentication before exposing it to the internet.
- **Branch sync** covers stock movements only; cash and promises stay per branch. The "hub" is a SQLite file on a shared path, which suits a few branches, not a large chain.
- **"Owed" means a customer owes the business.** Money the business owes suppliers is not modelled.
- **Voice input** relies on the browser's speech recognition; support for Hindi and Gujarati varies by browser, and it has not been tested here.
- **Hindi/Gujarati notes need an LLM.** The offline reader is English only. Forecast "Why" explanations are in English; headings, tables, buttons and warnings are translated.
- **Starter data is made up.** Festival dates (Diwali 8 Nov 2026, Christmas, Uttarayan) and surge multipliers are starting guesses; set your own in Settings. Predictions improve as real usage is logged (burn rate is learned from the last 30 days).
- **Times** are shown in the server's local time zone.

## License

MIT, see [`LICENSE`](LICENSE).
