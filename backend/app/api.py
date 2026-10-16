"""REST API. Thin layer: validate input, call a service, return JSON. No business logic lives here."""
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import PlainTextResponse

from . import schemas
from .config import settings
from .database import db
from .services import catalog, scanner, sync
from .services.document import build_document, render_doc
from .services.extraction import llm_status, process_note
from .services.inventory import audit_stock

router = APIRouter(prefix="/api")
LANGS = {"en": "English", "hi": "हिन्दी", "gu": "ગુજરાતી"}


def _need_branch(branch: str):
    if not catalog.branch_exists(branch):
        raise HTTPException(404, f"Unknown branch {branch!r}")


def _lang(lang: str) -> str:
    return lang if lang in LANGS else "en"


@router.get("/health", tags=["system"])
def health():
    with db() as c:
        c.execute("SELECT 1")
    return {"status": "ok"}


@router.get("/config", tags=["system"])
def get_config():
    return {"default_branch": settings.default_branch, "currency": settings.currency, "languages": LANGS,
            "sync_interval_seconds": settings.sync_interval_seconds, "scanner_poll_seconds": settings.scanner_poll_seconds,
            "llm": llm_status()}


@router.get("/branches", tags=["system"])
def branches():
    return {"branches": catalog.list_branches()}


@router.get("/document", tags=["document"], summary="Structured living document for one branch")
def document(branch: str, lang: str = "en"):
    _need_branch(branch)
    return build_document(branch, _lang(lang))


@router.get("/document.md", tags=["document"], response_class=PlainTextResponse, summary="Markdown export")
def document_md(branch: str, lang: str = "en"):
    _need_branch(branch)
    return PlainTextResponse(render_doc(branch, _lang(lang)), media_type="text/markdown; charset=utf-8")


@router.post("/notes", tags=["notes"], summary="Submit a messy note; LLM extracts JSON deltas, code applies them")
def post_note(body: schemas.NoteIn):
    _need_branch(body.branch)
    res = process_note(body.text, body.branch)
    if not res.get("ok"):
        if res.get("error") == "duplicate":
            raise HTTPException(409, "This exact note was just processed; not applied twice.")
        raise HTTPException(400, "Empty note")
    return res


@router.get("/notes", tags=["notes"])
def list_notes(branch: str, limit: int = Query(20, ge=1, le=100)):
    _need_branch(branch)
    return {"notes": catalog.recent_notes(branch, limit)}


@router.get("/movements", tags=["inventory"], summary="Recent stock movements (notes, scanner, counts)")
def movements(branch: str, limit: int = Query(30, ge=1, le=200)):
    _need_branch(branch)
    return {"movements": catalog.recent_movements(branch, limit)}


@router.get("/items", tags=["inventory"])
def items(branch: str):
    _need_branch(branch)
    return {"items": catalog.list_items(branch)}


@router.put("/items", tags=["inventory"], summary="Create or update an item; optional physical count")
def put_item(body: schemas.ItemIn):
    _need_branch(body.branch)
    return catalog.upsert_item(body.branch, body.name, body.unit, body.min_stock, body.daily_use,
                               body.shelf_life_days, body.sku, body.counted)


@router.post("/scanner/events", tags=["scanner"], summary="Push scanner events directly (JSON)")
def scanner_events(body: schemas.ScanBatch):
    branch = body.branch or settings.default_branch
    return scanner.ingest_events(body.events, branch, "api")


@router.post("/scanner/poll", tags=["scanner"], summary="Process the scanner_inbox folder now")
def scanner_poll(branch: Optional[str] = None):
    return scanner.process_scanner_inbox(branch or settings.default_branch, min_age=0)


@router.post("/sync", tags=["sync"], summary="Sync stock movements with the other branches now")
def run_sync():
    try:
        return sync.sync_with_hub()
    except Exception as e:  # hub unreachable: report, never crash
        raise HTTPException(502, f"Sync failed: {type(e).__name__}: {e}")


@router.get("/sync/status", tags=["sync"])
def sync_status():
    with db() as c:
        waiting = c.execute("SELECT COUNT(*) n FROM movements WHERE synced=0").fetchone()["n"]
        last = c.execute("SELECT value FROM meta WHERE key='last_sync'").fetchone()
    return {"last_sync": last["value"] if last else None, "pending_movements": waiting,
            "interval_seconds": settings.sync_interval_seconds}


@router.get("/festivals", tags=["forecast"])
def festivals():
    return {"festivals": catalog.list_festivals(), "lead_days": catalog.get_lead_days()}


@router.post("/festivals", tags=["forecast"], status_code=201)
def add_festival(body: schemas.FestivalIn):
    catalog.save_festival(body.name, body.date, body.surge_multiplier, body.supplier_blackout_days)
    return {"festivals": catalog.list_festivals()}


@router.delete("/festivals", tags=["forecast"])
def remove_festival(name: str, date: str):
    if not catalog.delete_festival(name, date):
        raise HTTPException(404, "Festival not found")
    return {"festivals": catalog.list_festivals()}


@router.put("/settings/lead-days", tags=["forecast"])
def lead_days(body: schemas.LeadDaysIn):
    catalog.set_lead_days(body.days)
    return {"lead_days": body.days}


@router.patch("/promises/{pid}", tags=["document"])
def patch_promise(pid: int, body: schemas.PromisePatch):
    if not catalog.set_promise_done(pid, body.done):
        raise HTTPException(404, "Promise not found")
    return {"id": pid, "done": body.done}


@router.post("/risks/{rid}/resolve", tags=["document"])
def resolve_risk(rid: int):
    if not catalog.resolve_risk(rid):
        raise HTTPException(404, "Risk not found")
    return {"id": rid, "resolved": True}


@router.get("/audit", tags=["system"], summary="Check the stock counts against the movement log")
def audit():
    with db() as c:
        bad = audit_stock(c)
    return {"ok": not bad, "mismatches": [{"branch": b, "item": i, "stored": q, "logged": s} for b, i, q, s in bad]}
