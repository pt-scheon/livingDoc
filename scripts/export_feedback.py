"""Write the owner's suggestions to notes/FEEDBACK.md so coding assistants (Gemini, Claude) can read them.

    python scripts/export_feedback.py [--branch "Main Store"] [--out notes/FEEDBACK.md]

Reads the same database the app uses (LIVINGDOC_DB). Customer comments, names and contacts are never exported.
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.config import settings  # noqa: E402
from app.services import feedback  # noqa: E402
from app.services.seed import init_db  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--branch", default=settings.default_branch)
ap.add_argument("--out", default=str(ROOT / "notes" / "FEEDBACK.md"))
a = ap.parse_args()
init_db()   # make sure the tables exist, also on a brand-new database
out = Path(a.out)
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(feedback.export_markdown(a.branch), encoding="utf-8")
print(f"wrote {out}")
