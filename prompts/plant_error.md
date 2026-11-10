You are building a test of whether readers can catch a mistake in a proof. The manuscript below is correct. Produce {{K}} corrupted variants, each with exactly one planted mathematical error inside a proof. Do not touch the abstract, the introduction or the statement of the main theorem.

Each planted error must be:

- **Substantive.** After the edit, the affected step is false or does not follow, so a careful verifier who checks that step would reject the proof as written. An edit that leaves the step true, or weaker but still sufficient, is not acceptable.
- **Natural.** The kind of slip a person or a model makes while writing a proof: an inequality that goes the wrong way or drops a factor, a quantifier or hypothesis dropped or swapped, a lemma applied where its hypothesis fails, a miscounted case, an index or exponent off by one, an invalid interchange. Not a typo, and not something absurd on its face.
- **Clean on the surface.** Make at most three small edits, and propagate the consequence just enough that the surrounding sentences do not contradict the edited claim outright. Do not rewrite more than necessary.
- **Load-bearing and spread out.** Each variant's error sits in a step the main result depends on, and the variants differ in kind and are in different lemmas or sections.

Give each variant as a list of exact find/replace edits on the LaTeX source. Each `find` must be a verbatim substring of the manuscript that occurs exactly once (include enough context to make it unique, but keep it short). Also give `where` (lemma/section), `kind`, `explanation` (what is now wrong and why; this is for the grader), and `correct_version` (what the text said or should say).

<manuscript>
{{DOC}}
</manuscript>
