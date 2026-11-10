"""Independent fidelity audit of final rewrites by a second model (Opus), fresh context.

    python scripts/second_audit.py B,C
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from legible.llm import call, pmap  # noqa: E402
from legible.pipeline import AUDIT_SCHEMA, prompt  # noqa: E402

arms = sys.argv[1].split(",")
jobs = [(s, a) for s in json.loads((ROOT / "papers/index.json").read_text()) for a in arms
        if (ROOT / "runs" / s / "clean" / a / "rewrite.tex").exists()]


def one(job):
    slug, arm = job
    d = ROOT / "runs" / slug / "clean" / arm
    r = call(prompt("audit", DOC=(d.parent / "source.tex").read_text(), REWRITE=(d / "rewrite.tex").read_text()),
             model="infra", effort="high", schema=AUDIT_SCHEMA,
             system="You are a meticulous referee checking a rewritten proof against its source.",
             tag=f"{slug}/clean/{arm}/audit-opus", role="audit_second")["data"]
    (d / "audit_second_model.json").write_text(json.dumps(r, indent=1, ensure_ascii=False))
    return slug, arm, {k: len(v) for k, v in r.items()}


for res in pmap(one, jobs):
    print(res if not isinstance(res, Exception) else "FAILED " + repr(res)[:200])
