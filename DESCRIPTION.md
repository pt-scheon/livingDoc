# Project description

## GitHub "About" text (paste into the repo description box)

Self-updating business brain for small shops: speak or type messy notes, feed scanner events, and get a live page of stock, cash and promises, with early festival-aware shortage warnings. FastAPI + SQLite backend, JavaScript frontend, English / Hindi / Gujarati.

**Suggested topics:** `fastapi` `sqlite` `javascript` `inventory-management` `small-business` `llm` `ollama` `hindi` `gujarati` `hackathon`

## The pitch (hackathon write-up)

**The problem.** From the outside a small business looks simple: someone sells something to someone. Inside, it runs on
memory, favours, instinct and one person's long days, and that person is usually the buyer, the cashier, the accountant
and the cleaner at once. Almost none of it is written down, because nobody has the time. What quietly breaks first is
the stuff nobody tracks: a stock count that drifted, a promise that was never recorded, a debt that has been open for two
weeks, a supplier who closes for the festival right when demand peaks.

**The solution.** LivingDoc is an integrated platform in two parts. A barcode/QR scanner (assumed to exist) reports every
item that comes in or goes out. The software side is a web app that holds the complicated bookkeeping behind a simple page
the owner can actually use, in English, Hindi or Gujarati. The owner just talks or types the way they think ("sold 4
coffees, used 2 milks, Dave paid 500 cash, remind me to order beans") and the page updates itself.

**How it works.**
- **Notes in, events out.** An LLM (local Ollama or any OpenAI-compatible service) reads the note and returns *only* structured JSON deltas. It never rewrites the document.
- **Plain code does the maths.** The JSON is validated, then deterministic Python and SQLite apply the additions and subtractions. The page is rebuilt from the database every time, so the numbers are always auditable.
- **Scanner events** arrive as files in a folder or as JSON over HTTP, and are applied the same deterministic way. Duplicates are ignored, stock can never go negative, and problems become warnings instead of crashes.
- **Early warnings.** A festive prediction engine multiplies demand in the week before a festival, adds the supplier's blackout days to the lead time, and back-calculates the last safe order date so stock arrives 48 hours before the surge. It also stops owners over-ordering perishables.
- **Quiet breakage detection.** The page watches for overdue debts, one customer holding most of the unpaid money, stale promises, a silent scanner, a lagging branch sync and an item that will run out before a delivery can arrive.
- **Forecast & pricing.** A Bayesian demand model (weather, paydays, festivals, rival promotions, owner-added factors) starts from labelled assumptions and is pulled toward reality as real days are logged. It recommends raise / sale / hold prices and prep quantities capped by real stock, and a scorecard grades only forecasts made before the day.
- **Trust ledger and promise cash flow.** Money owed, money we owe, favours and someone's word are kept as promises with *both* sides' figures. The other person gets a private link to see, dispute and veto what is recorded about them. Open promises feed a seeded cash-flow forecast with a 10/50/90% range.
- **Proof without exposure.** The shop can sign band-level claims ("owed at least ₹5,000 by at least 2 people, nothing over 7 days late") built only from entries both sides allowed, with no names or amounts, plus a verifier challenge that picks the entries to open. Honestly labelled selective disclosure, not zero-knowledge.
- **Be found, stay in control.** An owner-built public shop page (private until ticked, schema.org-ready, with a checkable trust badge) and an AI helper that only drafts: it shows where every word came from, cannot publish or spend, is capped by a budget the owner sets, and is fully logged.
- **Multiple branches** sync their stock movements hourly through a shared hub.

**Tech.** FastAPI, pydantic, SQLite (WAL), pandas/numpy (forecasting), a dependency-free modular JavaScript frontend with an OpenAPI-documented REST
API between them. 118 backend tests plus a real-browser smoke test.

**What is real and what is assumed.** The scanner hardware is assumed. The LLM is optional: without it, an English-only
rule-based reader keeps the app working. There is no login yet, so it is meant for a trusted shop network.
