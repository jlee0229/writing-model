"""LaTeX helpers: flatten multi-file sources, strip comments, compile, measure."""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

_INPUT = re.compile(r"\\(?:input|include)\{([^}]+)\}")
_COMMENT = re.compile(r"(?<!\\)%.*$")


def strip_comments(tex: str) -> str:
    out = []
    for line in tex.splitlines():
        stripped = _COMMENT.sub("", line)
        if stripped.strip() == "" and line.strip().startswith("%"):
            continue  # drop full-line comments entirely
        out.append(stripped.rstrip())
    return "\n".join(out) + "\n"


def flatten(main: Path, _depth: int = 0) -> str:
    """Inline \\input/\\include recursively (paths resolved against the main file's dir)."""
    base = main.parent
    tex = strip_comments(main.read_text(encoding="utf-8", errors="replace"))

    def repl(m):
        name = m.group(1).strip()
        cands = [base / name, base / (name + ".tex")]
        for c in cands:
            if c.is_file():
                if _depth > 6:
                    raise RuntimeError("input recursion too deep")
                sub = strip_comments(c.read_text(encoding="utf-8", errors="replace"))
                # nested inputs are still relative to the root dir (LaTeX semantics)
                return _INPUT.sub(repl, sub)
        return m.group(0)

    return _INPUT.sub(repl, tex)


def body(tex: str) -> str:
    m = re.search(r"\\begin\{document\}(.*)\\end\{document\}", tex, re.S)
    return m.group(1) if m else tex


def reading_text(tex: str) -> str:
    """What a reader model sees: the full flattened source minus the bibliography list."""
    tex = re.sub(r"\\begin\{thebibliography\}.*?\\end\{thebibliography\}",
                 "% [bibliography omitted]", tex, flags=re.S)
    return tex.strip() + "\n"


def word_count(tex: str) -> int:
    """Rough prose+math word count of the document body (bibliography excluded)."""
    t = body(reading_text(tex))
    t = re.sub(r"\\(begin|end)\{[^}]*\}", " ", t)
    t = re.sub(r"\\[a-zA-Z@]+\*?", " ", t)
    t = re.sub(r"[{}$\\^_&~]", " ", t)
    return len(t.split())


def compile_pdf(tex_path: Path, timeout: int = 300) -> tuple[bool, str]:
    """latexmk in the file's directory. Returns (ok, tail of log)."""
    d = tex_path.parent
    try:
        p = subprocess.run(
            ["latexmk", "-pdf", "-interaction=nonstopmode", "-halt-on-error", "-quiet", tex_path.name],
            cwd=d, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return False, "latexmk timeout"
    pdf = tex_path.with_suffix(".pdf")
    ok = p.returncode == 0 and pdf.exists()
    log = tex_path.with_suffix(".log")
    tail = ""
    if log.exists():
        lines = log.read_text(errors="replace").splitlines()
        errs = [i for i, l in enumerate(lines) if l.startswith("!")]
        if errs:
            i = errs[0]
            tail = "\n".join(lines[i:i + 12])
    for ext in (".aux", ".fls", ".fdb_latexmk", ".out", ".blg", ".toc", ".bcf", ".run.xml"):
        f = tex_path.with_suffix(ext)
        if f.exists():
            f.unlink()
    return ok, tail or (p.stdout[-500:] + p.stderr[-500:])


def copy_support(src_dir: Path, dst_dir: Path) -> None:
    """Copy .bib/.bbl files next to a rewritten paper so it compiles standalone."""
    for f in src_dir.iterdir():
        if f.suffix in (".bib", ".bbl", ".bst") and not (dst_dir / f.name).exists():
            shutil.copy(f, dst_dir / f.name)
