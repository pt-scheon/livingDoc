"""Scanner ingestion: folder inbox (.json/.jsonl/.csv) and direct API events. Idempotent by event_id."""
import csv
import io
import json
import shutil
import time
from datetime import datetime
from pathlib import Path

from ..config import settings, parse_ts
from ..database import add_risk, db, ensure_branch
from ..textutil import fmt_qty
from .extraction import _to_float
from .inventory import apply_movement, resolve_item


# ------------------------------------------------------------ scanner inbox ---
DIRECTIONS = {"in": 1, "inward": 1, "receive": 1, "received": 1, "restock": 1, "purchase": 1, "+": 1, "1": 1,
              "out": -1, "outward": -1, "sale": -1, "sold": -1, "issue": -1, "dispatch": -1, "-": -1, "-1": -1}


def _read_scan_file(f: Path):
    suffix = f.suffix.lower()
    text = f.read_text(encoding="utf-8-sig")
    if suffix == ".csv":
        return list(csv.DictReader(io.StringIO(text)))
    if suffix == ".jsonl":
        return [json.loads(ln) for ln in text.splitlines() if ln.strip()]
    obj = json.loads(text)
    if isinstance(obj, dict) and isinstance(obj.get("events"), list):
        obj = obj["events"]
    return obj if isinstance(obj, list) else [obj]


def _apply_scan_event(c, ev, default_branch, fname):
    if not isinstance(ev, dict):
        return "skipped", "event is not an object"
    branch = str(ev.get("branch") or default_branch).strip() or default_branch
    ensure_branch(c, branch)
    sku = str(ev.get("sku") or ev.get("barcode") or "").strip()
    name = str(ev.get("item") or ev.get("name") or "").strip()
    if not sku and not name:
        return "skipped", "no sku or item name"
    qty = _to_float(ev.get("qty", 1) if ev.get("qty") not in (None, "") else 1)
    if qty is None or qty <= 0:
        return "skipped", "invalid quantity"
    sign = DIRECTIONS.get(str(ev.get("direction", "")).strip().lower())
    if sign is None:
        return "skipped", "direction must be in/out"
    eid = str(ev.get("event_id") or ev.get("id") or "").strip()
    mov_id = f"scan-{branch}-{eid}" if eid else None
    item, created = resolve_item(c, branch, name, sku or None)
    if sku:  # learn barcode -> item mapping the first time a known item is scanned
        cur = c.execute("SELECT sku FROM items WHERE branch=? AND name=?", (branch, item)).fetchone()
        taken = c.execute("SELECT 1 FROM items WHERE branch=? AND lower(sku)=lower(?)", (branch, sku)).fetchone()
        if cur and not cur["sku"] and not taken:
            c.execute("UPDATE items SET sku=? WHERE branch=? AND name=?", (sku, branch, item))
    ts = None
    if ev.get("ts"):
        try:
            ts = parse_ts(str(ev["ts"]).replace("T", " ")).strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            ts = None
    r = apply_movement(c, branch, item, sign * qty, "scanner", fname, ts=ts, mov_id=mov_id)
    if r["duplicate"]:
        return "duplicate", ""
    if r["short"] > 0:
        add_risk(c, branch, f"Scanner: {fmt_qty(qty)} x {item} went out but only {fmt_qty(qty - r['short'])} were on record - "
                            f"an earlier delivery scan is probably missing.", "scanner")
    return "applied", ""


def ingest_events(events, default_branch, origin="api"):
    """Apply a batch of scanner events in ONE transaction. Returns counts; problems become warnings, not crashes."""
    stats = {"applied": 0, "duplicate": 0, "skipped": 0}
    with db() as c:
        for ev in events:
            res, why = _apply_scan_event(c, ev, default_branch, origin)
            stats[res] += 1
            if res == "skipped":
                add_risk(c, default_branch, f"Scanner event skipped ({why}): {json.dumps(ev, ensure_ascii=False, default=str)[:140]}", "scanner")
    return stats


def process_scanner_inbox(default_branch, min_age=1.0):
    """Ingest files dropped by the (already working) scanner: .json / .jsonl / .csv. Idempotent via event_id."""
    inbox = Path(settings.scanner_inbox)
    done, bad = inbox / "processed", inbox / "failed"
    for d in (inbox, done, bad):
        d.mkdir(parents=True, exist_ok=True)
    stats = {"files": 0, "applied": 0, "duplicate": 0, "skipped": 0, "failed_files": 0}
    for f in sorted(inbox.iterdir()):
        if (not f.is_file() or f.name.startswith(".") or f.suffix.lower() not in (".json", ".jsonl", ".csv")
                or time.time() - f.stat().st_mtime < min_age):
            continue
        stamp = datetime.now().strftime("%Y%m%d%H%M%S%f")
        try:
            res = ingest_events(_read_scan_file(f), default_branch, f.name)
            for k in ("applied", "duplicate", "skipped"):
                stats[k] += res[k]
        except Exception as e:
            stats["failed_files"] += 1
            shutil.move(str(f), str(bad / f"{stamp}_{f.name}"))
            (bad / f"{stamp}_{f.name}.error.txt").write_text(f"{type(e).__name__}: {e}", encoding="utf-8")
            with db() as c:
                add_risk(c, default_branch, f"Scanner file {f.name} could not be read ({type(e).__name__}); moved to failed/.", "scanner")
            continue
        stats["files"] += 1
        shutil.move(str(f), str(done / f"{stamp}_{f.name}"))
    return stats
