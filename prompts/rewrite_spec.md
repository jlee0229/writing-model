You are rewriting an AI-generated research manuscript so that a mathematician can follow it and check it.

The source below is believed to be correct (its main theorem has a machine-checked Lean proof), but it was written as raw research output: dense, with skipped steps and little guidance. Your rewrite will be read by a strong mathematics student who has finished a first-year graduate curriculum, is not a specialist in this subfield, and has about an hour. They want to (a) understand what is proved and why the proof works, and (b) verify each step, and catch the error if there is one.

What a good rewrite does:

1. **Orients the reader fast.** It opens with the main result stated precisely and self-containedly, just enough background to parse it, and then a short "Proof at a glance": the key idea, the steps of the argument, and how they depend on each other (which lemma feeds which).
2. **Makes every step locally checkable.** Each proof is a sequence of small steps. Each step says what is claimed and exactly what justifies it: an earlier step, a named hypothesis, a cited result together with its precise statement, or a displayed computation. Where the source says "clearly", "it follows" or "a routine computation shows", supply the reason or the computation. Every symbol is introduced before it is used and keeps one meaning. Before a long proof, say its plan in one to three sentences. When a lemma is stated, say where it will be used.
3. **Keeps the mathematics identical.** Same theorems, lemmas, hypotheses, constants, and the same proof strategy. You may reorder material, split a proof into steps, add intermediate claims, small examples and sanity checks, and rename a symbol that clashes (say so when you do). Do not strengthen, weaken or "improve" any statement. Keep the source's citations and bibliography exactly; do not add citations.
4. **Is honest about what you could not verify.** Check each step as you write it. If you meet a step you cannot justify, or that looks wrong, do not silently repair, soften or drop it: keep the source's claim and mark it with `\unverified{...}`, giving your concern in one or two sentences. Use this only for real doubts about correctness, never for style. If you have no doubts there are no such marks.
5. **Respects the reader's time.** Add what is needed to verify; cut what is not. No filler, no praise, nothing said twice. Expect the result to be somewhat longer than the source (roughly 1.2–2 times); if it is much longer than that, it has probably lost the thread.
6. **Ends with a short "Verification checklist"**: the few load-bearing steps a sceptical reader should check first, each with a pointer to where it is proved.

Format: output one complete LaTeX document that compiles with pdflatex, and nothing else. It starts with `\documentclass` and ends with `\end{document}`. Reuse the source's preamble and bibliography setup; you may add standard packages (amsmath, amssymb, amsthm, enumitem, xcolor, tikz, hyperref). Add this to the preamble:

```
\newcommand{\unverified}[1]{\par\smallskip\noindent\fbox{\parbox{0.95\linewidth}{\textbf{Unverified step.} #1}}\par\smallskip}
```

Keep the title. Set the author line to `Rewritten for readability from the OpenAI manuscript of the same title`.
