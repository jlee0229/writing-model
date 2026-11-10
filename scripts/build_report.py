"""Build report/index.html (the shareable results page) from results/summary.json.

    python scripts/build_report.py
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
S = json.loads((ROOT / "results" / "summary.json").read_text())
DOCS = S["documents"]
ARMS = ["O", "B", "L", "C0", "C"]
ARM = {"O": "Original", "B": "One-shot", "L": "Located", "C0": "Compact", "C": "Compact + reports"}
READER = {"novice": "Haiku 4.5, reasoning off", "weak": "Haiku 5.5, low effort", "mid": "Sonnet 5.5, low effort", "infra": "Opus 5.5"}


def pct(x):
    return "–" if x is None or x != x else f"{100 * x:.0f}%"


def delta(p):
    if not p:
        return ""
    d, (lo, hi) = 100 * p["diff"], [100 * v for v in p["ci95"]]
    cls = "up" if lo > 0 else "down" if hi < 0 else "flat"
    return f'<span class="delta {cls}">{d:+.0f} <span class="ci">[{lo:+.0f}, {hi:+.0f}]</span></span>'


def cell(mean, p=None):
    return f"<td>{pct(mean)}{delta(p)}</td>"


def quiz_rows():
    out = []
    for reader in ("novice", "weak"):
        for budget, label in (("full", "whole paper"), ("1500", "first 1,500 words")):
            v = S["quiz"][f"{reader}|{budget}|all"]
            m, p = v["means"], v["pairs"]
            out.append(f"<tr><th scope='row'>{READER[reader]}<span class='sub'>{label}</span></th>"
                       + cell(m["O"]) + "".join(cell(m[a], p.get(f"{a}-O")) for a in ARMS[1:]) + "</tr>")
    v = S["quiz"]["novice|full|step"]
    out.append("<tr><th scope='row'>Haiku 4.5, reasoning off<span class='sub'>whole paper, step questions only</span></th>"
               + cell(v["means"]["O"]) + "".join(cell(v["means"][a], v["pairs"].get(f"{a}-O")) for a in ARMS[1:]) + "</tr>")
    return "\n".join(out)


def error_rows():
    out = []
    for reader in ("novice", "weak", "mid"):
        u = S["errors"]["unflagged"][reader]
        fa = S["errors"]["false_alarm"][reader]["means"]
        out.append(f"<tr><th scope='row'>{READER[reader]}</th>{cell(u['means']['O'])}{cell(u['means']['B'], u['pairs'].get('B-O'))}"
                   f"{cell(u['means']['C'], u['pairs'].get('C-O'))}<td>{pct(fa['O'])} / {pct(fa['B'])} / {pct(fa['C'])}</td></tr>")
    return "\n".join(out)


def pipeline_rows():
    out = []
    for reader in ("novice", "weak", "mid"):
        v = S["errors"]["pipeline"][reader]["means"]
        out.append(f"<tr><th scope='row'>{READER[reader]}</th><td>{pct(v['O'])}</td>"
                   f"<td>{pct(v[chr(66) + ' (asked about the original' + chr(39) + 's proof)'])}</td></tr>")
    return "\n".join(out)


def pair_rows():
    out = []
    names = {"B vs O": "One-shot vs original", "L vs O": "Located vs original", "C vs O": "Compact + reports vs original",
             "L vs B": "Located vs one-shot", "C vs B": "Compact + reports vs one-shot", "C vs C0": "Compact + reports vs compact"}
    for comp, label in names.items():
        ks = [k for k in S["pairwise"] if k.startswith(comp + "|")]
        if not ks:
            continue
        n = sum(S["pairwise"][k]["n"] for k in ks)
        wins = sum(round(S["pairwise"][k]["win_rate_y"] * S["pairwise"][k]["n"]) for k in ks)
        crit = {c: [sum(S["pairwise"][k]["criteria"][c][s] for k in ks) for s in ("y", "x", "tie")] for c in ("orientation", "checkability", "notation", "economy")}
        first = sum(S["pairwise"][k]["first_position_win_rate"] * S["pairwise"][k]["n"] for k in ks) / n
        out.append(f"<tr><th scope='row'>{label}<span class='sub'>{len(ks)} judges, both orders</span></th><td>{wins} of {n}</td>"
                   + "".join(f"<td>{a}–{b}<span class='sub'>{t} tie</span></td>" for a, b, t in crit.values()) + f"<td>{pct(first)}</td></tr>")
    return "\n".join(out)


def doc_rows():
    out = []
    for slug, d in DOCS.items():
        def aud(a):
            a1 = d[a]["audit1"]
            return a1["statements"] + a1["introduced"]
        out.append(f"<tr><th scope='row'>{d['title']}</th><td>{d['source_words']:,}</td>"
                   + "".join(f"<td>{d[a]['length_ratio']:.2f}×</td>" for a in ARMS[1:])
                   + f"<td>{aud('B')} / {aud('L')} / {aud('C0')} / {aud('C')}</td><td>{d['B']['unverified_marks']}</td></tr>")
    return "\n".join(out)


def papers_json():
    return json.dumps([{"slug": s, "title": d["title"], "words": d["source_words"],
                        "ratio": {a: d[a]["length_ratio"] for a in ARMS[1:]}} for s, d in DOCS.items()])


q = S["quiz"]["novice|full|all"]
cost = sum(v["list_price_usd"] for v in S["cost"].values())
calls = sum(v["calls"] for v in S["cost"].values())
html = (ROOT / "report" / "template.html").read_text()
for key, val in {
    "QUIZ_ROWS": quiz_rows(), "ERROR_ROWS": error_rows(), "PIPELINE_ROWS": pipeline_rows(), "PAIR_ROWS": pair_rows(),
    "DOC_ROWS": doc_rows(), "PAPERS_JSON": papers_json(), "COST": f"{cost:,.0f}", "CALLS": f"{calls:,}",
    "N_O": pct(q["means"]["O"]), "N_B": pct(q["means"]["B"]), "N_L": pct(q["means"]["L"]), "N_C": pct(q["means"]["C"]),
}.items():
    html = html.replace("{{" + key + "}}", val)
assert "{{" not in html, html[html.index("{{"):][:80]
(ROOT / "report" / "index.html").write_text(html)
print("wrote report/index.html", len(html), "bytes")
