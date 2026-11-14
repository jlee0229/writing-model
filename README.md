# writing-model

Rewriting correct-but-opaque AI-generated research mathematics into writeups a mathematician can follow and check, and measuring whether the rewrite is actually better.

Source material: eight manuscripts from OpenAI's October 2026 release ([openai/math](https://github.com/openai/math), 721 manuscripts, self-described as "raw research data, rather than polished academic papers"). All eight have a Lean-checked main result and are 7–15 pages.

This is an overnight proof of concept (10 Nov 2026). Everything was run with Claude models only; no human has yet read the rewrites for this study.

## Result in one screen

Four rewrite variants of each paper, all compiled, all passing two independent fidelity audits:

| variant | what it is | length vs original |
|---|---|---|
| one-shot | one rewrite pass against a fixed style spec | 1.71× |
| located | weak readers report where they got stuck → rewrite → they re-read → revise | 2.17× |
| compact | same spec with a hard cap of 1.25× the original's length | 1.15× |
| compact + reports | compact, with the weak readers' reports used to decide where words go | 1.17× |

What the evaluations say (8 papers; differences are paired by paper with a bootstrap 95% interval over papers):

| measure | original | one-shot | located | compact + reports |
|---|---|---|---|---|
| Comprehension, reader that cannot reason (Haiku 4.5, reasoning off) | 47% | 59% (+12 [+4, +19]) | 66% (+19 [+11, +27]) | 60% (+13 [+5, +21]) |
| … same reader, "why does this step hold" questions only | 51% | 73% | 79% | 73% |
| … same reader, allowed only the first 1,500 words | 19% | 16% | 14% | 18% |
| Comprehension, capable reader (Haiku 5.5, low effort) | 88% | 88% | 90% | 86% |
| Unflagged planted error named, Haiku 5.5 | 81% | 88% | not run | 81% |
| Unflagged planted error named, Sonnet 5.5 | 69% | 58% | not run | 73% |
| Blind pairwise preference vs original (3 judges, both orders) | n/a | 48/48 | 32/32 | 32/32 |

Separately: when a manuscript with one planted error was sent through the one-shot rewriter blind, the rewriter flagged the error in an "Unverified step" box in **8 of 8** cases, and raised no false flag about internal mathematics on the eight clean manuscripts.

Reading of these numbers:

1. **The papers can be improved, and the gain is where you would expect it.** A reader that can only follow what is written answers many more step-justification questions from the rewrite. Judges prefer every rewrite.
2. **The gain disappears for readers who can reconstruct steps themselves**, and it mostly disappears under a fixed reading budget. In 1,500 words the weakest reader gets no further with any rewrite (slightly less far with the longest), and the only reliable gain is +5 points [+2, +8] for Haiku 5.5 on the plain compact variant.
3. **Readability did not make unflagged errors easier to catch.** The trust benefit came from the rewriter acting as a checker, not from readers spotting mistakes.
4. **"Locate, then rewrite" helped only by adding words.** With no length cap, the located variant beat one-shot by +7 points [+2, +12] at 27% more text and twice the cost. Under a length cap, reader reports made no measurable difference (−0 [−7, +7]; judges split 50–56%).
5. **Length is the real constraint for the human study.** The compact variant keeps the whole comprehension gain of the one-shot at 1.15× instead of 1.7×. Use it.

## The papers

`papers/<slug>/original/paper.pdf` is the OpenAI manuscript (recompiled from flattened source); the rewrites sit beside it.

| slug | manuscript | original | one-shot | located | compact + reports |
|---|---|---|---|---|---|
| sensitivity | A superquadratic separation between sensitivity and block sensitivity | [pdf](papers/sensitivity/original/paper.pdf) | [pdf](papers/sensitivity/rewrite-oneshot/paper.pdf) | [pdf](papers/sensitivity/rewrite-located/paper.pdf) | [pdf](papers/sensitivity/rewrite-compact/paper.pdf) |
| groupring | A counterexample to the group-ring determinant conjecture | [pdf](papers/groupring/original/paper.pdf) | [pdf](papers/groupring/rewrite-oneshot/paper.pdf) | [pdf](papers/groupring/rewrite-located/paper.pdf) | [pdf](papers/groupring/rewrite-compact/paper.pdf) |
| talagrand | Talagrand's discrete convexity conjecture | [pdf](papers/talagrand/original/paper.pdf) | [pdf](papers/talagrand/rewrite-oneshot/paper.pdf) | [pdf](papers/talagrand/rewrite-located/paper.pdf) | [pdf](papers/talagrand/rewrite-compact/paper.pdf) |
| seymour | A proof of Seymour's second neighborhood conjecture | [pdf](papers/seymour/original/paper.pdf) | [pdf](papers/seymour/rewrite-oneshot/paper.pdf) | [pdf](papers/seymour/rewrite-located/paper.pdf) | [pdf](papers/seymour/rewrite-compact/paper.pdf) |
| foulkes | Quadratic stabilization of the canonical Foulkes–Howe map | [pdf](papers/foulkes/original/paper.pdf) | [pdf](papers/foulkes/rewrite-oneshot/paper.pdf) | [pdf](papers/foulkes/rewrite-located/paper.pdf) | [pdf](papers/foulkes/rewrite-compact/paper.pdf) |
| kahnkalai | The second Kahn–Kalai conjecture | [pdf](papers/kahnkalai/original/paper.pdf) | [pdf](papers/kahnkalai/rewrite-oneshot/paper.pdf) | [pdf](papers/kahnkalai/rewrite-located/paper.pdf) | [pdf](papers/kahnkalai/rewrite-compact/paper.pdf) |
| projbody | A product counterexample to the simplex maximum for projection-body volume | [pdf](papers/projbody/original/paper.pdf) | [pdf](papers/projbody/rewrite-oneshot/paper.pdf) | [pdf](papers/projbody/rewrite-located/paper.pdf) | [pdf](papers/projbody/rewrite-compact/paper.pdf) |
| thompson | Thompson's group F is nonamenable | [pdf](papers/thompson/original/paper.pdf) | [pdf](papers/thompson/rewrite-oneshot/paper.pdf) | [pdf](papers/thompson/rewrite-located/paper.pdf) | [pdf](papers/thompson/rewrite-compact/paper.pdf) |

Each rewrite opens with the result and a "Proof at a glance", gives every proof as steps with stated justifications, and ends with a verification checklist. The compact variant without reader reports is in `rewrite-compact-noreports/`.

## Method

### Rewrite pipeline (`writing_model/pipeline.py`, prompts in `prompts/`)

```
one-shot   source ─ rewrite ─▶ draft ─ audit ─ (repair, re-audit ≤3×) ─▶ final
located    source ─ 3 weak readers report stuck points ─ rewrite ─▶ draft
                  ─ 3 weak readers re-read ─ revise ─▶ draft ─ audit/repair ─▶ final
compact    one-shot with a hard length cap (± the readers' reports)
```

- Rewriter and first auditor: Claude Fable 5.2, high effort. Second auditor: Claude Opus 5.5, fresh context.
- In-loop weak readers: Claude Haiku 5.5. They report stuck points with a quote, a kind and a severity.
- The rewriter is told the source is believed correct and never sees any evaluation material. It must keep every statement and the proof strategy, and must mark any step it cannot justify with a visible `\unverified{…}` box instead of silently repairing it.
- The audit compares every statement against the source, checks added material step by step, and separates problems the rewrite introduced from doubts about the source itself.

### Evaluation (`writing_model/evalkit.py`, analysis in `writing_model/analyze.py`)

| test | how | who |
|---|---|---|
| Comprehension | 15 short-answer questions per paper (3 gist, 8 step, 4 transfer), written from the **original only** by Opus 5.5; key confirmed by Fable answering open-book twice; a blind grader (Sonnet 5.5) marks answers against required points. Questions a reader can answer closed-book ≥50% of the time are dropped for that reader. | Haiku 4.5 with reasoning off (4 samples), Haiku 5.5 low effort (4 samples); full document and first 1,500 words |
| Planted errors, unflagged | 2 errors per paper planted in the original by Opus 5.5 (each independently validated as a real error by Fable 5.2), then the same error transplanted into each rewrite. Reader is asked whether the proofs contain an error; a grader checks the reader named the planted one. Clean documents give the false-alarm rate. | the two above plus Sonnet 5.5 low effort (3 samples) |
| Planted errors, through the pipeline | The corrupted original goes through the one-shot pipeline blind (1 error per paper). We record whether the rewrite preserved, flagged, repaired or dropped the error. | same |
| Pairwise | Two writeups, both orders, four criteria plus an overall choice. | Haiku 5.5, Sonnet 5.5, Opus 5.5 |

The paper is the unit of analysis. Full tables: [`results/SUMMARY.md`](results/SUMMARY.md); raw rows in `results/*.jsonl`; every model response is cached under `cache/` (kept out of git; `cache.zip` at the repo root holds it, so `unzip cache.zip` lets the scripts replay every call).

## Results in more detail

**Fidelity.** The first audit found a problem in 3 of 8 one-shot rewrites, 3 of 8 located, 1 of 8 compact and 1 of 8 compact + reports (10 findings in all). Seven were in text the rewriter added around the proofs: an overview that dropped a base case, a checklist that overstated where a bound is used, an inaccurate heuristic. Two were inside proofs (a wrong reason given for a boundary case, an aside stated more strongly than the source). One compact rewrite dropped half of a lemma's statement. All were fixed within two repair rounds, so the audit is doing real work and a rewrite should not ship without it. The second-model audit of the final one-shot and compact + reports rewrites found no changed statement and no introduced error in any of the 16. No human and no Lean check has been run on the rewrites.

**Flags on clean papers.** The rewriter raised "Unverified step" boxes on three clean papers. All are dependency notes, not doubts about internal steps: the group-ring paper's main theorem rests entirely on a companion manuscript's counterexample to Kaplansky's direct-finiteness conjecture; two corollaries of the Thompson-group paper and one of the Talagrand paper are proved only by citing other manuscripts. That is useful to a reader deciding what to trust.

**Flags are under-read.** When readers of a flagged rewrite were asked whether the *original* proof had an error, only 38% (Haiku 4.5), 56% (Haiku 5.5) and 42% (Sonnet 5.5) named it. The rewriter typically wrote "as written this is false; with the corrected statement every step checks", and readers treated that as a resolved slip. One label for both "cannot check this" and "the source is wrong here" is a design flaw.

**Pairwise judging does not discriminate.** Every rewrite beat every original, unanimously, while every judge also rated the original as more economical. Between rewrites the judges prefer the longer one (one-shot over compact 81–88%) and show a strong position effect in close calls (the first-shown writeup won only 6–31% of the time), so both orders are essential.

**The in-loop signal does not converge.** Weak readers' self-reported stuck load went from 13.1 to 11.3 after the first located rewrite and fell in 6 of 8 papers, but readers always find about ten things to report, nearly all severity 1 ("I reconstructed it, but the text leaves it implicit"). It works as a list of edit suggestions. It is not a readability score.

**Reader effort.** Haiku 5.5 spent about 9–13% fewer output tokens answering from the one-shot and located rewrites than from the original (7,708 → 7,042 and 6,678). The compact variants gave a similar 7–9% saving.

## Where this pushes back on the plan

1. **"Weaker reader models" are not weak in the way the plan needs.** Haiku 5.5 at low effort answers 88% of step-level questions from the *original* and catches 81% of planted errors. It reconstructs what the text omits, so its score barely moves when the text improves. A model with reasoning switched off does respond to the text, but it catches 0% of planted errors, so it cannot stand in for a checker. No single reader model gave a signal that tracks both comprehension and error-catching.
2. **Multiple-choice comprehension tests are useless here.** Readers scored 95–100% without the paper. Free-response questions with a closed-book floor check fixed that (0% closed-book for the weakest reader).
3. **"Models can't find errors but can fix them once located" (Tyen et al.) no longer holds at this level.** The rewriter found all eight planted errors without being asked to look. The more valuable loop may be rewrite-as-verification, with weak readers used to test whether flags and explanations land.
4. **More legible is not the same as more checkable.** Sonnet's detection of unflagged errors fell from 69% to 58% on the one-shot rewrites (interval [−35, +15], so not established). The direction matches the human literature on fluent explanations increasing reliance without improving accuracy. The human study should measure this directly.
5. **The honest length-controlled effect is the one to report.** At 1.15× length the rewrite still gains 13 points for the weakest reader and loses nothing for the others.

## Prior art

Checked by web search on 10 Nov 2026. A background research agent was interrupted early in the session, so this list is shorter than intended.

- **Legibility training.** Kirchner et al., "Prover-Verifier Games improve legibility of LLM outputs", [arXiv:2407.13692](https://arxiv.org/abs/2407.13692) (2024). Trains provers against small verifiers, with "sneaky" provers planting errors; legibility transfers to time-constrained humans on grade-school maths, at a cost in accuracy. The closest ancestor of this plan. Differences: research-level proofs, rewriting a fixed correct proof instead of solving, and no training yet.
- **Error localisation.** Tyen et al., "LLMs cannot find reasoning errors, but can correct them given the error location", [arXiv:2311.08516](https://arxiv.org/abs/2311.08516) (Findings of ACL 2024). The premise of locate-then-rewrite; measured on 2023 models.
- **Proof-verification benchmarks.** Hard2Verify, [arXiv:2510.13744](https://arxiv.org/abs/2510.13744) (2025; ACL 2026): step-level verification of frontier-model proofs. Reports that verifiers often accept under-justified steps.
- **Measuring proof comprehension in people.** Mejía-Ramos et al., "An assessment model for proof comprehension in undergraduate mathematics", [Educ. Stud. Math. 79 (2012)](https://link.springer.com/doi/10.1007/s10649-011-9349-7), which motivates the gist/step/transfer split used here; Hodds, Alcock and Inglis, "Self-explanation training improves proof comprehension", [JRME 45(1), 2014](https://dspace.lboro.ac.uk/2134/13603) (d = 0.95). Recalled but not re-verified today: Alcock and colleagues' "e-Proofs" did not improve, and on a delayed test worsened, comprehension compared with a plain proof. If that holds, format changes alone are a weak lever for humans.
- **Over-trust in fluent explanations.** Cohen et al., "The Persuasion Paradox", [arXiv:2604.03237](https://www.alphaxiv.org/abs/2604.03237) (2026); Kim et al., [arXiv:2502.08554](https://arxiv.org/abs/2502.08554) (CHI 2025). Explanations raise confidence and reliance, including on wrong answers.
- **Judge bias.** Panickssery, Bowman and Feng, "LLM Evaluators Recognize and Favor Their Own Generations", [arXiv:2404.13076](https://arxiv.org/abs/2404.13076) (NeurIPS 2024). All judges here are in the same model family as the rewriter.
- **Lean to prose.** Hattori et al. (INLG 2025) informalise Lean proofs step by step; HERALD, [arXiv:2410.10878](https://arxiv.org/abs/2410.10878); "Explorable Theorems", [arXiv:2604.02598](https://alphaxiv.org/abs/2604.02598) (2026) links a written proof to Lean so readers can step through it. None of these found targets AI-written research manuscripts.
- **The release itself.** [Wikipedia summary](https://en.wikipedia.org/wiki/OpenAI_bulk_release_of_mathematical_papers): one manuscript was called "so horribly written that it's impossible to read it without AI help" (Dana Moshkovitz); some Lean formalisations reportedly prove weaker statements than the papers claim; a human audit of ten earlier results is at [arXiv:2608.14673](https://arxiv.org/abs/2608.14673). I found no existing project that systematically rewrites the release.

What looks open: a rewriter for AI-written research proofs evaluated on reader behaviour instead of preference; length-controlled comparisons; any link between reader-model scores and human readers at research level.

## Limitations

- **No human data.** Every reader, judge, grader and auditor is a Claude model, and the rewriter is too. Same-family preference could inflate the pairwise result and possibly comprehension.
- **Eight papers,** chosen to be short, Lean-verified and accessible. Intervals are wide. The 104-page manuscripts in the release are a different problem.
- **The weakest reader is an older model with reasoning off,** not a person with limited time.
- **Planted errors are synthetic** and of middling subtlety. Transplanting an error into a rewrite requires writing a flawed justification, which may make it more or less detectable than a natural mistake.
- **Fidelity rests on two model audits.** The obvious stronger check, comparing each rewrite's main statement against the Lean statement, is not done.
- **The "8 of 8 flagged" result has no direct baseline.** Fable was not asked simply to find the error in the original. Haiku 5.5 found 84% of the same eight when asked.
- **The reading-budget test truncates at a word count,** a crude stand-in for limited time.
- Sonnet answered the quiz on only the two pilot papers (it was at ceiling), so it is left out of the quiz tables.

## Next steps

1. **Human pilot before any training.** Five to ten readers, compact + reports vs original, fixed time. Measure step-question accuracy, time to criterion, and detection of an unflagged planted error. This also tests whether any reader model predicts human scores.
2. **Typed flags and a front-page trust summary**: "source error, corrected here" vs "depends on an unchecked external result". Re-run the flag-reading test.
3. **Anchor to Lean.** Check each rewrite's theorem statement against the Lean statement; where a paper says "clearly", mine the Lean proof for the missing step.
4. **Behavioural localisation.** Replace self-reported stuck points with step-justification probes answered by the non-reasoning reader, and spend the length budget where it fails.
5. **Adversarial arm.** A rewriter told to make a flawed proof convincing, to measure how much legibility can hide.
6. Only then, distil the pipeline into a trained rewriter with reader behaviour as the reward.

## Reproduce

Requires Python 3.11+, a LaTeX toolchain with `latexmk`, and the Claude Code CLI (`claude`) logged in. All model calls go through `writing_model/llm.py`, which shells out to `claude -p` and caches every response. Run `unzip cache.zip` first and re-running replays the recorded responses instead of spending tokens.

```bash
python scripts/vendor_papers.py /path/to/clone/of/openai-math
python -m writing_model.pipeline --papers foulkes --variants clean --arms B,L,C,C0
python -m writing_model.evalkit quiz-write --papers foulkes
python -m writing_model.evalkit quiz-run --papers foulkes --arms O,B,L,C,C0 --readers novice,weak
python -m writing_model.evalkit plant --papers foulkes
python -m writing_model.evalkit transplant --papers foulkes --variants err1,err2 --arms B,C
python -m writing_model.evalkit err-run --papers foulkes --variants clean,err1,err2,err1t,err2t --arms O,B,C
python -m writing_model.evalkit pairwise --papers foulkes --pairs O:B,O:C,B:C
python -m writing_model.analyze
```

Arm codes: `O` original, `B` one-shot, `L` located, `C0` compact, `C` compact + reports.

## Cost and licence

The run made 3,803 model calls, about $470 at list prices (Fable 5.2 $278, Sonnet 5.5 $80, Opus 5.5 $70, Haiku 4.5 $34, Haiku 5.5 $8). A one-shot rewrite with audit costs roughly $4–5 per paper; the located variant about $8.

The manuscripts under `papers/*/original` and everything derived from them are from [openai/math](https://github.com/openai/math), Apache-2.0 (`papers/LICENSE-openai-math`); the rewrites are modified versions of those works.
