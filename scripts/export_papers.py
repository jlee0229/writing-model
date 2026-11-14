"""Copy the final rewrites (tex + pdf) next to the originals under papers/<slug>/.

    python scripts/export_papers.py
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from writing_model import tex  # noqa: E402

NAMES = {"B": "rewrite-oneshot", "L": "rewrite-located", "C": "rewrite-compact", "C0": "rewrite-compact-noreports"}

for slug in json.loads((ROOT / "papers" / "index.json").read_text()):
    for arm, name in NAMES.items():
        src = ROOT / "runs" / slug / "clean" / arm
        if not (src / "rewrite.tex").exists():
            continue
        dst = ROOT / "papers" / slug / name
        dst.mkdir(parents=True, exist_ok=True)
        shutil.copy(src / "rewrite.tex", dst / "paper.tex")
        tex.copy_support(ROOT / "papers" / slug / "original", dst)
        if not (src / "rewrite.pdf").exists():
            tex.compile_pdf(src / "rewrite.tex")
        if (src / "rewrite.pdf").exists():
            shutil.copy(src / "rewrite.pdf", dst / "paper.pdf")
        print(slug, name, "pdf" if (dst / "paper.pdf").exists() else "NO PDF")
