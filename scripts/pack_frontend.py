"""Build frontend-pack/livingdoc-frontend-pack.zip from frontend/ (run after changing the frontend).

    python scripts/pack_frontend.py
"""
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "frontend"
OUT = ROOT / "frontend-pack" / "livingdoc-frontend-pack.zip"

with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED) as z:
    for p in sorted(SRC.rglob("*")):
        if p.is_file() and "__pycache__" not in p.parts and p.name != ".DS_Store":
            z.write(p, "livingdoc-frontend/" + p.relative_to(SRC).as_posix())
    z.write(ROOT / "frontend-pack" / "README.md", "livingdoc-frontend/PACK-README.md")
print(f"wrote {OUT} ({OUT.stat().st_size // 1024} KB)")
