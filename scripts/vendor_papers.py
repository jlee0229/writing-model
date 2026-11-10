"""Copy the selected manuscripts out of a local clone of github.com/openai/math.

    python scripts/vendor_papers.py /path/to/openai-math

Each paper is flattened to a single `paper.tex` (all \\input files inlined, comments
stripped) so every downstream step works on one self-contained source.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from legible import tex  # noqa: E402

# slug -> upstream directory under preprints/
PAPERS = {
    "sensitivity": "A-superquadratic-separation-between-sensitivity-and-block-sensitivity-September-25-2026",
    "groupring": "A-Counterexample-to-the-Group-Ring-Determinant-Conjecture-September-23-2026",
    "talagrand": "Talagrands-discrete-convexity-conjecture-September-23-2026",
    "seymour": "A-proof-of-Seymours-second-neighborhood-conjecture-September-23-2026",
    "foulkes": "Quadratic-Stabilization-of-the-Canonical-Foulkes-Howe-Map-September-25-2026",
    "kahnkalai": "The-second-Kahn-Kalai-conjecture-September-24-2026",
    "projbody": "A-product-counterexample-to-the-simplex-maximum-for-projection-body-volume-September-24-2026",
    "thompson": "Thompsons-group-F-is-nonamenable-September-23-2026",
}


def find_main(d: Path) -> Path:
    cands = [p for p in d.rglob("*.tex") if "\\documentclass" in p.read_text(errors="replace")]
    if len(cands) != 1:
        raise RuntimeError(f"{d}: expected one main tex, found {cands}")
    return cands[0]


def main(upstream: Path) -> None:
    commit = subprocess.run(["git", "-C", str(upstream), "rev-parse", "HEAD"],
                            capture_output=True, text=True).stdout.strip()
    lean = set(re.findall(r"id: \.\./preprints/([^/]+)/", (upstream / "lean/formalization.yaml").read_text()))
    index = {}
    for slug, name in PAPERS.items():
        src = upstream / "preprints" / name
        main_tex = find_main(src)
        flat = tex.flatten(main_tex)
        # bibliography files live next to the flattened source
        out = ROOT / "papers" / slug / "original"
        out.mkdir(parents=True, exist_ok=True)
        for m in re.finditer(r"\\(?:bibliography|addbibresource)\{([^}]+)\}", flat):
            for ref in m.group(1).split(","):
                ref = ref.strip()
                for cand in (main_tex.parent / ref, main_tex.parent / (ref + ".bib")):
                    if cand.is_file():
                        shutil.copy(cand, out / cand.name)
        flat = re.sub(r"\\bibliography\{([^}]+)\}",
                      lambda m: "\\bibliography{" + ",".join(Path(r.strip()).name for r in m.group(1).split(",")) + "}", flat)
        flat = re.sub(r"\\addbibresource\{([^}]+)\}",
                      lambda m: "\\addbibresource{" + Path(m.group(1).strip()).name + "}", flat)
        (out / "paper.tex").write_text(flat)
        pdfs = [p for p in src.glob("*.pdf")]
        if pdfs:
            shutil.copy(pdfs[0], out / "upstream.pdf")
        title = re.search(r"^# \[(.+?)\]", (src / "README.md").read_text(), re.M)
        index[slug] = {
            "title": title.group(1) if title else slug,
            "upstream_dir": f"preprints/{name}",
            "upstream_commit": commit,
            "lean_formalized_main_result": name in lean,
            "words": tex.word_count(flat),
        }
        ok, log = tex.compile_pdf(out / "paper.tex")
        index[slug]["compiles"] = ok
        print(f"{slug:12s} words={index[slug]['words']:6d} lean={index[slug]['lean_formalized_main_result']} compiles={ok} {'' if ok else log[:200]}")
    (ROOT / "papers" / "index.json").write_text(json.dumps(index, indent=2, ensure_ascii=False) + "\n")
    shutil.copy(upstream / "LICENSE", ROOT / "papers" / "LICENSE-openai-math")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
