"""REST routes: owner suggestions to the developer, customer comments on the public page, and the developer export."""
from typing import Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from .config import settings
from .services import catalog, feedback

router = APIRouter(prefix="/api")


def _branch(branch: Optional[str]) -> str:
    b = branch or settings.default_branch
    if not catalog.branch_exists(b):
        raise HTTPException(404, f"Unknown branch {b!r}")
    return b


def _run(fn, *a, **k):
    try:
        return fn(*a, **k)
    except feedback.FeedbackError as e:
        raise HTTPException(400, str(e))
    except KeyError as e:
        raise HTTPException(404, f"Not found: {e.args[0]}")


class OwnerIn(BaseModel):
    text: str = Field(max_length=1000)
    category: str = "idea"
    screen: str = Field(default="", max_length=40)
    lang: str = "en"


class CustomerIn(BaseModel):
    text: str = Field(default="", max_length=1000)
    rating: Optional[int] = Field(default=None, ge=1, le=5)
    name: str = Field(default="", max_length=80)
    contact: str = Field(default="", max_length=120)
    lang: str = "en"
    website: str = ""          # honeypot: people leave it empty, scripts fill it


class StatusIn(BaseModel):
    status: Optional[str] = None
    dev_note: Optional[str] = Field(default=None, max_length=400)


@router.get("/feedback", tags=["feedback"])
def get_feedback(branch: Optional[str] = None, source: Optional[str] = None):
    b = _branch(branch)
    return dict(summary=feedback.summary(b), items=feedback.list_(b, source if source in ("owner", "customer") else None))


@router.post("/feedback", tags=["feedback"], status_code=201)
def suggest_to_developer(body: OwnerIn, branch: Optional[str] = None):
    """The shop owner suggests something to the developer of LivingDoc."""
    return _run(feedback.add, _branch(branch), "owner", body.text, body.category, None, "", "", body.lang, body.screen)


@router.patch("/feedback/{fid}", tags=["feedback"])
def update_feedback(fid: int, body: StatusIn, branch: Optional[str] = None):
    return _run(feedback.set_status, _branch(branch), fid, body.status, body.dev_note)


@router.get("/feedback/export.md", tags=["feedback"], response_class=PlainTextResponse)
def export_md(branch: Optional[str] = None):
    """Markdown for the notes folder that coding assistants (Gemini, Claude) read. Owner suggestions only."""
    return PlainTextResponse(feedback.export_markdown(_branch(branch)), media_type="text/markdown; charset=utf-8")


@router.post("/presence/public/{slug}/feedback", tags=["feedback"], status_code=201)
def customer_feedback(slug: str, body: CustomerIn):
    """A visitor leaves a comment for the shop. Public, rate-limited, only for a published page."""
    from .database import db
    with db() as c:
        r = c.execute("SELECT branch FROM presence_profiles WHERE slug=? AND published=1", (slug,)).fetchone()
    if r is None:
        raise HTTPException(404, "This shop page is not available")
    if body.website:
        return {"ok": True}              # silently drop bots
    if feedback.throttle(slug):
        raise HTTPException(429, "Too many comments just now. Please try again later.")
    _run(feedback.add, r["branch"], "customer", body.text, "praise" if (body.rating or 0) >= 4 else "idea", body.rating, body.name, body.contact, body.lang)
    return {"ok": True}
