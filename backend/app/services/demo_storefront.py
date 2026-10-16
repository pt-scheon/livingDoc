"""Optional demo content for a hosted demo: a published public page, a signed proof and a few posts.

Switched on only by LIVINGDOC_DEMO_STOREFRONT=1 (the Dockerfile sets it), so tests and local use keep the private-by-default behaviour.
It runs once: if the branch already has a public-page profile it does nothing, so it never overwrites an owner's choices.
Everything it publishes is sample data. Clear it before using the app for a real shop.
"""
from __future__ import annotations

import os
from datetime import timedelta

from ..config import settings
from . import catalog, presence, proofs, trust

DEMO_PARTIES = [("Sunita Stores", 5000, 5), ("Kiran Traders", 3000, 6), ("Asha Caterers", 2000, 8)]


def enabled() -> bool:
    return os.environ.get("LIVINGDOC_DEMO_STOREFRONT", "0") == "1"


def seed(branch: str | None = None) -> bool:
    if not enabled():
        return False
    branch = branch or settings.default_branch
    p = presence.get_profile(branch)
    if p["published"] or p["tagline"] or p["name"] != branch:
        return False   # the owner has already made choices; never overwrite them
    items = [i["name"] for i in catalog.list_items(branch)]
    today = trust.today()
    for who, amt, due in DEMO_PARTIES:
        trust.create_entry(branch, "owed_to_us", who, "Sample order on credit", amt, (today + timedelta(days=due)).isoformat(), "customer", True)
    pk = proofs.issue(branch, None, proofs.MAX_VALID_DAYS)["packet"]
    presence.update_profile(branch, dict(
        name="Shah Provision", tagline="Spices, milk and festival sweets since 1998",
        about="A neighbourhood provision store. This is a sample page: the owner chooses every line, and stock, customers and money owed are never shown.",
        area="Navrangpura, Ahmedabad", hours="Mo-Sa 09:00-21:00", languages=["en", "hi", "gu"],
        show_products=True, product_names=items[:8], show_trust=True, proof_id=pk["id"], published=True, budget_cap=500))
    for lang in ("en", "hi", "gu"):
        for d in presence.suggest(branch, lang):
            presence.decide(branch, d["id"], "approve")
            presence.decide(branch, d["id"], "publish")
    return True
