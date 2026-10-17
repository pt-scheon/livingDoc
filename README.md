# LivingDoc: The Self-Updating Business Brain

> A small shop runs on memory, favours and one person's long days. LivingDoc turns the owner's messy notes and the scanner's stock events into a live business page, keeps the shop's promises honest on both sides, forecasts demand without pretending to be certain, and lets the shop be found and trusted without handing itself over to a tool it cannot see inside.

**Jump to:** [Problem and users](#problem-and-intended-users) · [How each riddle shaped it](#how-each-riddle-shaped-the-project) · [Risks and limitations](#risks-and-limitations) · [Setup / run](#setup--run-instructions) · [Frontend Pack](#frontend-pack) · [Live links](#-live-working-links--api-endpoints) · [Notes for coding agents](GEMINI.md)

---

## Problem and intended users

**The problem.** From outside, a small business looks simple: someone sells something to someone. Inside, it runs on memory, favours, instinct and one person's long days. That person is the buyer, cashier, accountant and cleaner at once, so almost nothing is written down. What breaks first is whatever nobody tracks: a stock count that drifted, a promise that was never recorded, a debt open for two weeks, a supplier closing for the festival exactly when demand peaks. Big-company software does not fit: it needs data entry the owner has no time for, in a language and a vocabulary that is not theirs.

**Intended users**

| Who | What they need from LivingDoc |
|---|---|
| **The owner** of a shop, cafe or workshop (1 to a few branches), often more comfortable in Hindi or Gujarati than English | Talk or type the day the way they think; see stock, cash and promises on one page; be warned *before* something runs out or goes overdue |
| **Staff** the owner trusts | Use the app daily, without being able to invite, remove or see account management |
| **The owner's counterparties**: a customer who owes money, a supplier owed money, a friend who promised a favour | A private link to see exactly what is recorded about *them*, dispute it, or veto its use |
| **Customers and neighbours** | A public shop page that shows only what the owner chose to publish, a checkable trust badge, and a way to leave a rating and comment |
| **A bank or supplier** deciding whether to trust the shop | A signed proof of a few band-level facts that they can verify themselves, with no names or amounts exposed |
| **The developer** improving the product | Suggestions sent from inside the app (owner to developer), exported to `notes/FEEDBACK.md` |

**Not for:** large chains, regulated accounting or tax filing, or anyone who needs audited figures. See [Risks and limitations](#risks-and-limitations).

---

## How each riddle shaped the project

The project grew by answering four riddles in turn. Each one changed what was built and, just as much, what was deliberately left out.

### 1. "What does a small business run on, and what quietly breaks first?"
*It runs on memory, favours and one person's long days. What breaks first is what nobody writes down.*
- **Shaped:** the owner never fills in forms. They write or speak a ramble ("sold 4 coffees, Dave paid 500, remind me to order beans") and the page updates itself, in English, Hindi or Gujarati.
- **Design rule that came out of it:** *the AI never rewrites the document.* The model only extracts events as JSON; validated plain code does every addition and subtraction in SQLite, so the numbers stay auditable and the app still works with no AI at all (a rule reader takes over).
- **Where it shows:** notes to page, scanner feed, quiet-breakage warnings (out of stock, runs out before delivery, overdue debt, one customer holding most of the unpaid money, stale promises, silent scanner), and the festival engine that adds supplier blackout days to lead time.

### 2. "Which bets can a small business not take back?"
*Ordering stock and setting prices are bets made under uncertainty, with nobody to tell the owner how wrong they might be.*
- **Shaped:** the Forecast & Pricing module (Foresight). Every forecast is a range (50% and 80%), not a number; assumptions are labelled as assumptions; owner knowledge the data cannot see ("wedding nearby") is a factor that is pulled toward reality as real days are logged.
- **Design rule:** *grade the decision, not the outcome.* A scorecard grades only forecasts frozen before the day, on calibration, skill against a naive baseline, and counterfactual value of the price plan. Prep quantities are capped by real stock so the plan cannot promise what the shelf cannot deliver.

### 3. "A business is held together by promises. How do you keep them honest without exposing anyone?"
*Money owed, money we owe, favours, someone's word: every promise has two sides, and each side remembers it differently.*
- **Shaped:** the Trust ledger. Each promise keeps *both* figures; each person gets a private link to see, dispute and veto what is recorded about them; entries are private by default and count only if the owner opts in and the other person has not vetoed.
- **Proof without exposure:** the shop can sign a few band-level claims ("owed at least ₹5,000, by at least 2 people, nothing over N days late"). A verifier checks the signature and can spot-check by nonce. Names and amounts never leave. *(This is selective disclosure with a Merkle tree and an Ed25519 signature, not zero-knowledge; see limits.)*
- **Promise to cash flow:** open money promises feed a seeded Monte Carlo forecast with a 10/50/90% range of when cash actually arrives, using each person's track record.

### 4. "Machines can write, design and spend for you, but owners avoid tools they do not understand. What would it take to be found and trusted without handing yourself over?"
*The tools are powerful; the people who need them are not using them, because they cannot see inside.*
- **Shaped:** "Be found, stay in control". Nothing is public until the owner ticks it, field by field. The AI helper can **only draft**: it shows what each draft was built from, what it used and that it invented nothing, then waits. It cannot publish, edit the page or spend; the owner's budget cap covers *planned* spend only (no ad account is connected). Every action by the helper or the owner is in an activity log.
- **Trust, not hype:** the page can carry the signed trust badge from riddle 3, which visitors can verify. Visitors can leave a rating and comment that only the owner reads.

### What grew around the riddles
- **Feedback loop (owner to developer, customer to owner):** a place inside the app to tell the developer what is broken or confusing, and for customers to tell the shop what they think. Customer comments never reach the public page or the developer notes.
- **Accounts:** sign up, sign in, owner and staff roles, single-use invite codes, so a hosted copy is not a shared password.
- **Notes for coding agents:** [`GEMINI.md`](GEMINI.md), [`AGENTS.md`](AGENTS.md) and [`notes/`](notes/) hold the rules, changelog, architecture and owner feedback so any agent can pick up the work.

---

## Setup / run instructions

You need **Python 3.10+**. No Node.js, no database server, no build step.

### Run it on your computer (2 minutes)
```bash
git clone https://github.com/pt-scheon/livingdoc.git
cd livingdoc/backend
python3 -m venv .venv && source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python -m uvicorn app.main:app --port 8000
```
Open **http://localhost:8000**. The first start creates `livingdoc.db` with starter data (a sweet shop and cafe with two branches, three weeks of stock history, people who owe money, open promises and a festival calendar). Interactive API docs: **http://localhost:8000/docs**. From the repo root, `make install`, `make run`, `make test` do the same.

Run it with a **single worker** (the default): the scanner inbox and hourly sync run inside the app process.

The app starts **open** (no sign-in) so you can try it on `localhost`. Click **Create an account to lock it** in the sidebar to make the first (owner) account.

### Optional: an AI model for Hindi and Gujarati notes
Without one, an English-only rule reader is used. Any OpenAI-compatible endpoint works (Groq by default, OpenAI, or a local [Ollama](https://ollama.com)). Copy `backend/.env.example` to `backend/.env` and set `LLM_API_KEY` (see [Configuration](#configuration-environment-variables)).

### Put it on the internet
1. **Always** set `LIVINGDOC_ADMIN_PASSWORD` to a long passphrase. It is the **setup code** for creating the first owner account, so a stranger cannot claim your app.
2. Deploy with the files in the repo: `Dockerfile`, `docker-compose.yml`, `render.yaml` (free plan, no disk), `fly.toml`. Step by step in [`DEPLOY.md`](DEPLOY.md).
3. Open the site, choose **Create account**, enter your details and the setup code. You are the owner. Invite staff under **Account**.

### Run the tests
```bash
cd backend && pip install -r requirements-dev.txt
python -m app.engine && python -m pytest -q tests          # 146 backend tests
pip install playwright && playwright install chromium && python e2e/browser_smoke.py   # 53 browser checks
```

### Try it in two minutes
1. In **Talk or type your day**, paste: `Sold 4 milks, used 2 coffee beans, Dave paid Rs 500 cash, reminded me to order beans` and press **Update my business page**.
2. Open **Money**, then **Trust**: add a promise, copy a person's private link, and open it in a private window.
3. Open **Be found**, fill in your shop, tick what to show, use the helper to draft, approve, publish, then open the public page.
4. Open **Be found, then Feedback** to send a suggestion to the developer, then run `python scripts/export_feedback.py` to see it in `notes/FEEDBACK.md`.

---

## Frontend Pack

The whole browser side is available as a standalone pack you can host on any static host:

- **Download:** [`frontend-pack/livingdoc-frontend-pack.zip`](frontend-pack/livingdoc-frontend-pack.zip) (about 100 KB, rebuilt with `make pack`)
- **Pack guide:** [`frontend-pack/README.md`](frontend-pack/README.md)
- **Source:** [`frontend/`](frontend/) (owner app `index.html`, public shop `shop.html`, counterparty page `party.html`, English/Hindi/Gujarati strings)

Point it at an API by editing one line in [`frontend/config.js`](frontend/config.js). See [Hosting the frontend separately](#hosting-the-frontend-separately) for the sign-in caveat.

---

## Risks and limitations

Read this before using LivingDoc for a real shop. Each item says what could go wrong and what the project does about it.

**Wrong numbers**
- **The AI can misread a note.** Mitigation: it only emits JSON deltas, the JSON is shown beside every note, validated and applied by plain code, and stock can never go negative. It does not remove the risk: check the extracted JSON, especially for Hindi/Gujarati and mixed-language notes. The offline reader is English only.
- **Forecasts rest on assumptions.** Starter festival dates, surge multipliers and payday effects are guesses until real days are logged. The UI labels assumptions as assumptions and shows ranges, but a range is not a guarantee. Do not place large, irreversible orders on a forecast alone.
- **Cash-flow forecasts** use each person's past behaviour; a new customer has none. The ranges widen, they do not become correct.
- **Starter data is made up** (the sweet shop, the people, the demo storefront "Shah Provision"). Clear it before real use. `LIVINGDOC_DEMO_STOREFRONT=1` publishes sample content and a public chart on purpose; **do not set it on a real shop**.

**Privacy and trust**
- **Cloud AI sees note text.** If you configure a hosted model (Groq, OpenAI), the text of your notes goes to that provider. Use a local model (Ollama) if that is not acceptable. Customer records are not sent as such, but a note can contain a name.
- **Your data lives where you host it.** Locally it is one SQLite file on your machine. On Render or Fly it is on that host. On the free Render plan **data is wiped on every restart**; use a paid plan with a disk (see `DEPLOY.md`) for anything real. The database also holds the proof-signing key, so guard backups like a password.
- **The trust proof is not zero-knowledge and is not audited.** It is a signed, spot-checkable statement by the shop about entries it and the other person allowed. Band-level claims can still hint at the order of magnitude. A dishonest owner can choose which entries to opt in; the other person's veto and the verifier's nonce spot-check limit this, they do not eliminate it.
- **Customer comments** are visible only to the owner, but a customer may type personal data. Contact details are optional and never exported to the developer notes. There is no spam filter beyond a hidden field and a per-shop rate limit.
- **The helper cannot spend**, but that is partly because no ad platform is connected. The budget cap is a *planned* spend ledger. If you connect real ad accounts later, re-audit this guarantee.

**Access and security**
- **Accounts have no e-mail verification and no password-reset e-mail** (that needs an e-mail service). A forgotten password means an owner removes the person and sends a new invite; a forgotten owner password needs the hosting shell. Sessions last 7 days and are not individually revocable (changing a password or removing a person kills theirs).
- **Open mode is for `localhost` only.** With no accounts and no `LIVINGDOC_ADMIN_PASSWORD`, anyone who reaches the app can use it, *and the first visitor to create an account becomes the owner*. On any public host set the deployment password first.
- **Never put a real password in this README or the repo.** The demo's earlier `admin` password was weak and public; rotate it. Sign-in rate limits are in memory, so they reset on restart and are per instance.
- The Cloudflare quick-tunnel link used for the demo is temporary and its address changes on restart.

**Scale and scope**
- **One instance.** SQLite and in-memory limits mean a single server process; this suits one shop or a few branches, not a chain. Branch sync covers **stock movements only**; cash and promises stay per branch, via a shared SQLite "hub" file.
- **Not accounting.** No tax, GST, payroll or audited statements. The cash section's "owed" is customers owing the shop; money the shop owes, favours and words live in the Trust ledger.
- **Voice input** uses the browser's speech recognition. Hindi and Gujarati support varies by browser and has not been tested here.
- **Hosting the frontend on a different site** from the API cannot keep a sign-in (the session cookie is `SameSite=Lax`); use one domain with a reverse proxy. See the [Frontend Pack](#frontend-pack).
- **Times** are shown in the server's local time zone. Forecast "Why" explanations are English; headings, tables, buttons and warnings are translated.

**What has and has not been tested**
- 146 backend tests and 53 scripted browser checks pass, covering the rules above (privacy of entries, the proof round trip, public vs private routes, accounts and roles). They have **not** been run against a real shop's data, on a phone in the field, or with a real scanner. Treat it as a working prototype.

---

## More detail

## 🌐 Live Working Links & API Endpoints

The demo is exposed through a Cloudflare quick tunnel, so **its address changes every time the tunnel restarts**. If a link is dead, run it yourself (see [Setup](#setup--run-instructions)) or deploy with [`DEPLOY.md`](DEPLOY.md):
* **Base URL:** `https://wear-linda-des-powerpoint.trycloudflare.com`
* **Sign-in:** create the first (owner) account, or use the password the person who deployed it gave you. Never publish a real password in a README.

### Interactive Documentation & Specs
| Link | Description |
|---|---|
| [**Swagger UI (/docs)**](https://wear-linda-des-powerpoint.trycloudflare.com/docs) | Interactive API playground to test any route directly |
| [**ReDoc (/redoc)**](https://wear-linda-des-powerpoint.trycloudflare.com/redoc) | Human-readable comprehensive REST documentation |
| [**OpenAPI Spec (/openapi.json)**](https://wear-linda-des-powerpoint.trycloudflare.com/openapi.json) | Standard JSON OpenAPI 3.1 specification |

### Frontend Applications
| Screen | Link | Access |
|---|---|---|
| **LivingDoc App** | [wear-linda-des-powerpoint.trycloudflare.com](https://wear-linda-des-powerpoint.trycloudflare.com) | Sign-in required |
| **Public Storefront** | [wear-linda-des-powerpoint.trycloudflare.com/shop.html?s=main-store](https://wear-linda-des-powerpoint.trycloudflare.com/shop.html?s=main-store) | Public (no login) |
| **Bilateral Counterparty View** | [wear-linda-des-powerpoint.trycloudflare.com/party.html](https://wear-linda-des-powerpoint.trycloudflare.com/party.html) | Token-gated per party |

### Working API Endpoints (Direct Access)
| Resource | Method & Path | Description |
|---|---|---|
| **Health Check** | `GET` [/api/health](https://wear-linda-des-powerpoint.trycloudflare.com/api/health) | Uptime & server status |
| **Auth Status** | `GET` [/api/auth/status](https://wear-linda-des-powerpoint.trycloudflare.com/api/auth/status) | Authentication requirement & session state |
| **Living Document (JSON)** | `GET` [/api/document?branch=Main%20Store](https://wear-linda-des-powerpoint.trycloudflare.com/api/document?branch=Main%20Store) | Full live state (stock, cash, promises, risks) |
| **Markdown Export** | `GET` [/api/document.md?branch=Main%20Store](https://wear-linda-des-powerpoint.trycloudflare.com/api/document.md?branch=Main%20Store) | Clean markdown summary export |
| **Demand Forecast** | `GET` [/api/forecast?branch=Main%20Store&horizon=14](https://wear-linda-des-powerpoint.trycloudflare.com/api/forecast?branch=Main%20Store&horizon=14) | 14/28/56-day Bayesian demand with 50/80% bands |
| **Dynamic Pricing** | `GET` [/api/pricing?branch=Main%20Store](https://wear-linda-des-powerpoint.trycloudflare.com/api/pricing?branch=Main%20Store) | Raise / sale / hold product pricing actions |
| **Forecast Scorecard** | `GET` [/api/scorecard?branch=Main%20Store](https://wear-linda-des-powerpoint.trycloudflare.com/api/scorecard?branch=Main%20Store) | Brier accuracy score graded against actuals |
| **Trust Ledger** | `GET` [/api/trust/ledger?branch=Main%20Store](https://wear-linda-des-powerpoint.trycloudflare.com/api/trust/ledger?branch=Main%20Store) | Bilateral promises & FIFO debts |
| **Cashflow Projections** | `GET` [/api/cashflow/promises?branch=Main%20Store](https://wear-linda-des-powerpoint.trycloudflare.com/api/cashflow/promises?branch=Main%20Store) | Seeded cashflow with 10/50/90% percentiles |
| **Verifiable Proofs** | `GET` [/api/proofs?branch=Main%20Store](https://wear-linda-des-powerpoint.trycloudflare.com/api/proofs?branch=Main%20Store) | Band-level Merkle proofs for banks/suppliers |
| **Festival Engine** | `GET` [/api/festivals?branch=Main%20Store](https://wear-linda-des-powerpoint.trycloudflare.com/api/festivals?branch=Main%20Store) | Festival calendar & blackout lead times |
| **Sync Status** | `GET` [/api/sync/status](https://wear-linda-des-powerpoint.trycloudflare.com/api/sync/status) | Hub multi-branch synchronization state |

---


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
| **Trust ledger, proof without exposure, promise → cash flow** | Every promise (money owed, money we owe, favours, someone's word) keeps *both* sides' figures. Each person gets a private link to see, dispute and veto what is recorded about them. Open money promises are turned into a seeded cash-flow forecast, and the shop can sign a proof of a few band-level facts without showing names or amounts. See [Trust ledger](#trust-ledger-proof-without-exposure-promise--cash-flow). |
| **Be found, stay in control** | An owner-built public shop page (`shop.html?s=<slug>`) where every field is hidden until ticked, plus an AI helper that can only write drafts. It shows why each draft says what it says, cannot publish, edit or spend, and everything it and you do is logged. The page can carry a signed, checkable trust badge. See [Be found, stay in control](#be-found-stay-in-control). |
| **Forecast & Pricing** | Daily demand forecast with 50/80% ranges (weather, paydays, festivals, rival promotions, your own factors), a per-product raise / sale / hold plan with prep quantities capped by real stock, a scorecard that grades only forecasts frozen before the day, and an Owner desk where you add things the data cannot see and log real days so the AI's belief visibly updates. Integrated from the Foresight module. See [Forecast & Pricing](#forecast--pricing-foresight). |
| **Scanner** | Accepts files (`.json`, `.jsonl`, `.csv`) dropped in a folder **or** JSON posted to the API. Duplicate-safe, never lets stock go negative, flags problems instead of crashing. |
| **Multi-branch** | Stock movements upload hourly to a shared hub and are pulled by every other branch. Repeat syncs change nothing. |
| **Languages** | English, हिन्दी, ગુજરાતી for the whole interface and for generated warnings. |
| **Voice input** | A microphone button uses the browser's built-in speech recognition (where the browser supports it) in the selected language. |


## Quick start (more detail)

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
| `LIVINGDOC_ADMIN_PASSWORD` | *(empty = open)* | **Set this before hosting on the internet.** It is the setup code for creating the first (owner) account (see [Hosting](#hosting-it-on-the-internet)) |
| `LIVINGDOC_CSP` | `1` | `0` turns off the Content-Security-Policy header |
| `LIVINGDOC_CORS_ORIGINS` | `*` | Allowed origins when the frontend is hosted elsewhere |
| `LIVINGDOC_FRONTEND` | `../frontend` | Folder served at `/` |
| `LIVINGDOC_FORESIGHT_DIR` | `<db folder>/foresight_data` | Folder holding one Foresight SQLite file per branch |
| `LIVINGDOC_FORESIGHT_LIVE` | `1` | `0` forbids live weather calls (assumed climate only) |
| `LIVINGDOC_FORESIGHT_AUTOIMPORT` | `1` | Daily job imports yesterday's LivingDoc numbers as sales (`0` to skip) |
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
| `GET /api/forecast?horizon=&history=` | Demand forecast with 50/80% bands, festival spans, weather source, model state and assumption flags (also freezes today's forecast for grading) |
| `GET /api/pricing?date=&days=` | Per product and day: SURGE / SALE / HOLD, price, expected units, prep quantity, reason (code + English text) |
| `GET /api/explain?date=` | % effect of each driver on one day |
| `GET/POST /api/actuals`, `DELETE /api/actuals/{date}`, `POST /api/actuals/import`, `DELETE /api/actuals?source=` | Real daily sales (the learning signal); import from LivingDoc; clear by source (`demo`, `livingdoc`, `owner`) |
| `GET/POST /api/factors`, `DELETE /api/factors/{id}`, `GET /api/factors/suggest?text=` | Owner factors and the AI's current belief about each |
| `GET/POST /api/rival-promos`, `DELETE /api/rival-promos/{id}` | Rival promotions |
| `GET /api/scorecard` | MAPE, bias, 80% coverage, skill vs last-7-day average, profit vs flat prices, plain-language verdicts |
| `GET /api/trends`, `POST /api/trends/refresh` | Cached web-trend scores (never hits the network) / run the search now |
| `GET/PUT /api/foresight/profile`, `PUT /api/foresight/products/{name}`, `GET/PUT /api/foresight/festivals`, `POST /api/foresight/festivals/reset` | Assumptions: location, income, rivals, guardrails, product prices/costs/elasticity, festival calendar |
| `POST/DELETE /api/foresight/demo`, `GET /api/foresight/learned`, `POST /api/foresight/daily` | Demo mode (rows tagged `demo`), starting vs learned coefficients, run the daily job |
| `GET /api/trust/ledger`, `POST /api/trust/entries`, `PATCH/DELETE /api/trust/entries/{id}`, `POST /api/trust/entries/{id}/resolve` | Promise ledger with both figures, scores and consent state; add, edit, delete, mark kept/broken/forgiven |
| `POST/DELETE /api/trust/parties/link`, `GET /api/trust/party/{token}`, `POST /api/trust/party/{token}/entries/{id}` | The other person's private link: see only their own records, state their figure, dispute, grant or withhold proof consent |
| `GET /api/cashflow/promises?horizon=&opening_cash=&include_sales=` | Day-by-day cash from open promises (10/50/90%), per-promise odds, warnings, every assumption |
| `GET /api/proofs/preview`, `GET/POST /api/proofs`, `GET /api/proofs/{id}`, `POST /api/proofs/{id}/revoke` | Preview what a proof reveals, sign it, list, fetch, revoke |
| `POST /api/proofs/verify`, `POST /api/proofs/{id}/open`, `POST /api/proofs/check-openings` | Verifier tools: check signature/expiry/revocation, spot-check challenge, check the openings |
| `GET/PUT /api/presence` | Profile of the public page (every field private until ticked), autonomy, budget cap |
| `POST /api/presence/suggest`, `GET /api/presence/drafts`, `PATCH /api/presence/drafts/{id}`, `POST /api/presence/drafts/{id}/{approve|publish|unpublish|reject}`, `POST /api/presence/drafts/{id}/boost`, `GET /api/presence/log` | Helper drafts (only when asked), owner decisions, planned spend inside the cap, audit log |
| `GET /api/presence/public/{slug}` | The only unauthenticated view of a shop: published, owner-chosen fields, schema.org JSON-LD |
| `GET /api/audit` | Check that every stock count equals the sum of its movement log |

## Forecast & Pricing (Foresight)

The **Forecast & Pricing** section (tabs: Forecast, Pricing, Owner inputs, Scorecard, Setup) wraps the Foresight demand and pricing
engine, vendored in `backend/foresight/` (pure Python; its matplotlib charts are replaced by SVG drawn in the browser).

**How our data feeds it**

| LivingDoc | Foresight | Notes |
|---|---|---|
| `items` per branch | `profile["products"]` | `baseline_burn` becomes `base_units`; **current stock becomes `supply_per_day`** (capacity), so surge/sale/prep use real stock; shelf life ≤ 14 days marks a product perishable. Items with no daily use are listed as "not forecast", never silently dropped. |
| *(nothing)* | price, cost, category, elasticity, essential, temp/rain sensitivity, keywords | LivingDoc has none of these, so each product gets **placeholder** defaults (flagged on screen until you edit them in Setup). Elasticity defaults to the margin-implied value (price ÷ (price − cost)), capped to 0.4–4, unless you override it. |
| outflow `movements` + `cash_events` (collected) | `actuals` (orders, revenue) | LivingDoc has no order count, so orders are **estimated as outflow events per day** (a proxy). Imports are tagged `source=livingdoc`, never overwrite a day you logged, and can be cleared. Log the true number for any day to override. |
| branch | one Foresight store per branch | `<db folder>/foresight_data/<branch>.db` |
| `festivals` (supplier planning) | `festivals` (demand kernels) | Different shapes, so they stay **separate**. LivingDoc's calendar is shown read-only in Setup for reference. |

**What the section guarantees**
- Festival dates, pay schedules, weather normals, starting coefficients and placeholder prices are labelled as editable assumptions on every tab, with a reminder to verify festival dates for your region.
- Live weather (Open-Meteo, no key) and the daily web search (DuckDuckGo via `ddgs`) fall back to clearly labelled assumed values when offline; the page says which one it is using.
- Demo mode loads simulated sales tagged `demo`, shows a banner whenever any are present, refuses to overwrite days you logged, and clears in one click.
- Essentials are never surged; the surge cap, sale floor and rival-price ceiling are editable.
- The scorecard grades only forecasts frozen before the day; one day proves nothing, so it reports averages over many days.

**Daily job.** `python scripts/refresh_daily.py` (run from `backend/`, see the file for cron / Task Scheduler / launchd examples) refreshes web trends, imports yesterday's numbers and freezes today's forecast for every branch. The server runs the same job itself once a day while its background workers are on.

**Honest limits.** Capacity is today's stock (incoming deliveries are not modelled). Trend scoring is keyword-based and noisy: a nudge of at most 12%, not a driver. Until real days are logged the forecast runs on assumptions and its ranges are widened accordingly. Foresight's explanations are translated into Hindi/Gujarati by reason code; festival, product and driver names typed by you are shown as written.

## Trust ledger, proof without exposure, promise → cash flow

The question this answers: *when a promise is both an asset and someone's private story, who may see it, and who decides what it is worth?*
The design answer is **two views, two consents, bands not names**.

- **Two views of every promise.** Each entry stores the shop's figure and, separately, the other person's figure. They are never silently merged. If they differ by more than 10%, or either side disputes, the entry is flagged *disputed* and shows a range ("worth ₹X to ₹Y, depending on whose view"). Outsiders only ever get the conservative figure (the lower one for money owed to the shop, the higher for money the shop owes).
- **The other person has a say.** *Share their view* makes a private link (`/party.html?t=…`). That page shows exactly what is recorded about that one person, how their reliability score is worked out, and lets them state their own figure, add a note, dispute, or **say no to being counted in any proof**. Money debts and promises about other people in your notes are mirrored here automatically (as private entries); amounts of mirrored entries can only change through the cash/notes flow.
- **Private by default.** An entry is counted in a proof only if the shop opted it in **and** the other person has not withheld consent.
- **Fair scoring.** Reliability counts resolved promises only: kept on time = 1, kept late = 0.6, broken = 0; forgiven ones are ignored; a starting belief of 80% is worth two promises, so a single event never decides anything. The formula is shown to the shop and to the person scored.
- **Promise → cash flow.** Open money promises become a 2,000-run seeded simulation (same ledger, same answer). A promise arrives with probability = the person's score × a decay for how overdue it is × 0.6 if disputed, on its due date plus that person's usual delay. Money the shop owes is paid on its due date. Favours and words carry no cash. Opening cash is only what you type; Foresight's expected sales can be added and are labelled as an assumption. Warnings: possible shortfall (≥20% chance), one person making up more than half of what you expect, overdue and disputed money.
- **Proof without exposure.** The shop picks which claims to sign: *owed to us is at least a band floor*, *at least N people*, *nothing more than N days overdue*, *no single person above X%*, *at least X% of resolved promises kept* (needs ≥5 resolved, so small samples cannot identify people), *we owe at most a band*. Before signing, the page shows exactly what would be revealed and which entries are excluded and why. Each counted entry becomes a salted hash in a Merkle tree; the root and claims are signed with Ed25519 (valid 7 days by default, revocable). A verifier can paste the packet to check signature, expiry and revocation, or **challenge** the shop: the entries to open are derived from the root plus the verifier's random nonce, so the shop cannot cherry-pick flattering ones. Names are hidden in openings, and opening requires the one-time *open key* shown when the proof is signed. `python scripts/verify_proof.py packet.json` verifies signature and expiry offline.

**Honest limits.**
- This is a signed, committed, selectively-openable attestation. It is **not zero-knowledge**: the verifier trusts the shop's signature for the totals, and the spot-check only samples a few entries.
- Claims say nothing about entries kept private or withheld by the other person.
- The person's identity on their link is whoever holds the link; there is no per-person login. Anyone with the link can answer for that person, so send it only to them and turn it off from the ledger if it leaks.
- The open key is a bearer secret: whoever has it (plus a proof id) can run challenges for that proof.
- The signing key lives in the database next to the data; protect the database file.
- Forecast odds are a model of past behaviour with a stated prior, not a promise of payment.

## Be found, stay in control

**The riddle, answered.** Good small shops stay unknown, and owners avoid the tools that could help because those tools are opaque: they write, design and spend, and the owner cannot see why or stop them. What is missing is not more power but *legibility and a veto*. So the helper here is built around four rules, each enforced in code and tested:

1. **Private by default.** The public page does not exist until you switch it on, and each field (name, product names, trust badge) is hidden until you tick it. Stock levels, customers, debts, cash and ledger entries are never shown.
2. **Drafts only.** The helper writes drafts when you press the button (never in the background) from your own data: your tagline, the festival calendar, a signed proof. It cannot publish, change your page or spend. Each draft shows its source, what it used, and what it invented (it states no prices or discounts). Draft in English, Hindi or Gujarati, edit freely, then approve and publish in two separate taps.
3. **Spending has a cap you set.** Boosts above the remaining cap are refused. No ad account is connected, so a boost is recorded as *planned* spend and the page says nothing was bought.
4. **A glass activity log.** Every action is recorded with who did it (helper or you). Turn the helper off and suggestions stop. Revoke a proof and its badge disappears from the public page immediately.

**Being found.** The public page carries schema.org `LocalBusiness` JSON-LD so search engines and assistants can read it, and a trust section: the band-level claims of a signed proof that any visitor can check with one tap (no names, no amounts). Trust here means *checkable*, not *audited*.

**Honest limits.** The page is served by this app: to be reachable on the internet it must be hosted behind HTTPS (set `LIVINGDOC_ADMIN_PASSWORD` so the owner screens stay private while the public page stays open). Drafts are filled-in templates, not a language model, so they are plain on purpose. No ad platform or social network is connected.

## Hosting it on the internet

One container serves the website and the API. See **[DEPLOY.md](DEPLOY.md)** for step-by-step Render, Fly.io and own-server instructions.

```bash
cp .env.example .env            # set LIVINGDOC_ADMIN_PASSWORD
docker compose up -d --build    # http://localhost:8000
```

- **Sign-in.** With `LIVINGDOC_ADMIN_PASSWORD` set, the owner screens and API need a password. Still public on purpose: the shop's public page, proof checking, `/api/health`, and each person's private link (its secret token is the credential). Scanners and scripts can send `Authorization: Bearer <password>`.
- **Security headers.** `nosniff`, `no-referrer` (private links carry a token), frame blocking, a Content-Security-Policy, and HSTS over HTTPS.
- **Data.** SQLite files live in `/data`; mount a persistent volume there or you lose them on redeploy.
- **HANDOFF.md** is the brief for a coding agent (for example Antigravity) to review, commit, push and deploy.

## The interface

Sidebar on desktop and a bottom tab bar on phones, one screen per area (Today, Stock, Money, Forecast, Trust, Be found; the URL hash, e.g. `#/trust`, selects it). **Today** opens with how many things need the owner, four live numbers and a one-tap note box. Palette: indigo ink with a turmeric highlight, light and dark. Fonts: Bricolage Grotesque with Noto Sans (Devanagari and Gujarati included), loaded from Google Fonts and falling back to system fonts offline. Keyboard focus is visible and reduced-motion is respected.

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
cd backend && pip install -r requirements-dev.txt && python -m pytest -q tests     # 146 tests
pip install playwright && playwright install chromium && python ../e2e/browser_smoke.py   # real browser, 42 checks
```

The backend tests cover the engine, extraction and validation (including a fake LLM and garbage LLM output), stock math,
FIFO debt settlement, scanner edge cases, branch sync convergence, every API route including the Forecast & Pricing routes, the trust ledger (two-sided consent, scoring, cash-flow determinism, proof signing/tamper/expiry/revocation, no-leak and challenge checks) and Foresight's own 24 model/pricing/learning tests (including 40 parallel scanner requests
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
    forecast_api.py  Forecast & Pricing routes
    auth.py          Optional owner login (signed session cookie)
    security.py      Security headers
    trust_api.py     Trust ledger, promise cash flow and proof routes
    presence_api.py  Public shop page, drafting helper, audit log
    workers.py       background loop (scanner inbox, hourly sync, daily forecast job)
    services/        extraction · inventory · ledger · scanner · sync · document · catalog · forecasting · trust · cashflow · proofs · presence · seed
  foresight/         vendored demand & pricing engine (model, pricing, owner learning, scorecard, trends, weather)
  tests/             pytest suite
frontend/
  index.html  party.html  shop.html  config.js  css/
  js/                main.js · api.js · store.js · i18n.js · format.js · dom.js · toast.js
  js/components/     shell (sidebar + Today hero) · login · header · notes · scanner · inventory · cash · promises · forecast · foresight · trust · presence · risks · settings
  js/charts.js       SVG charts for the forecast and scorecard
Dockerfile  docker-compose.yml  render.yaml  fly.toml  .env.example  DEPLOY.md  HANDOFF.md
scripts/             refresh_daily.py (once-a-day job) · verify_proof.py (offline proof check)
e2e/                 browser smoke test (Playwright)
examples/            sample scanner files and notes
```

## Hosting the frontend separately

By default the backend serves the frontend at `/`, so one command runs everything. To host the frontend elsewhere (any
static host), grab the [Frontend Pack](#frontend-pack) and set `window.LIVINGDOC_API` in [`frontend/config.js`](frontend/config.js) to the API's address and start the backend with
`LIVINGDOC_CORS_ORIGINS=https://your-frontend-origin`.

**Sign-in caveat:** the session cookie is `SameSite=Lax`, so a frontend on a different *site* than the API cannot stay signed in. Put both behind one domain with a reverse proxy, or use the pack only for the public shop and party pages.

## Problems Faced & Engineering Challenges

Building an autonomous operations brain for micro-businesses revealed real-world edge cases where standard enterprise patterns fail. Here are the 7 major engineering problems faced and how LivingDoc solves them:

### 1. Running Massive AI Locally on Edge Hardware
* **The Problem:** Small businesses run on modest store laptops, tablets, or old POS counters—not GPU workstations. Attempting to run 8B+ local models (like Llama 3.1 8B) saturated CPU/GPU cores, caused thermal throttling, drained laptop batteries, and triggered out-of-memory crashes.
* **Our Solution:** LivingDoc decouples reasoning from compute:
  1. It provides an **OpenAI-compatible cloud bridge (e.g. Groq)** that delivers 20B/70B parameter reasoning in under **200 milliseconds** with **0% local CPU load**.
  2. For completely offline environments, it falls back to a **sub-1B micro-model (`llama3.2:1b` / `qwen2.5:0.5b`)** taking less than 1.5 GB of RAM.
  3. If no LLM is running at all, a deterministic regex/rule engine instantly takes over—the shopkeeper's interface never crashes.

### 2. Global Cloud Hosting vs. Local Data Sovereignty
* **The Problem:** Shopkeepers are intensely protective of their books. Forcing them to upload customer names, informal debts, and supplier pricing to a centralized multi-tenant cloud database introduces compliance liabilities, recurring subscription costs, and deep user distrust.
* **Our Solution:** A **Local-First Data Architecture**. The primary ledger and SQLite databases live 100% on the shop's physical machine. When cloud AI is used, only anonymized text fragments are evaluated transiently in memory; zero customer records or financial books are stored on third-party servers.

### 3. Context-Window Drift & Token Explosion (The "Full Document Rewrite" Trap)
* **The Problem:** Early naive prototypes passed the entire operational state back into the LLM on every voice note: `LLM(Entire Document + New Note) → Rewritten Document`. As the business accumulated hundreds of inventory items and debts, the context window exploded, latency skyrocketed, and the LLM began hallucinating math errors (e.g. subtracting 5 from 12 and getting 8).
* **Our Solution:** **Event-Sourced Delta Extraction**. The AI acts strictly as an event parser, extracting tiny JSON deltas (`{"item": "Milk", "change": -4}`). Plain, deterministic Python/SQLite code performs the mathematical additions and subtractions. Context tokens stay minimal (<100 tokens), latency remains sub-second, and arithmetic is mathematically guaranteed.

### 4. Hardware & Environment Fragmentation (The "Zero-Sysadmin" Reality)
* **The Problem:** The business owner is simultaneously the cashier, cleaner, and accountant; they cannot maintain Docker containers, resolve Python build dependencies, or configure Node.js build pipelines.
* **Our Solution:** The frontend is written in **vanilla modular ES JavaScript and pure CSS**—there is no npm build, no Webpack, and no bundle step. The backend is a lightweight FastAPI engine running on SQLite in WAL mode. It boots in a single command across macOS, Linux, and Windows.

### 5. Code-Mixed Multilingual Noise (Hinglish & Regional Dialects)
* **The Problem:** Micro-SMB owners rarely speak formatted English. A single voice ramble frequently mixes languages and informal colloquialisms (*"2 packet ghee becha, Ramesh ne 300 rupiya diya, baki kal dega"*). Off-the-shelf named-entity recognition (NER) models fail completely on code-mixed grammar.
* **Our Solution:** Targeted prompt engineering with localized schema constraints and phonetic keyword resolution against the store's known product catalog (`KNOWN_ITEMS`), allowing seamless recognition across English, Hindi, and Gujarati.

### 6. Radical Uncertainty & Unwritten External Signals
* **The Problem:** A shopkeeper's sales are moved by external variables that exist in no ERP: sudden monsoon rain, local festival dates, neighborhood salary paydays, and rival shop discounts.
* **Our Solution:** The **Foresight Multi-Factor Engine**:
  * Ingests free, zero-key **Open-Meteo Weather APIs** for 16-day rainfall and temperature forecasts.
  * Algorithmic **Payday Spending Waves** calibrating purchasing power on the 1st and 7th of the month.
  * **Bayesian Owner Intuition:** The owner types unwritten hunches (*"Metro construction outside"*, *"Wedding nearby"*), and the system treats it as an offset with Bayesian shrinkage that updates as real days are logged.

### 7. The Evaluation Paradox ("Did We Decide Well?")
* **The Problem:** In volatile markets, a good decision can produce a bad outcome (a sudden storm empties the street), while a reckless decision can look like genius through dumb luck. Traditional business software only records the final revenue, never evaluating the quality of the decision under uncertainty.
* **Our Solution:** A **Frozen-Forecast Scorecard**. The system freezes its demand and price predictions *before* midnight of the target day. It evaluates past bets using three honest tests: Calibration (did 80% of days fall within the 80% confidence band?), Skill (did the model outperform a naive 7-day rolling baseline?), and Counterfactual Value (did dynamic surge/hold prices generate higher profit than flat pricing?).


## License

MIT, see [`LICENSE`](LICENSE).

