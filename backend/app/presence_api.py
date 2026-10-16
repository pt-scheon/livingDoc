"""REST routes: the owner-controlled public page, the drafting helper and its audit log."""
from typing import List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .config import settings
from .services import catalog, presence

router = APIRouter(prefix="/api")


def _branch(branch: Optional[str]) -> str:
    b = branch or settings.default_branch
    if not catalog.branch_exists(b):
        raise HTTPException(404, f"Unknown branch {b!r}")
    return b


def _run(fn, *a, **k):
    try:
        return fn(*a, **k)
    except presence.PresenceError as e:
        raise HTTPException(400, str(e))
    except KeyError as e:
        raise HTTPException(404, f"Not found: {e.args[0]}")


class ProfileIn(BaseModel):
    name: Optional[str] = None
    tagline: Optional[str] = None
    about: Optional[str] = None
    area: Optional[str] = None
    hours: Optional[str] = None
    languages: Optional[List[str]] = None
    show_products: Optional[bool] = None
    product_names: Optional[List[str]] = None
    show_trust: Optional[bool] = None
    proof_id: Optional[str] = None
    published: Optional[bool] = None
    autonomy: Optional[str] = None
    budget_cap: Optional[float] = Field(default=None, ge=0, le=1e7)


class SuggestIn(BaseModel):
    lang: str = "en"


class TextIn(BaseModel):
    text: str


class BoostIn(BaseModel):
    amount: float = Field(gt=0, le=1e7)


@router.get("/presence", tags=["presence"])
def get_presence(branch: Optional[str] = None):
    b = _branch(branch)
    return dict(profile=_run(presence.get_profile, b), budget=presence.budget(b), items=[i["name"] for i in catalog.list_items(b)])


@router.put("/presence", tags=["presence"])
def put_presence(body: ProfileIn, branch: Optional[str] = None):
    b = _branch(branch)
    return dict(profile=_run(presence.update_profile, b, body.model_dump(exclude_unset=True)), budget=presence.budget(b))


@router.post("/presence/suggest", tags=["presence"], status_code=201)
def suggest(body: SuggestIn, branch: Optional[str] = None):
    """The helper writes drafts when asked. It never publishes, edits the profile or spends."""
    return {"drafts": _run(presence.suggest, _branch(branch), body.lang)}


@router.get("/presence/drafts", tags=["presence"])
def drafts(branch: Optional[str] = None):
    return {"drafts": presence.list_drafts(_branch(branch))}


@router.patch("/presence/drafts/{did}", tags=["presence"])
def edit(did: int, body: TextIn, branch: Optional[str] = None):
    return _run(presence.edit_draft, _branch(branch), did, body.text)


@router.post("/presence/drafts/{did}/boost", tags=["presence"])
def boost(did: int, body: BoostIn, branch: Optional[str] = None):
    return _run(presence.boost, _branch(branch), did, body.amount)


@router.post("/presence/drafts/{did}/{action}", tags=["presence"])
def decide(did: int, action: str, branch: Optional[str] = None):
    return _run(presence.decide, _branch(branch), did, action)


@router.get("/presence/log", tags=["presence"])
def get_log(branch: Optional[str] = None):
    return {"log": presence.log(_branch(branch))}


@router.get("/presence/public/{slug}", tags=["presence"])
def public(slug: str):
    """The only unauthenticated view of a shop: published, owner-chosen fields only."""
    return _run(presence.public_view, slug)
