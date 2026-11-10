"""Blind evaluation with reader models.

Three measurements, all on the same documents (arm O = original, B = one-shot
rewrite, L = located rewrite):

  quiz      comprehension: multiple-choice questions written from the ORIGINAL only,
            answered by reader models who see one document (full, or only its first
            N words), plus a closed-book floor.
  errors    planted-error detection: an error is planted in the original, the
            corrupted original goes through each rewrite arm blind, and readers are
            asked whether the proof contains an error. Clean documents give the
            false-alarm rate.
  pairwise  blind preference between two writeups, both presentation orders.

    python -m legible.evalkit quiz-write --papers a,b
    python -m legible.evalkit quiz-run   --papers a,b
    python -m legible.evalkit plant      --papers a,b
    python -m legible.evalkit err-run    --papers a,b --variants clean,err1,err2
    python -m legible.evalkit pairwise   --papers a,b
"""
from __future__ import annotations

import argparse
import json
import random
import re
import sys
import threading
from pathlib import Path

from . import tex
from .llm import ROOT, call, pmap, total_cost
from .pipeline import prompt

RES = ROOT / "results"
# Held-out readers, weakest first: (model role, effort). "novice" is an older small model with
# reasoning switched off, so it can only follow what is written; the other two can reconstruct steps.
READERS = [("novice", None), ("weak", "low"), ("mid", "low")]
SEEDS = {"novice": 4, "weak": 4, "mid": 3}
BUDGETS = [None, 1500]                                # None = whole document; else first N words
GRADER = ("mid", "low")                               # marks free-response answers against the key, blind to arm
_lock = threading.Lock()


# ---------------------------------------------------------------- documents
def doc_path(slug: str, variant: str, arm: str) -> Path:
    v = ROOT / "runs" / slug / variant
    return v / "source.tex" if arm == "O" else v / arm / "rewrite.tex"


def load_doc(slug: str, variant: str, arm: str) -> str:
    return tex.reading_text(doc_path(slug, variant, arm).read_text())


def truncate(doc: str, n_words: int) -> str:
    """Preamble (for macro definitions) + the first n_words whitespace tokens of the body."""
    i = doc.find("\\begin{document}")
    head, bod = doc[:i], doc[i:]
    toks = re.findall(r"\S+\s*", bod)
    if len(toks) <= n_words:
        return doc
    return head + "".join(toks[:n_words]) + "\n\n[... the document continues, but you did not have time to read further ...]\n"


def append(path: Path, row: dict) -> None:
    with _lock:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def read_rows(path: Path) -> list[dict]:
    return [json.loads(l) for l in path.read_text().splitlines() if l.strip()] if path.exists() else []


# ---------------------------------------------------------------- quiz
QUIZ_SCHEMA = {"type": "object", "properties": {"questions": {"type": "array", "items": {
    "type": "object", "properties": {
        "id": {"type": "integer"}, "type": {"type": "string", "enum": ["gist", "step", "transfer"]},
        "question": {"type": "string"}, "answer": {"type": "string"},
        "must_include": {"type": "array", "items": {"type": "string"}}},
    "required": ["id", "type", "question", "answer", "must_include"]}}}, "required": ["questions"]}
ANS_SCHEMA = {"type": "object", "properties": {"answers": {"type": "array", "items": {
    "type": "object", "properties": {"q": {"type": "integer"}, "answer": {"type": "string"}},
    "required": ["q", "answer"]}}}, "required": ["answers"]}
QGRADE_SCHEMA = {"type": "object", "properties": {"grades": {"type": "array", "items": {
    "type": "object", "properties": {"q": {"type": "integer"}, "correct": {"type": "boolean"}},
    "required": ["q", "correct"]}}}, "required": ["grades"]}


def answer_quiz(qs, doc, reader, effort, tag, budget=None) -> dict:
    """One reader answers the whole quiz (free response), then a blind grader marks it."""
    if doc is None:
        pre = "No document is provided. This checks what can be answered without reading the paper."
        block = ""
    elif budget:
        pre = "You had time to read only the beginning of the document below; it is cut off where you stopped."
        block = f"<document>\n{truncate(doc, budget)}\n</document>"
    else:
        pre = "Read the document below."
        block = f"<document>\n{doc}\n</document>"
    text = "\n\n".join(f"Q{q['id']}. {q['question']}" for q in qs)
    r = call(prompt("quiz_answer", PREAMBLE=pre, DOCBLOCK=block, QUESTIONS=text), model=reader, effort=effort,
             system="You are a mathematics graduate student taking a comprehension test.",
             schema=ANS_SCHEMA, tag=tag, role="quiz_answer")
    got = {a["q"]: a["answer"] for a in r["data"]["answers"]}
    # the grader never sees the document or which arm the reader was in
    items = "\n\n".join(
        f"Q{q['id']}. {q['question']}\nReference answer: {q['answer']}\nMust include: {json.dumps(q['must_include'], ensure_ascii=False)}\n"
        f"Reader's answer: {got.get(q['id'], '(no answer)')}" for q in qs)
    g = call(prompt("quiz_grade", ITEMS=items), model=GRADER[0], effort=GRADER[1], schema=QGRADE_SCHEMA,
             system="You are a strict, fair grader of mathematics.", tag="grade/" + tag, role="quiz_grade")["data"]
    marks = {x["q"]: int(bool(x["correct"])) for x in g["grades"]}
    return {"correct": {q["id"]: marks.get(q["id"], 0) for q in qs}, "answers": got, "usage": r["usage"]}


def quiz_write(slugs):
    def one(slug):
        out = RES / "quiz" / f"{slug}.json"
        if out.exists():
            return slug, json.loads(out.read_text())
        doc = load_doc(slug, "clean", "O")
        r = call(prompt("quiz_write", DOC=doc), model="infra", effort="high", schema=QUIZ_SCHEMA,
                 system="You write rigorous assessments of proof comprehension.", tag=f"quiz3/{slug}", role="quiz_write")
        qs = r["data"]["questions"]
        for i, q in enumerate(qs, 1):
            q["id"] = i
        # key validation: the strongest model answers open-book from the original, twice
        votes = [answer_quiz(qs, doc, "auditor", "high", f"quizkey/{slug}/s{s}")["correct"] for s in range(2)]
        for q in qs:
            q["key_confirmed"] = all(v[q["id"]] for v in votes)
        # closed-book floor: can a reader answer without the paper?
        for reader, effort in READERS:
            cb = [answer_quiz(qs, None, reader, effort, f"quizcb/{slug}/{reader}/s{s}")["correct"] for s in range(2)]
            for q in qs:
                q[f"closed_book_{reader}"] = sum(c[q["id"]] for c in cb) / len(cb)
        for q in qs:
            # usable = the answer key is confirmed. Whether a question is too easy to guess is
            # decided per reader at analysis time, from that reader's closed-book rate.
            q["usable"] = bool(q["key_confirmed"])
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps({"slug": slug, "questions": qs}, indent=1, ensure_ascii=False))
        return slug, {"questions": qs}
    for res in pmap(one, slugs):
        if isinstance(res, Exception):
            print("FAILED quiz-write", repr(res)[:300])
            continue
        slug, quiz = res
        qs = quiz["questions"]
        print(f"{slug:12s} questions={len(qs)} key_confirmed={sum(q['key_confirmed'] for q in qs)} usable={sum(q['usable'] for q in qs)} closed_book "
              + " ".join(f"{r}={sum(q[f'closed_book_{r}'] for q in qs)/len(qs):.2f}" for r, _ in READERS))


def quiz_run(slugs, arms, readers=None, budgets=None):
    readers, budgets = readers or READERS, budgets or BUDGETS
    out = RES / "quiz_answers.jsonl"
    done = {(r["slug"], r["arm"], r["reader"], r["seed"], r["budget"]) for r in read_rows(out)}
    jobs = []
    for slug in slugs:
        qs = [q for q in json.loads((RES / "quiz" / f"{slug}.json").read_text())["questions"] if q["usable"]]
        for arm in arms:
            if not doc_path(slug, "clean", arm).exists():
                continue
            doc = load_doc(slug, "clean", arm)
            for reader, effort in readers:
                for budget in budgets:
                    for seed in range(SEEDS[reader]):
                        k = (slug, arm, reader, seed, budget)
                        if k not in done:
                            jobs.append((k, effort, qs, doc))

    def one(job):
        (slug, arm, reader, seed, budget), effort, qs, doc = job
        r = answer_quiz(qs, doc, reader, effort, f"quiz/{slug}/{arm}/{budget}/{reader}/s{seed}", budget)
        row = {"slug": slug, "arm": arm, "reader": reader, "seed": seed, "budget": budget,
               "correct": {str(k): v for k, v in r["correct"].items()},
               "types": {str(q["id"]): q["type"] for q in qs}, "usage": r["usage"]}
        append(out, row)
        return row
    res = pmap(one, jobs)
    print(f"quiz-run: {len(jobs)} jobs, {sum(isinstance(r, Exception) for r in res)} failed; cost so far ${total_cost():.2f}")
    for r in res:
        if isinstance(r, Exception):
            print("  ", repr(r)[:200])


# ---------------------------------------------------------------- planted errors
PLANT_SCHEMA = {"type": "object", "properties": {"variants": {"type": "array", "items": {
    "type": "object", "properties": {
        "where": {"type": "string"}, "kind": {"type": "string"}, "explanation": {"type": "string"},
        "correct_version": {"type": "string"},
        "edits": {"type": "array", "items": {"type": "object", "properties": {
            "find": {"type": "string"}, "replace": {"type": "string"}}, "required": ["find", "replace"]}}},
    "required": ["where", "kind", "explanation", "correct_version", "edits"]}}}, "required": ["variants"]}
VALID_SCHEMA = {"type": "object", "properties": {
    "verdict": {"type": "string", "enum": ["real_error", "harmless", "broken"]},
    "subtlety": {"type": "integer"}, "reason": {"type": "string"}}, "required": ["verdict", "subtlety", "reason"]}
FIND_SCHEMA = {"type": "object", "properties": {
    "verdict": {"type": "string", "enum": ["error", "no_error"]}, "confidence": {"type": "integer"},
    "candidates": {"type": "array", "items": {"type": "object", "properties": {
        "location": {"type": "string"}, "quote": {"type": "string"}, "explanation": {"type": "string"}},
        "required": ["location", "quote", "explanation"]}}}, "required": ["verdict", "confidence", "candidates"]}
GRADE_SCHEMA = {"type": "object", "properties": {"hit_rank": {"type": "integer"}}, "required": ["hit_rank"]}
STATUS_SCHEMA = {"type": "object", "properties": {
    "status": {"type": "string", "enum": ["preserved", "flagged", "repaired", "absent"]},
    "quote": {"type": "string"}}, "required": ["status", "quote"]}


def plant(slugs, k_candidates=4, k_keep=2):
    def one(slug):
        if (ROOT / "runs" / slug / "err1" / "error.json").exists():
            return slug, "exists"
        src = (ROOT / "runs" / slug / "clean" / "source.tex").read_text()
        r = call(prompt("plant_error", DOC=src, K=str(k_candidates)), model="infra", effort="high", schema=PLANT_SCHEMA,
                 system="You design rigorous tests of proof checking.", tag=f"plant/{slug}", role="plant")
        cands = []
        for v in r["data"]["variants"]:
            doc, ok = src, bool(v["edits"])
            for e in v["edits"]:
                if doc.count(e["find"]) != 1 or e["find"] == e["replace"]:
                    ok = False
                    break
                doc = doc.replace(e["find"], e["replace"])
            if not ok:
                continue
            val = call(prompt("validate_error", DOC=src, EDITS=json.dumps(v["edits"], ensure_ascii=False, indent=1),
                              EXPLANATION=v["explanation"]), model="auditor", effort="high", schema=VALID_SCHEMA,
                       system="You are a meticulous referee.", tag=f"plantval/{slug}/{v['where']}", role="plant_validate")["data"]
            cands.append({**v, "validation": val, "doc": doc})
        good = [c for c in cands if c["validation"]["verdict"] == "real_error"]
        # prefer errors that need real checking (subtlety near 3), keep distinct locations
        good.sort(key=lambda c: abs(c["validation"]["subtlety"] - 3))
        kept = []
        for c in good:
            if all(c["where"] != x["where"] for x in kept):
                kept.append(c)
            if len(kept) == k_keep:
                break
        for i, c in enumerate(kept, 1):
            d = ROOT / "runs" / slug / f"err{i}"
            d.mkdir(parents=True, exist_ok=True)
            (d / "source.tex").write_text(c.pop("doc"))
            (d / "error.json").write_text(json.dumps(c, indent=1, ensure_ascii=False))
        return slug, f"candidates={len(r['data']['variants'])} applied={len(cands)} real={len(good)} kept={len(kept)} subtlety={[c['validation']['subtlety'] for c in kept]}"
    for res in pmap(one, slugs):
        print("plant", res if not isinstance(res, Exception) else "FAILED " + repr(res)[:300])


EDIT_SCHEMA = {"type": "object", "properties": {"edits": {"type": "array", "items": {"type": "object", "properties": {
    "find": {"type": "string"}, "replace": {"type": "string"}}, "required": ["find", "replace"]}}}, "required": ["edits"]}


def transplant(slugs, variants, arms):
    """Plant the same error directly into each clean rewrite (variant 'err1' -> directory 'err1t')."""
    jobs = [(s, v, a) for s in slugs for v in variants if v != "clean" for a in arms if a != "O"
            and doc_path(s, "clean", a).exists() and not doc_path(s, v + "t", a).exists()]

    def one(job):
        slug, variant, arm = job
        err = json.loads((ROOT / "runs" / slug / variant / "error.json").read_text())
        src = (ROOT / "runs" / slug / "clean" / "source.tex").read_text()
        rw = doc_path(slug, "clean", arm).read_text()
        feedback = ""
        for attempt in range(3):
            r = call(prompt("transplant_error", DOC=src, TRUTH=truth_text(err), REWRITE=rw) + feedback, model="infra",
                     effort="high", schema=EDIT_SCHEMA, system="You design rigorous tests of proof checking.",
                     tag=f"transplant/{slug}/{variant}/{arm}/{attempt}", role="transplant")["data"]
            bad = [e["find"][:80] for e in r["edits"] if rw.count(e["find"]) != 1 or e["find"] == e["replace"]]
            if r["edits"] and not bad:
                doc = rw
                for e in r["edits"]:
                    doc = doc.replace(e["find"], e["replace"])
                d = doc_path(slug, variant + "t", arm).parent
                d.mkdir(parents=True, exist_ok=True)
                (d / "rewrite.tex").write_text(doc)
                (d / "transplant_edits.json").write_text(json.dumps(r["edits"], indent=1, ensure_ascii=False))
                (d.parent / "error.json").write_text(json.dumps(err, indent=1, ensure_ascii=False))
                return job, len(r["edits"])
            feedback = ("\n\nYour previous attempt was rejected: these `find` strings did not occur exactly once in REWRITE: "
                        + json.dumps(bad, ensure_ascii=False) + ". Copy each `find` verbatim from REWRITE.")
        raise RuntimeError(f"transplant failed for {job}")
    for res in pmap(one, jobs):
        print("transplant", res if not isinstance(res, Exception) else "FAILED " + repr(res)[:200])


def truth_text(err: dict) -> str:
    return json.dumps({k: err[k] for k in ("where", "kind", "explanation", "correct_version", "edits")}, ensure_ascii=False, indent=1)


def err_status(slugs, variants, arms=("B", "L")):
    """What happened to each planted error inside each rewrite (preserved / flagged / repaired / absent)."""
    out = RES / "error_status.jsonl"
    done = {(r["slug"], r["variant"], r["arm"]) for r in read_rows(out)}
    jobs = [(s, v, a) for s in slugs for v in variants if v != "clean" for a in arms
            if (s, v, a) not in done and doc_path(s, v, a).exists()]

    def one(job):
        slug, variant, arm = job
        err = json.loads((ROOT / "runs" / slug / variant / "error.json").read_text())
        r = call(prompt("error_status", TRUTH=truth_text(err), REWRITE=load_doc(slug, variant, arm)), model="infra",
                 effort="medium", schema=STATUS_SCHEMA, system="You are a meticulous referee.",
                 tag=f"errstatus/{slug}/{variant}/{arm}", role="error_status")["data"]
        append(out, {"slug": slug, "variant": variant, "arm": arm, **r})
    res = pmap(one, jobs)
    print(f"err-status: {len(jobs)} jobs, {sum(isinstance(r, Exception) for r in res)} failed")


def err_run(slugs, variants, arms, readers=READERS, question="doc"):
    """question="doc": is there an error in this document's proofs?  question="source": the document is a
    rewrite; was the ORIGINAL proof wrong? (Used when the rewriter itself flagged and corrected the error.)"""
    out = RES / "error_answers.jsonl"
    done = {(r["slug"], r["variant"], r["arm"], r["reader"], r["seed"]) for r in read_rows(out) if r.get("question", "doc") == question}
    qtag = "" if question == "doc" else "/srcq"
    pname = "find_error" if question == "doc" else "find_error_source"
    jobs = []
    for slug in slugs:
        for variant in variants:
            for arm in arms:
                if not doc_path(slug, variant, arm).exists():
                    continue
                for reader, effort in readers:
                    for seed in range(SEEDS[reader]):
                        k = (slug, variant, arm, reader, seed)
                        if k not in done:
                            jobs.append((*k, effort))

    def one(k):
        slug, variant, arm, reader, seed, effort = k
        r = call(prompt(pname, DOC=load_doc(slug, variant, arm)), model=reader, effort=effort, schema=FIND_SCHEMA,
                 system="You are a mathematics graduate student refereeing a proof for correctness.",
                 tag=f"finderr/{slug}/{variant}/{arm}/{reader}/s{seed}{qtag}", role="find_error")
        d = r["data"]
        hit = 0
        if variant != "clean" and d["verdict"] == "error" and d["candidates"]:
            err = json.loads((ROOT / "runs" / slug / variant / "error.json").read_text())
            g = call(prompt("grade_error", TRUTH=truth_text(err),
                            CANDIDATES=json.dumps(d["candidates"][:3], ensure_ascii=False, indent=1)),
                     model="infra", effort="medium", schema=GRADE_SCHEMA, system="You are a strict grader.",
                     tag=f"gradeerr/{slug}/{variant}/{arm}/{reader}/s{seed}{qtag}", role="grade_error")["data"]
            hit = int(g["hit_rank"])
        append(out, {"slug": slug, "variant": variant, "arm": arm, "reader": reader, "seed": seed, "question": question,
                     "verdict": d["verdict"], "confidence": d["confidence"], "hit_rank": hit,
                     "n_candidates": len(d["candidates"]), "usage": r["usage"]})
    res = pmap(one, jobs)
    print(f"err-run: {len(jobs)} jobs, {sum(isinstance(r, Exception) for r in res)} failed; cost so far ${total_cost():.2f}")
    for r in res:
        if isinstance(r, Exception):
            print("  ", repr(r)[:200])


# ---------------------------------------------------------------- pairwise
PAIR_SCHEMA = {"type": "object", "properties": {
    **{c: {"type": "string", "enum": ["1", "2", "tie"]} for c in ("orientation", "checkability", "notation", "economy")},
    "overall": {"type": "string", "enum": ["1", "2"]}, "margin": {"type": "integer"}, "reason": {"type": "string"}},
    "required": ["orientation", "checkability", "notation", "economy", "overall", "margin", "reason"]}
JUDGES = [("weak", "medium"), ("mid", "medium"), ("infra", "medium")]


def pairwise(slugs, pairs=(("O", "L"), ("O", "B"), ("B", "L")), judges=JUDGES):
    out = RES / "pairwise.jsonl"
    done = {(r["slug"], r["x"], r["y"], r["judge"], r["order"]) for r in read_rows(out)}
    jobs = [(s, x, y, j, e, o) for s in slugs for x, y in pairs for j, e in judges for o in (0, 1)
            if (s, x, y, j, o) not in done and doc_path(s, "clean", x).exists() and doc_path(s, "clean", y).exists()]

    def one(job):
        slug, x, y, judge, effort, order = job
        first, second = (x, y) if order == 0 else (y, x)
        r = call(prompt("pairwise", DOC1=load_doc(slug, "clean", first), DOC2=load_doc(slug, "clean", second)),
                 model=judge, effort=effort, schema=PAIR_SCHEMA, system="You are an experienced referee and teacher of mathematics.",
                 tag=f"pair/{slug}/{x}{y}/{judge}/{order}", role="pairwise")["data"]
        name = {"1": first, "2": second, "tie": "tie"}
        append(out, {"slug": slug, "x": x, "y": y, "judge": judge, "order": order,
                     "overall": name[r["overall"]], "margin": r["margin"],
                     **{c: name[r[c]] for c in ("orientation", "checkability", "notation", "economy")},
                     "reason": r["reason"]})
    res = pmap(one, jobs)
    print(f"pairwise: {len(jobs)} jobs, {sum(isinstance(r, Exception) for r in res)} failed; cost so far ${total_cost():.2f}")


# ---------------------------------------------------------------- cli
def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["quiz-write", "quiz-run", "plant", "transplant", "err-run", "err-status", "pairwise"])
    ap.add_argument("--readers", default="novice,weak,mid")
    ap.add_argument("--pairs", default="O:L,O:B,B:L")
    ap.add_argument("--judges", default="weak,mid,infra")
    ap.add_argument("--question", default="doc", choices=["doc", "source"])
    ap.add_argument("--papers", required=True)
    ap.add_argument("--arms", default="O,B,L")
    ap.add_argument("--variants", default="clean,err1,err2")
    a = ap.parse_args(argv)
    slugs, arms, variants = a.papers.split(","), a.arms.split(","), a.variants.split(",")
    readers = [r for r in READERS if r[0] in a.readers.split(",")]
    if a.cmd == "quiz-write":
        quiz_write(slugs)
    elif a.cmd == "quiz-run":
        quiz_run(slugs, arms, readers)
    elif a.cmd == "plant":
        plant(slugs)
    elif a.cmd == "err-run":
        err_run(slugs, variants, arms, readers, a.question)
    elif a.cmd == "transplant":
        transplant(slugs, variants, arms)
    elif a.cmd == "err-status":
        err_status(slugs, variants, [x for x in arms if x != "O"])
    elif a.cmd == "pairwise":
        pairwise(slugs, [tuple(p.split(":")) for p in a.pairs.split(",")], [j for j in JUDGES if j[0] in a.judges.split(",")])


if __name__ == "__main__":
    sys.exit(main())
