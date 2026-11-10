You are auditing a rewrite of a mathematical manuscript for fidelity and correctness. The SOURCE is the reference. The REWRITE is supposed to present the same theorems with the same proofs, more readably; it was allowed to reorder, expand steps, add intermediate claims and examples, but not to change any mathematical content.

Do three things.

1. **Statements.** For every theorem, proposition, lemma, corollary and definition in the SOURCE, find its counterpart in the REWRITE and decide whether it is `equivalent`, `changed` (hypotheses, quantifiers, constants or conclusion differ in mathematical content) or `missing`. Only list the ones that are `changed` or `missing`.
2. **Introduced errors.** Read every proof in the REWRITE and check it step by step, paying most attention to material the rewrite added (expanded computations, new intermediate claims, examples, sanity checks, the summary and checklist). List every place where the REWRITE says something mathematically false, makes an inference that does not follow, or misstates what the SOURCE proves, and that is NOT already present in the SOURCE. These are `introduced` problems.
3. **Doubts about the source itself.** If a step is wrong or unjustified in the REWRITE and the same problem is present in the SOURCE, list it under `source_doubts` instead (the rewrite was right to keep it; it should carry an `\unverified{...}` mark). Also list each `\unverified{...}` mark the REWRITE contains and say whether the doubt is warranted.

Be strict about real mathematical problems and silent about style. If you find nothing in a category, return an empty list.

<source>
{{DOC}}
</source>

<rewrite>
{{REWRITE}}
</rewrite>
