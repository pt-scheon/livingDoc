"""REST routes: trust ledger, counterparty links, promise->cashflow predictor, proofs without exposure."""
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from .config import settings
from .services import cashflow, catalog, proofs, trust

router = APIRouter(prefix="/api")


def _branch(branch: Optional[str]) -> str:
    b = branch or settings.default_branch
    if not catalog.branch_exists(b):
        raise HTTPException(404, f"Unknown branch {b!r}")
    return b


def _run(fn, *a, **k):
    try:
        return fn(*a, **k)
    except trust.TrustError as e:
        raise HTTPException(400, str(e))
    except PermissionError as e:
        raise HTTPException(403, str(e))
    except KeyError as e:
        raise HTTPException(404, f"Not found: {e.args[0]}")


class EntryIn(BaseModel):
    kind: str
    counterparty: str = Field(min_length=1, max_length=80)
    description: str = Field(default="", max_length=300)
    amount: Optional[float] = Field(default=None, ge=0, le=1e9)
    due_on: Optional[str] = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    role: str = "other"
    proof_owner: bool = False


class EntryPatch(BaseModel):
    description: Optional[str] = Field(default=None, max_length=300)
    amount: Optional[float] = Field(default=None, ge=0, le=1e9)
    due_on: Optional[str] = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    role: Optional[str] = None
    proof_owner: Optional[bool] = None


class ResolveIn(BaseModel):
    status: str


class LinkIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)


class RespondIn(BaseModel):
    cp_amount: Optional[float] = Field(default=None, ge=0, le=1e9)
    cp_note: Optional[str] = Field(default=None, max_length=300)
    disputed: Optional[bool] = None
    proof_consent: Optional[bool] = None


class IssueIn(BaseModel):
    claims: Optional[List[str]] = None
    valid_days: int = Field(default=proofs.DEFAULT_VALID_DAYS, ge=1, le=proofs.MAX_VALID_DAYS)


class OpenIn(BaseModel):
    open_key: str
    nonce: str = Field(min_length=8, max_length=200)


class CheckIn(BaseModel):
    packet: Dict[str, Any]
    nonce: str
    openings: List[Dict[str, Any]]


# ------------------------------------------------------------------ ledger
@router.get("/trust/ledger", tags=["trust"])
def get_ledger(branch: Optional[str] = None):
    """Every promise (money, favours, words) with both sides' figures, consent state and each person's reliability score."""
    return _run(trust.ledger, _branch(branch))


@router.post("/trust/entries", tags=["trust"], status_code=201)
def post_entry(body: EntryIn, branch: Optional[str] = None):
    return _run(trust.create_entry, _branch(branch), body.kind, body.counterparty, body.description, body.amount, body.due_on, body.role, body.proof_owner)


@router.patch("/trust/entries/{eid}", tags=["trust"])
def patch_entry(eid: int, body: EntryPatch, branch: Optional[str] = None):
    return _run(trust.update_entry, _branch(branch), eid, body.model_dump(exclude_none=True))


@router.post("/trust/entries/{eid}/resolve", tags=["trust"])
def resolve_entry(eid: int, body: ResolveIn, branch: Optional[str] = None):
    return _run(trust.resolve_entry, _branch(branch), eid, body.status)


@router.delete("/trust/entries/{eid}", tags=["trust"])
def delete_entry(eid: int, branch: Optional[str] = None):
    _run(trust.delete_entry, _branch(branch), eid)
    return {"deleted": eid}


# ------------------------------------------------------------------ the other person's view
@router.post("/trust/parties/link", tags=["trust"])
def make_link(body: LinkIn, branch: Optional[str] = None):
    """Create (or fetch) the private link that lets one person see and answer what is recorded about them."""
    r = _run(trust.party_link, _branch(branch), body.name)
    return {**r, "path": f"/party.html?t={r['token']}"}


@router.delete("/trust/parties/link", tags=["trust"])
def drop_link(name: str, branch: Optional[str] = None):
    return {"revoked": _run(trust.revoke_party_link, _branch(branch), name)}


@router.get("/trust/party/{token}", tags=["trust"])
def party_view(token: str):
    return _run(trust.party_view, token)


@router.post("/trust/party/{token}/entries/{eid}", tags=["trust"])
def party_respond(token: str, eid: int, body: RespondIn):
    """The counterparty states their own figure, disputes, adds a note, or withholds (or grants) consent to be counted in proofs."""
    return _run(trust.party_respond, token, eid, body.cp_amount, body.cp_note, body.disputed, body.proof_consent)


# ------------------------------------------------------------------ cashflow
@router.get("/cashflow/promises", tags=["trust"])
def promise_cashflow(branch: Optional[str] = None, horizon: int = Query(60, ge=7, le=120), opening_cash: Optional[float] = Query(None, ge=-1e9, le=1e9),
                     include_sales: bool = False):
    """Day-by-day cash from the open promises with a 10/50/90% range, per-promise probabilities, and every assumption used."""
    return _run(cashflow.predict, _branch(branch), horizon, opening_cash, include_sales)


# ------------------------------------------------------------------ proofs
@router.get("/proofs/preview", tags=["trust"])
def proof_preview(branch: Optional[str] = None):
    """Exactly what a proof would reveal right now (and which entries are excluded), before anything is signed."""
    return _run(proofs.preview, _branch(branch))


@router.get("/proofs", tags=["trust"])
def list_proofs(branch: Optional[str] = None):
    return {"proofs": _run(proofs.list_proofs, _branch(branch)), "public_key": proofs.public_hex()}


@router.post("/proofs", tags=["trust"], status_code=201)
def issue_proof(body: IssueIn, branch: Optional[str] = None):
    """Sign a proof packet. The response carries the one-time `open_key`; share it only with a verifier you trust to challenge you."""
    return _run(proofs.issue, _branch(branch), body.claims, body.valid_days)


@router.get("/proofs/{pid}", tags=["trust"])
def get_proof(pid: str):
    """The shareable packet (claims only) and whether it was revoked."""
    return _run(proofs.get_packet, pid)


@router.post("/proofs/{pid}/revoke", tags=["trust"])
def revoke_proof(pid: str, branch: Optional[str] = None):
    _run(proofs.revoke, _branch(branch), pid)
    return {"revoked": pid}


@router.post("/proofs/verify", tags=["trust"])
def verify_proof(packet: Dict[str, Any]):
    return proofs.verify(packet)


@router.post("/proofs/{pid}/open", tags=["trust"])
def open_proof(pid: str, body: OpenIn):
    """Verifier's spot-check: entries are chosen from root+nonce, so the shop cannot pick flattering ones."""
    return _run(proofs.open_leaves, pid, body.open_key, body.nonce)


@router.post("/proofs/check-openings", tags=["trust"])
def check_openings(body: CheckIn):
    return proofs.check_openings(body.packet, body.nonce, body.openings)
