# LivingDoc: The Self-Updating Business Brain

A small business runs on memory, favours and one person's long days. Most of it is never written down, so the
first thing that breaks is quiet: a stock count nobody updated, a promise nobody wrote down, a debt that has been
open for two weeks, a supplier that closes for a festival.

LivingDoc turns messy notes and scanner events into a live, Google-Docs-style business page, and warns you about
shortages (including festival surges) before they happen.

```
 voice notes / rambles ──► LLM (JSON deltas ONLY) ──► validator ──┐
                                                                  ├─► deterministic Python ─► SQLite ─► Markdown page
 QR / barcode scanner ──► scanner_inbox/*.json|csv ───────────────┘        (stock math, cash settlement)    (re-rendered
 other branches ◄──► hourly sync via shared hub DB                                                           from state)
```

The AI never rewrites the document. It only extracts events; plain code applies them and the page is rebuilt from
the database every time.

## Features

- **Two-column UI**: left is a free-text box for rambling notes, right is a live page with
  📦 Current Inventory (⚠️ low-stock alerts), 💰 Cash & Invoices, 🤝 Handshakes & Promises (`[ ]` / `[x]`),
  🔮 Early Shortage Predictions and 🚨 Quiet Breakage Warnings.
- **Event-driven and scalable**: the LLM only returns
  `{inventory_deltas, cash_events, promises, quiet_risk}`. Output is validated and sanitised before use.
  Stock changes are O(1) updates backed by an audit log (`movements` table); a built-in audit checks the log against counts.
- **Works without an LLM**: if the model is unreachable, a deterministic English rule parser takes over.
- **Scanner feed**: drop `.json`, `.jsonl` or `.csv` files into `scanner_inbox/`; they are polled every 10 seconds.
- **Festival-aware prediction engine** (`festive_engine.py`, also embedded in the app).
- **Multi-branch**: stock movements upload hourly to a shared hub and are pulled by every other store.
- **Languages**: English, हिन्दी, ગુજરાતી (interface and warnings).
- **Problem solving built in** (see below).

## Quick start

```bash
git clone <your-repo-url> livingdoc && cd livingdoc
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
streamlit run livingdoc_app.py
```

The first run creates `livingdoc.db` with starter data (a sweet shop and café with two branches, stock history,
customers who owe money, open promises and a festival calendar).

### Connecting an LLM (optional but recommended)

Any OpenAI-compatible endpoint works. Defaults point to a local [Ollama](https://ollama.com):

```bash
ollama pull llama3.1
# defaults: LLM_BASE_URL=http://localhost:11434/v1  LLM_MODEL=llama3.1  LLM_API_KEY=ollama
streamlit run livingdoc_app.py
```

For OpenAI instead:

```bash
export LLM_BASE_URL=https://api.openai.com/v1 LLM_API_KEY=sk-... LLM_MODEL=gpt-4o-mini
```

The notes panel shows which extractor handled each note (`llm` or `rules`) and the exact JSON deltas it produced.
Hindi, Gujarati and Hinglish notes need the LLM; the offline fallback parser understands English only.

### Configuration

| Variable | Default | Meaning |
|---|---|---|
| `LIVINGDOC_DB` | `livingdoc.db` | Local database |
| `LIVINGDOC_HUB` | `livingdoc_hub.db` | Shared hub used for branch sync (put it on a shared drive/path) |
| `LIVINGDOC_SCANNER_INBOX` | `scanner_inbox` | Folder the scanner writes to |
| `LIVINGDOC_SYNC_SECONDS` | `3600` | Branch sync interval |
| `LIVINGDOC_LEAD_DAYS` | `3` | Default supplier lead time (editable in the sidebar) |
| `LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL`, `LLM_TIMEOUT` | see above | LLM connection |

## Scanner integration

The scanner hardware is assumed to already work. It only has to write a file into `scanner_inbox/`
(write to a temporary name, then rename to `.json`, `.jsonl` or `.csv`). Examples are in `examples/`.

```json
[{"event_id": "scan-0001", "sku": "ITM-GHEE", "qty": 3, "direction": "out", "branch": "Main Store"}]
```

| Field | Notes |
|---|---|
| `sku` or `item` | Barcode and/or item name (at least one) |
| `qty` | Positive number, default 1 |
| `direction` | `in` or `out` |
| `branch` | Optional, defaults to the selected branch |
| `event_id` | Optional but recommended: makes re-delivery idempotent |

How problems are handled instead of crashing:

| Problem | What happens |
|---|---|
| Same event delivered twice | Ignored (by `event_id`) |
| Stock would go below zero | Clamped to 0 and flagged: a delivery was probably never scanned |
| Unknown barcode, known item name | Barcode is learned for next time |
| Unknown barcode and no name | Placeholder item created and flagged for review |
| Bad quantity or direction | Event skipped and recorded as a warning |
| Unreadable file | Moved to `scanner_inbox/failed/` with an `.error.txt`, and a warning is shown |
| LLM down or returns junk | Output is validated; rule parser takes over |
| Same note submitted twice within a minute | Not applied twice |

## Festival prediction engine

`festive_engine.py` is standalone (run it for the self-test). The rules:

1. **Surge**: burn rate × `surge_multiplier` for the 7 days before the festival and on the festival day.
2. **Blackout buffer**: adjusted lead time = standard lead time + `supplier_blackout_days`.
3. **Reorder deadline**: stock must arrive at least 48 hours before the surge begins and before the shelf runs out,
   whichever is earlier. The earlier date wins.
4. **Perishable guard**: if a batch would outlive its shelf life after the festival, the order is capped and staged
   deliveries are suggested.

```python
from festive_engine import predict_inventory
predict_inventory(
    {"Gift Boxes": 30}, {"Gift Boxes": 2.0},
    [{"name": "Diwali", "date": "2026-11-01", "surge_multiplier": 2.8, "supplier_blackout_days": 4}],
    lead_time_days=3, today="2026-10-16")
```

For Gift Boxes on 16 Oct 2026 this gives a festive burn of 5.6/day, 5.3 days of stock instead of 15, an adjusted lead
time of 7 days (3 + 4) and a deadline of **today** (normally 28 Oct). The suggested quantity and a plain-language
alert are included in the JSON.

Note: the example JSON in the original brief showed `must_order_by: 2026-10-21`; following the stated rules
(arrive 48h before the surge, lead time 7 days) the correct deadline for those inputs is 2026-10-16.

## Tests

```bash
pip install -r requirements-dev.txt
python festive_engine.py        # prints normal vs festive reorder dates, runs assertions
python -m pytest -q tests
```

## Project layout

```
livingdoc_app.py     Streamlit app (single file; contains the engine)
festive_engine.py    Standalone engine + self-test (kept identical to the embedded copy by a test)
tests/               Engine, extraction, scanner, sync and UI-independent logic tests
examples/            Sample scanner files and sample notes
.github/workflows/   CI (Python 3.10 to 3.12)
```

If you edit the engine, change `festive_engine.py` and copy the block between `# ==== ENGINE START ====` and
`# ==== ENGINE END ====` into `livingdoc_app.py`; the test suite fails if they drift apart.

## Limitations

- Voice input is text: use your phone's or browser's dictation to fill the notes box. There is no speech-to-text built in.
- Branch sync covers stock movements. Cash entries and promises stay per-branch.
- Multi-branch sync assumes a hub file on a shared path. A production setup would put the hub behind a small server.
- "Owed" means a customer owes the business. Supplier payables are not modelled.
- Festival dates in the starter data (Diwali 8 Nov 2026, Christmas, Uttarayan) are editable in the sidebar; verify them
  for your region. Demand multipliers are starting guesses, not measurements.
- Forecast alert sentences are English; table columns and warnings are translated.
- Burn rate is learned from the last 30 days of recorded usage; early predictions improve as more data is logged.

## License

MIT, see `LICENSE`.
