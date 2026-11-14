"""Rewrite pipeline.

Two arms, both followed by the same independent audit (+ at most one repair):

  B  one-shot:   source ──rewrite──▶ draft ──audit/repair──▶ final
  L  located:    source ──3 weak readers──▶ stuck-point reports
                        ──rewrite(with reports)──▶ draft1
                        ──3 weak readers on draft1──▶ reports
                        ──revise──▶ draft2 ──audit/repair──▶ final

The rewriter is told the source is believed correct and never sees any evaluation
material. The same code runs on clean sources and on sources with a planted error
(variants err1, err2, ...): that is what makes the error-detection test honest.

    python -m writing_model.pipeline --papers sensitivity,foulkes --variants clean --arms B,L
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import traceback
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import tex
from .llm import ROOT, call, total_cost

PROMPTS = ROOT / "prompts"
N_LOCATORS = 3
MAX_REPAIRS = 3

LOCATE_SCHEMA = {
    "type": "object",
    "properties": {
        "main_result": {"type": "string"},
        "proof_strategy": {"type": "string"},
        "hardest_part": {"type": "string"},
        "issues": {"type": "array", "items": {
            "type": "object",
            "properties": {
                "where": {"type": "string"},
                "quote": {"type": "string"},
                "kind": {"type": "string", "enum": ["unjustified_step", "undefined_notation", "lost_thread",
                                                     "ambiguous_statement", "heavy_computation", "suspected_error"]},
                "severity": {"type": "integer"},
                "what_i_needed": {"type": "string"},
            },
            "required": ["where", "quote", "kind", "severity", "what_i_needed"]}},
    },
    "required": ["main_result", "proof_strategy", "hardest_part", "issues"],
}

AUDIT_SCHEMA = {
    "type": "object",
    "properties": {
        "statements": {"type": "array", "items": {"type": "object", "properties": {
            "name": {"type": "string"}, "status": {"type": "string", "enum": ["changed", "missing"]},
            "detail": {"type": "string"}}, "required": ["name", "status", "detail"]}},
        "introduced": {"type": "array", "items": {"type": "object", "properties": {
            "where": {"type": "string"}, "quote": {"type": "string"}, "problem": {"type": "string"},
            "severity": {"type": "integer"}}, "required": ["where", "quote", "problem", "severity"]}},
        "source_doubts": {"type": "array", "items": {"type": "object", "properties": {
            "where": {"type": "string"}, "quote": {"type": "string"}, "problem": {"type": "string"},
            "already_marked_unverified": {"type": "boolean"}},
            "required": ["where", "quote", "problem", "already_marked_unverified"]}},
        "unverified_marks": {"type": "array", "items": {"type": "object", "properties": {
            "where": {"type": "string"}, "concern": {"type": "string"}, "warranted": {"type": "boolean"}},
            "required": ["where", "concern", "warranted"]}},
    },
    "required": ["statements", "introduced", "source_doubts", "unverified_marks"],
}


def prompt(name: str, **kw) -> str:
    t = (PROMPTS / f"{name}.md").read_text()
    if "{{SPEC}}" in t:
        t = t.replace("{{SPEC}}", (PROMPTS / "rewrite_spec.md").read_text().strip())
    for k, v in kw.items():
        t = t.replace("{{" + k + "}}", v)
    left = re.findall(r"\{\{[A-Z_]+\}\}", t.split("<source>")[0])
    if left:
        raise ValueError(f"unfilled placeholders in {name}: {left}")
    return t


def extract_tex(text: str) -> str:
    i = text.find("\\documentclass")
    j = text.rfind("\\end{document}")
    if i < 0 or j < 0:
        raise ValueError("model output is not a LaTeX document")
    return text[i:j + len("\\end{document}")] + "\n"


def locate(doc: str, tag: str) -> list[dict]:
    """Three weak readers independently report where they got stuck."""
    def one(i):
        r = call(prompt("reader_locate", DOC=tex.reading_text(doc)), model="weak", effort="medium",
                 system="You are a first-year mathematics graduate student reading a research manuscript outside your specialty. You report honestly where you cannot follow.",
                 schema=LOCATE_SCHEMA, tag=f"{tag}/locator{i}", role="locate")
        return r["data"]
    with ThreadPoolExecutor(N_LOCATORS) as ex:
        return list(ex.map(one, range(N_LOCATORS)))


def severity_load(reports: list[dict]) -> float:
    """Mean severity-weighted stuck-point count per reader (the in-loop readability signal)."""
    return sum(sum(int(i.get("severity", 1)) for i in r["issues"]) for r in reports) / max(1, len(reports))


def _write(model_text: str) -> str:
    return extract_tex(model_text)


def gen(name: str, tag: str, **kw) -> str:
    r = call(prompt(name, **kw), model="rewriter", effort="high",
             system="You are an expert mathematical expositor. You write proofs that can be checked line by line, and you never change the mathematics.",
             tag=tag, role=name)
    return _write(r["text"])


def audit(doc: str, rewrite: str, tag: str) -> dict:
    r = call(prompt("audit", DOC=doc, REWRITE=rewrite), model="auditor", effort="high",
             system="You are a meticulous referee checking a rewritten proof against its source.",
             schema=AUDIT_SCHEMA, tag=tag, role="audit")
    return r["data"]


def needs_repair(a: dict) -> bool:
    return bool(a["statements"] or a["introduced"] or
                any(not d["already_marked_unverified"] for d in a["source_doubts"]))


def ensure_compiles(d: Path, src_dir: Path, name: str, tag: str) -> bool:
    tex.copy_support(src_dir, d)
    path = d / f"{name}.tex"
    for attempt in range(3):
        ok, log = tex.compile_pdf(path)
        if ok:
            return True
        fixed = call("This LaTeX document fails to compile with pdflatex. Fix the compile error and change nothing else "
                     "(no wording, no mathematics). Output the full corrected document and nothing else.\n\n"
                     f"<error>\n{log}\n</error>\n\n<document>\n{path.read_text()}\n</document>",
                     model="rewriter", effort="low", tag=f"{tag}/texfix{attempt}", role="texfix")
        path.write_text(extract_tex(fixed["text"]))
    return tex.compile_pdf(path)[0]


def run_arm(slug: str, variant: str, arm: str) -> dict:
    vdir = ROOT / "runs" / slug / variant
    src_path = vdir / "source.tex"
    if not src_path.exists():
        if variant != "clean":
            raise FileNotFoundError(f"{src_path} (plant errors first)")
        vdir.mkdir(parents=True, exist_ok=True)
        shutil.copy(ROOT / "papers" / slug / "original" / "paper.tex", src_path)
    doc = src_path.read_text()
    d = vdir / arm
    d.mkdir(parents=True, exist_ok=True)
    tag = f"{slug}/{variant}/{arm}"
    meta = {"slug": slug, "variant": variant, "arm": arm, "source_words": tex.word_count(doc)}

    if arm == "B":
        draft = gen("rewrite_oneshot", tag + "/draft", DOC=doc)
    elif arm == "L":
        rep1 = locate(doc, tag + "/r1")
        (d / "reports_on_source.json").write_text(json.dumps(rep1, indent=1, ensure_ascii=False))
        meta["stuck_load_source"] = severity_load(rep1)
        draft1 = gen("rewrite_located", tag + "/draft1", DOC=doc, REPORTS=json.dumps(rep1, ensure_ascii=False))
        (d / "draft1.tex").write_text(draft1)
        rep2 = locate(draft1, tag + "/r2")
        (d / "reports_on_draft1.json").write_text(json.dumps(rep2, indent=1, ensure_ascii=False))
        meta["stuck_load_draft1"] = severity_load(rep2)
        draft = gen("revise", tag + "/draft2", DOC=doc, REWRITE=draft1, REPORTS=json.dumps(rep2, ensure_ascii=False))
    elif arm in ("C", "C0"):
        # length-controlled rewrite: C uses the weak readers' reports to decide where to spend words, C0 does not
        n = meta["source_words"]
        located, block = "", ""
        if arm == "C":
            rp = vdir / "L" / "reports_on_source.json"
            rep1 = json.loads(rp.read_text()) if rp.exists() else locate(doc, f"{slug}/{variant}/L/r1")
            (d / "reports_on_source.json").write_text(json.dumps(rep1, indent=1, ensure_ascii=False))
            located = ("\n**Reader reports.** Three less experienced readers each tried to verify the source and reported where they "
                       "got stuck (JSON below). Use them to decide where the words go: a place where a reader could not continue "
                       "(severity 2 or 3), or that more than one reader reported, deserves an explicit step; a severity-1 remark "
                       "that the reader resolved on their own usually does not. Treat the reports as evidence about exposition, "
                       "not as mathematical authority.\n")
            block = "\n<reader_reports>\n" + json.dumps(rep1, ensure_ascii=False) + "\n</reader_reports>\n"
        draft = gen("rewrite_compact", tag + "/draft", DOC=doc, N=str(n), LIMIT=str(int(1.25 * n)),
                    LOCATED=located, REPORTS_BLOCK=block)
    else:
        raise ValueError(arm)
    (d / "draft.tex").write_text(draft)

    a1 = audit(doc, draft, tag + "/audit1")
    (d / "audit1.json").write_text(json.dumps(a1, indent=1, ensure_ascii=False))
    final, final_audit, rounds = draft, a1, 0
    while needs_repair(final_audit) and rounds < MAX_REPAIRS:
        rounds += 1
        suffix = "" if rounds == 1 else str(rounds)          # keeps cache keys of round 1 stable
        final = gen("repair", tag + "/repair" + suffix, DOC=doc, REWRITE=final,
                    AUDIT=json.dumps(final_audit, ensure_ascii=False))
        final_audit = audit(doc, final, tag + f"/audit{rounds + 1}")
        (d / f"audit{rounds + 1}.json").write_text(json.dumps(final_audit, indent=1, ensure_ascii=False))
    meta["repaired"] = rounds > 0
    meta["repair_rounds"] = rounds
    (d / "rewrite.tex").write_text(final)
    meta["compiles"] = ensure_compiles(d, ROOT / "papers" / slug / "original", "rewrite", tag)
    final = (d / "rewrite.tex").read_text()
    meta.update({
        "rewrite_words": tex.word_count(final),
        "length_ratio": round(tex.word_count(final) / meta["source_words"], 2),
        "unverified_marks": len(re.findall(r"\\unverified\{", tex.body(final))),
        "audit1": {k: len(v) for k, v in a1.items()},
        "final_audit": {k: len(v) for k, v in final_audit.items()},
    })
    (d / "meta.json").write_text(json.dumps(meta, indent=1))
    return meta


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--papers", required=True)
    ap.add_argument("--variants", default="clean")
    ap.add_argument("--arms", default="B,L")
    args = ap.parse_args(argv)
    jobs = [(s, v, a) for s in args.papers.split(",") for v in args.variants.split(",") for a in args.arms.split(",")]

    def safe(job):
        try:
            m = run_arm(*job)
            print("done", job, {k: m[k] for k in ("length_ratio", "unverified_marks", "repaired", "compiles", "final_audit")}, flush=True)
            return m
        except Exception as e:  # noqa: BLE001
            print("FAILED", job, repr(e)[:300], flush=True)
            traceback.print_exc()
            return None

    with ThreadPoolExecutor(len(jobs)) as ex:
        list(ex.map(safe, jobs))
    print(f"cumulative list-price cost so far: ${total_cost():.2f}")


if __name__ == "__main__":
    sys.exit(main())
