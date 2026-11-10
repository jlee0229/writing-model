Below is a research manuscript (LaTeX source). Read it from start to finish the way a referee checking correctness would, trying to verify each step yourself.

Then report every place where you personally could not follow or could not verify the text. Be concrete and honest. Do not give generic style advice, and do not claim to understand a step you could not actually justify. Kinds of trouble:

- `unjustified_step`: a claim or inference whose justification you could not reconstruct from what was written before it
- `undefined_notation`: a symbol or term used before (or without) a definition, or reused with a different meaning
- `lost_thread`: you could not tell why something is being proved, or how it is used later
- `ambiguous_statement`: a statement whose quantifiers, hypotheses or meaning are unclear
- `heavy_computation`: a calculation with skipped intermediate steps that you could not redo quickly
- `suspected_error`: something that looks false or inconsistent to you

For each issue give:
- `where`: section / lemma / equation it occurs in
- `quote`: a verbatim excerpt of at most 25 words from the manuscript, so the place can be found
- `kind`: one of the kinds above
- `severity`: 1, 2 or 3 (3 = I could not continue verifying the proof past this point)
- `what_i_needed`: the explanation, definition or intermediate step that would have let you verify it

Also give:
- `main_result`: the main theorem in your own words
- `proof_strategy`: 3–6 sentences on how the proof works; write "unclear" for the parts you could not tell
- `hardest_part`: the part of the argument you would least trust yourself to have checked

Report at most 20 issues, most severe first. The bibliography is not shown; assume cited results are quoted correctly and do not report missing references. Return only JSON.

<manuscript>
{{DOC}}
</manuscript>
