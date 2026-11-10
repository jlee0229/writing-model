A proof had one error planted in it. A reader then reported up to three candidate errors. Decide which candidate, if any, identifies the planted error.

A candidate counts as a hit only if it points at the same mathematical step as the planted error and its explanation is about the same defect (it need not propose the exact original wording). Pointing at the right lemma for an unrelated reason is not a hit. Note that the reader may have seen a differently worded writeup of the same proof, so match on the mathematics, not on wording or numbering.

<planted_error>
{{TRUTH}}
</planted_error>

<reader_candidates>
{{CANDIDATES}}
</reader_candidates>

Return JSON {"hit_rank": n} where n is the 1-based rank of the first candidate that is a hit, or 0 if none is.
