"""Aggregate evaluation results into results/summary.json and results/SUMMARY.md.

The unit of analysis is the paper (or the planted-error instance). For each
(reader, condition) we compute a per-paper score, then report the mean over
papers, the paired difference between arms, a bootstrap 95% interval over
papers, and how many papers moved in each direction.

    python -m legible.analyze
"""
from __future__ import annotations

import json
import random
from collections import Counter, defaultdict

from .evalkit import RES, read_rows
from .llm import ROOT

ARMS = ["O", "B", "L", "C0", "C"]
ARM_NAME = {"O": "original", "B": "one-shot", "L": "located (2 rounds)", "C0": "compact, no reports", "C": "compact, located"}
READERS = ["novice", "weak", "mid"]
READER_NAME = {"novice": "Haiku 4.5, reasoning off", "weak": "Haiku 5.5, low effort", "mid": "Sonnet 5.5, low effort",
               "infra": "Opus 5.5"}
PAIRS = [("O", "B"), ("O", "L"), ("O", "C0"), ("O", "C"), ("B", "L"), ("C0", "C"), ("B", "C")]


def mean(xs):
    xs = list(xs)
    return sum(xs) / len(xs) if xs else float("nan")


def boot_ci(diffs, n=10000, seed=0):
    """95% bootstrap interval for the mean of paired differences (resampling papers)."""
    if len(diffs) < 2:
        return [float("nan"), float("nan")]
    rng = random.Random(seed)
    ms = sorted(mean(rng.choice(diffs) for _ in diffs) for _ in range(n))
    return [ms[int(0.025 * n)], ms[int(0.975 * n)]]


def paired(per_unit: dict, a: str, b: str):
    """per_unit[unit][arm] -> score. Stats for arm b minus arm a over units that have both."""
    units = [u for u in per_unit if a in per_unit[u] and b in per_unit[u]]
    if not units:
        return None
    diffs = [per_unit[u][b] - per_unit[u][a] for u in units]
    return {"n": len(units), "a": mean(per_unit[u][a] for u in units), "b": mean(per_unit[u][b] for u in units),
            "diff": mean(diffs), "ci95": boot_ci(diffs),
            "up": sum(d > 1e-9 for d in diffs), "down": sum(d < -1e-9 for d in diffs),
            "per_unit": {str(u): round(per_unit[u][b] - per_unit[u][a], 3) for u in units}}


def all_pairs(per_unit):
    return {f"{b}-{a}": p for a, b in PAIRS if (p := paired(per_unit, a, b))}


def arm_means(per_unit):
    """Mean per arm over the units that have every arm present in the data (so columns are comparable)."""
    arms = [a for a in ARMS if any(a in d for d in per_unit.values())]
    full = [u for u, d in per_unit.items() if all(a in d for a in arms)]
    return {"n_units": len(full), **{a: mean(per_unit[u][a] for u in full) for a in arms}}


# ---------------------------------------------------------------- quiz
def quiz_tables():
    rows = read_rows(RES / "quiz_answers.jsonl")
    quizzes = {p.stem: {str(q["id"]): q for q in json.loads(p.read_text())["questions"]} for p in (RES / "quiz").glob("*.json")}
    out = {}
    for reader in READERS:
        for budget in (None, 1500):
            for qtype in ("all", "gist", "step", "transfer"):
                cell = defaultdict(lambda: defaultdict(list))
                for r in rows:
                    if r["reader"] != reader or r["budget"] != budget:
                        continue
                    for qid, c in r["correct"].items():
                        q = quizzes[r["slug"]][qid]
                        if q.get(f"closed_book_{reader}", 0) >= 0.5:
                            continue  # this reader can answer it without the paper
                        if qtype != "all" and q["type"] != qtype:
                            continue
                        cell[r["slug"]][r["arm"]].append(c)
                per_paper = {s: {a: mean(v) for a, v in d.items()} for s, d in cell.items()}
                if per_paper:
                    out[f"{reader}|{budget or 'full'}|{qtype}"] = {"means": arm_means(per_paper), "pairs": all_pairs(per_paper)}
    # reader effort: output tokens (almost all reasoning) spent answering the full-document quiz
    effort = {}
    for reader in READERS:
        per = defaultdict(lambda: defaultdict(list))
        for r in rows:
            if r["reader"] == reader and r["budget"] is None:
                per[r["slug"]][r["arm"]].append(r["usage"]["output"])
        pp = {s: {a: mean(v) for a, v in d.items()} for s, d in per.items()}
        if pp:
            effort[reader] = {"means": arm_means(pp)}
    floors = {s: {r: mean(q.get(f"closed_book_{r}", 0) for q in qs.values()) for r in READERS} for s, qs in quizzes.items()}
    return out, effort, floors


# ---------------------------------------------------------------- errors
def error_tables():
    rows = read_rows(RES / "error_answers.jsonl")
    status = {(r["slug"], r["variant"], r["arm"]): r["status"] for r in read_rows(RES / "error_status.jsonl")}
    out = {"status": {}, "false_alarm": {}, "unflagged": {}, "pipeline": {}}
    c = defaultdict(Counter)
    for (s, v, a), st in status.items():
        c[f"{a} {'transplanted' if v.endswith('t') else 'through pipeline'}"][st] += 1
    out["status"] = {k: dict(v) for k, v in c.items()}
    for reader in READERS:
        R = [r for r in rows if r["reader"] == reader]
        doc_q = [r for r in R if r.get("question", "doc") == "doc"]
        src_q = [r for r in R if r.get("question") == "source"]
        # false alarms on clean documents
        fa = defaultdict(lambda: defaultdict(list))
        for r in doc_q:
            if r["variant"] == "clean":
                fa[r["slug"]][r["arm"]].append(int(r["verdict"] == "error"))
        fa = {s: {a: mean(v) for a, v in d.items()} for s, d in fa.items()}
        out["false_alarm"][reader] = {"means": arm_means(fa), "pairs": all_pairs(fa)}
        # unflagged error present in the document: original (err1, err2) vs transplanted rewrites (err1t, err2t)
        det = defaultdict(lambda: defaultdict(list))
        for r in doc_q:
            v = r["variant"]
            if v in ("err1", "err2") and r["arm"] == "O":
                det[(r["slug"], v)]["O"].append(int(r["hit_rank"] >= 1))
            elif v in ("err1t", "err2t") and status.get((r["slug"], v, r["arm"])) == "preserved":
                det[(r["slug"], v[:-1])][r["arm"]].append(int(r["hit_rank"] >= 1))
        det = {u: {a: mean(v) for a, v in d.items()} for u, d in det.items()}
        out["unflagged"][reader] = {"means": arm_means(det), "pairs": all_pairs(det),
                                    "per_instance": {f"{s}/{v}": {a: round(x, 2) for a, x in d.items()} for (s, v), d in sorted(det.items())}}
        # error went through the rewrite pipeline blind (err1): does the reader end up knowing the source's flaw?
        pipe = defaultdict(lambda: defaultdict(list))
        for r in doc_q:
            if r["variant"] == "err1" and r["arm"] == "O":
                pipe[r["slug"]]["O"].append(int(r["hit_rank"] >= 1))
            if r["variant"] == "err1" and r["arm"] != "O":
                pipe[r["slug"]][r["arm"] + " (asked about the rewrite's own proofs)"].append(int(r["hit_rank"] >= 1))
        for r in src_q:
            if r["variant"] == "err1":
                pipe[r["slug"]][r["arm"] + " (asked about the original's proof)"].append(int(r["hit_rank"] >= 1))
        pipe = {s: {a: mean(v) for a, v in d.items()} for s, d in pipe.items()}
        keys = sorted({k for d in pipe.values() for k in d})
        full = [s for s, d in pipe.items() if all(k in d for k in keys)]
        fa_src = defaultdict(list)
        for r in src_q:
            if r["variant"] == "clean":
                fa_src[r["arm"]].append(int(r["verdict"] == "error"))
        out["pipeline"][reader] = {"n_papers": len(full), "means": {k: mean(pipe[s][k] for s in full) for k in keys},
                                   "false_alarm_about_original_on_clean": {a: mean(v) for a, v in fa_src.items()}}
    return out


# ---------------------------------------------------------------- pairwise
def pairwise_tables():
    rows = read_rows(RES / "pairwise.jsonl")
    out = {}
    for x, y in sorted({(r["x"], r["y"]) for r in rows}, key=lambda p: (ARMS.index(p[0]), ARMS.index(p[1]))):
        for judge in ("weak", "mid", "infra"):
            rs = [r for r in rows if r["judge"] == judge and (r["x"], r["y"]) == (x, y)]
            if not rs:
                continue
            per_paper = defaultdict(list)
            for r in rs:
                per_paper[r["slug"]].append(int(r["overall"] == y))
            crit = {c: {"y": sum(r[c] == y for r in rs), "x": sum(r[c] == x for r in rs), "tie": sum(r[c] == "tie" for r in rs)}
                    for c in ("orientation", "checkability", "notation", "economy")}
            first = mean(int(r["overall"] == (r["x"] if r["order"] == 0 else r["y"])) for r in rs)
            out[f"{y} vs {x}|{judge}"] = {
                "n": len(rs), "win_rate_y": mean(int(r["overall"] == y) for r in rs),
                "papers_y_both_orders": sum(all(v) for v in per_paper.values()),
                "papers_x_both_orders": sum(not any(v) for v in per_paper.values()),
                "papers_split": sum(any(v) and not all(v) for v in per_paper.values()),
                "criteria": crit, "first_position_win_rate": first}
    return out


# ---------------------------------------------------------------- documents
def docs_table():
    out = {}
    index = json.loads((ROOT / "papers" / "index.json").read_text())
    for slug in index:
        row = {"title": index[slug]["title"], "source_words": index[slug]["words"],
               "lean_main_result": index[slug]["lean_formalized_main_result"]}
        for arm in ARMS[1:]:
            d = ROOT / "runs" / slug / "clean" / arm
            if (d / "meta.json").exists():
                m = json.loads((d / "meta.json").read_text())
                row[arm] = {k: m.get(k) for k in ("length_ratio", "rewrite_words", "repaired", "repair_rounds", "compiles",
                                                    "unverified_marks", "audit1", "final_audit", "stuck_load_source", "stuck_load_draft1")}
                if (d / "audit_second_model.json").exists():
                    a = json.loads((d / "audit_second_model.json").read_text())
                    row[arm]["second_audit"] = {k: len(v) for k, v in a.items()}
        out[slug] = row
    return out


def inloop_signal(docs):
    """Weak readers' self-reported stuck load (severity-weighted issues per reader): source vs first located draft."""
    rows = {s: (d["L"]["stuck_load_source"], d["L"]["stuck_load_draft1"]) for s, d in docs.items()
            if "L" in d and d["L"].get("stuck_load_source") is not None}
    return {"per_paper": {s: [round(a, 1), round(b, 1)] for s, (a, b) in rows.items()},
            "mean_source": mean(a for a, b in rows.values()), "mean_first_draft": mean(b for a, b in rows.values()),
            "papers_where_it_fell": sum(b < a for a, b in rows.values()), "n": len(rows)}


def cost_table():
    c = defaultdict(lambda: [0, 0.0])
    p = RES / "usage.jsonl"
    for r in read_rows(p):
        c[r["model"]][0] += 1
        c[r["model"]][1] += r["cost"]
    return {m: {"calls": n, "list_price_usd": round(x, 2)} for m, (n, x) in c.items()}


# ---------------------------------------------------------------- report
def pct(x):
    return "–" if x is None or x != x else f"{100 * x:.0f}%"


def dstr(p):
    if not p:
        return "–"
    return f"{100 * p['diff']:+.0f} [{100 * p['ci95'][0]:+.0f}, {100 * p['ci95'][1]:+.0f}] ({p['up']}↑ {p['down']}↓ / {p['n']})"


def main():
    docs = docs_table()
    quiz, effort, floors = quiz_tables()
    errors = error_tables()
    pw = pairwise_tables()
    summary = {"documents": docs, "quiz": quiz, "quiz_reader_output_tokens": effort, "quiz_closed_book_floor": floors,
               "errors": errors, "pairwise": pw, "inloop_stuck_load": inloop_signal(docs), "cost": cost_table()}
    (RES / "summary.json").write_text(json.dumps(summary, indent=1, ensure_ascii=False))

    L = ["# Results (auto-generated by `python -m legible.analyze`)", "",
         "Differences are in percentage points: mean paired difference over papers, bootstrap 95% interval over papers, "
         "and (papers up ↑ / down ↓ / total).", ""]
    L += ["## Documents", "", "| paper | source words | length ×: one-shot | located | compact-no-reports | compact-located | audit problems found → left (B, L, C0, C) | second-model audit problems (B, C) | \"unverified\" marks (B, L, C0, C) |", "|---|---|---|---|---|---|---|---|---|"]
    for s, d in docs.items():
        def aud(a):
            if a not in d:
                return "–"
            a1, a2 = d[a]["audit1"], d[a]["final_audit"]
            return f"{a1['statements'] + a1['introduced']}→{a2['statements'] + a2['introduced']}"

        def aud2(a):
            x = d.get(a, {}).get("second_audit")
            return "–" if not x else str(x["statements"] + x["introduced"])
        L.append(f"| {s} | {d['source_words']} | " + " | ".join(str(d.get(a, {}).get("length_ratio", "–")) for a in ARMS[1:])
                 + f" | {', '.join(aud(a) for a in ARMS[1:])} | {aud2('B')}, {aud2('C')} | {', '.join(str(d.get(a, {}).get('unverified_marks', '–')) for a in ARMS[1:])} |")

    L += ["", "## Comprehension quiz", "", "Accuracy on short-answer questions written from the original only; a blind grader marks answers against the key. "
          "Questions a reader can answer without the paper (closed-book rate ≥ 50%) are excluded for that reader.", "",
          "| reader | reading budget | " + " | ".join(ARM_NAME[a] for a in ARMS) + " | one-shot − original | located − original | compact-located − original | located − one-shot | compact-located − compact-no-reports |", "|---|---|" + "---|" * (len(ARMS) + 5)]
    for reader in READERS:
        for budget in ("full", "1500"):
            v = quiz.get(f"{reader}|{budget}|all")
            if not v:
                continue
            m, p = v["means"], v["pairs"]
            if m["n_units"] < 8:
                continue  # Sonnet read only the two pilot papers; kept in summary.json, left out of the table
            L.append(f"| {READER_NAME[reader]} | {budget} | " + " | ".join(pct(m.get(a)) for a in ARMS) + f" | {dstr(p.get('B-O'))} | {dstr(p.get('L-O'))} | {dstr(p.get('C-O'))} | {dstr(p.get('L-B'))} | {dstr(p.get('C-C0'))} |")
    L += ["", "By question type, full document, difference from the original:", "", "| reader | arm | gist | step | transfer |", "|---|---|---|---|---|"]
    for reader in ("novice", "weak"):
        for arm in ("B", "L", "C"):
            cells = [dstr(quiz.get(f"{reader}|full|{t}", {}).get("pairs", {}).get(f"{arm}-O")) for t in ("gist", "step", "transfer")]
            L.append(f"| {READER_NAME[reader]} | {ARM_NAME[arm]} | " + " | ".join(cells) + " |")
    L += ["", "Reader output tokens (mostly reasoning) per full-document quiz attempt:", "", "| reader | " + " | ".join(ARM_NAME[a] for a in ARMS) + " |", "|---|" + "---|" * len(ARMS)]
    for reader, v in effort.items():
        if v["means"]["n_units"] < 8:
            continue
        L.append(f"| {READER_NAME[reader]} | " + " | ".join(f"{v['means'].get(a, float('nan')):.0f}" for a in ARMS) + " |")

    s = summary["inloop_stuck_load"]
    L += ["", "## In-loop signal", "", f"Weak readers' self-reported stuck load (severity-weighted issues per reader) on the source vs on the first located draft: "
          f"{s['mean_source']:.1f} → {s['mean_first_draft']:.1f} on average; it fell in {s['papers_where_it_fell']} of {s['n']} papers. Per paper: `{json.dumps(s['per_paper'])}`"]
    L += ["", "## Planted errors", "", f"Fate of each planted error inside a rewrite: `{json.dumps(errors['status'])}`", "",
          "### (a) Error present and unflagged in the document", "",
          "Share of reads in which the reader names the planted error (16 instances: 2 errors × 8 papers; rewrites carry the same error, transplanted).", "",
          "| reader | original | one-shot | compact-located | one-shot − original | compact-located − original |", "|---|---|---|---|---|---|"]
    for reader in READERS:
        v = errors["unflagged"][reader]
        L.append(f"| {READER_NAME[reader]} | {pct(v['means'].get('O'))} | {pct(v['means'].get('B'))} | {pct(v['means'].get('C'))} | {dstr(v['pairs'].get('B-O'))} | {dstr(v['pairs'].get('C-O'))} |")
    L += ["", "False alarms (reader says a clean document contains an error):", "", "| reader | " + " | ".join(ARM_NAME[a] for a in ("O", "B", "C")) + " |", "|---|---|---|---|"]
    for reader in READERS:
        m = errors["false_alarm"][reader]["means"]
        L.append(f"| {READER_NAME[reader]} | " + " | ".join(pct(m.get(a)) for a in ("O", "B", "C")) + " |")
    L += ["", "### (b) Error goes through the rewrite pipeline blind (one error per paper)", "",
          "| reader | names the error reading the corrupted original | reading the rewrite, asked about the rewrite's proofs | reading the rewrite, asked about the original's proof | false alarm about the original on clean rewrites |", "|---|---|---|---|---|"]
    for reader in READERS:
        v = errors["pipeline"][reader]
        m = v["means"]
        own, orig = m.get("B (asked about the rewrite's own proofs)"), m.get("B (asked about the original's proof)")
        fa_o = v["false_alarm_about_original_on_clean"].get("B")
        L.append(f"| {READER_NAME[reader]} | {pct(m.get('O'))} | {pct(own)} | {pct(orig)} | {pct(fa_o)} |")

    L += ["", "## Blind pairwise preference", "", "| comparison | judge | preferred | papers: both orders / split / neither | first-shown wins | orientation | checkability | notation | economy |", "|---|---|---|---|---|---|---|---|---|"]
    for key, v in pw.items():
        comp, judge = key.split("|")
        y, x = comp.split(" vs ")
        c = v["criteria"]
        L.append(f"| {ARM_NAME[y]} vs {ARM_NAME[x]} | {READER_NAME[judge]} | {ARM_NAME[y]} {pct(v['win_rate_y'])} | {v['papers_y_both_orders']} / {v['papers_split']} / {v['papers_x_both_orders']} | {pct(v['first_position_win_rate'])} | "
                 + " | ".join(f"{c[k]['y']}–{c[k]['x']} ({c[k]['tie']} tie)" for k in ("orientation", "checkability", "notation", "economy")) + " |")
    L += ["", "## Spend (list-price equivalent)", "", "| model | calls | USD |", "|---|---|---|"]
    for m, v in sorted(summary["cost"].items(), key=lambda kv: -kv[1]["list_price_usd"]):
        L.append(f"| {m} | {v['calls']} | {v['list_price_usd']:.0f} |")
    L.append(f"| total | {sum(v['calls'] for v in summary['cost'].values())} | {sum(v['list_price_usd'] for v in summary['cost'].values()):.0f} |")
    (RES / "SUMMARY.md").write_text("\n".join(L) + "\n")
    print("\n".join(L))


if __name__ == "__main__":
    main()
