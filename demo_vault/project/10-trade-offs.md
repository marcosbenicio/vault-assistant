---
tags: [project, evaluation, design]
---

# Trade-offs, read correctly

Every retrieval system has trade-offs; weak systems have surprises
instead. What separates the two is measurement: each limit below is
named, quantified on the committed ground truth, and either treated
with a measured remedy or consciously priced. None of them is an
accident, and none of them is unknown. The numbers come from the
project's evaluation notebooks, where each analysis can be rerun.

## "Retrieval is not perfect"

True, and the imperfection has a full anatomy, not just a number. The
0.755 hit rate belongs to plain hybrid, the BASE the system builds on;
the shipped default, query rewriting fused with hybrid, reaches 0.885
(see [[06-retrieval-evaluation]]). The per-question diagnosis broke
the base's misses open: of 200 questions, hybrid delivered 151 inside
the top 10, and only 74 of those at rank 1 — 77 answers arrived late,
behind thematically similar neighbors. The confusion pairs have a
shape: intro and revision notes losing the top spot to the specific
note of their topic. The searcher finds the right neighborhood and
picks the wrong house. That is an ORDERING disease, and it got an
ordering cure (the reranker). The remaining tail — questions whose
words share nothing with their target note — is a PRESENCE disease,
and it got a presence cure (the rewriter), which rescued 28 questions
while breaking 2.

Even the depth of the result list is a measured choice, not a habit:
the hit-rate-at-k curve keeps climbing visibly between k=5 and k=10,
which is why the retriever feeds ten chunks to the model rather than
five. And the evaluation states its own scope honestly: measured over
the full demo vault the base hit rate lands near 0.68, because these
documentation notes compete with the course notes for top-10 slots;
the reported numbers are reproduced on a dedicated index of the
ground truth's own corpus, a protocol the retrieval notebook builds
for itself.

## "Vector search is fuzzy, text search is vocabulary-blind"

This is not a flaw of the implementation; it is the fundamental
duality of search, and it holds for every engine ever built. Measured
alone on the ground truth, text lands at 0.680 and vector at 0.715 —
and the two miss DIFFERENT questions, which is exactly what
reciprocal rank fusion exploits: hybrid's 0.755 beats both because a
note ranked well by either list accumulates. If the two engines
failed on the same questions, fusion would have nothing to combine
and the numbers would stay flat. The rewriter then attacks the
residue from a third direction, giving the lexical engine informative
terms to match ("the thing doing the lookups" becomes "search
engine") and the semantic engine a more focused representation.

The embedding side of this duality was also stress-tested rather than
assumed: a stronger challenger model (bge-small) was benchmarked
against MiniLM twice, with and without the query instruction prefix
its training expects, and tied on this vault — so the lighter model
stayed. The lesson that outlived that experiment: embedding models
have usage protocols, and comparing them fairly means respecting each
one's protocol.

## "Reranking adds a second stage"

Complexity added on purpose, with a price tag measured on both sides.
The cross-encoder reads each question and candidate chunk TOGETHER —
the precision a bi-encoder's two separate vectors cannot offer — and
buys the largest pure ordering gain in the project: MRR 0.491 to
0.543, rank-1 answers 74 to 91. The costs were measured with the same
care: about 4 seconds per question on CPU, and two points lost on the
saturated easy subset, because a 30-candidate net occasionally drags
a good note out of the top 10. The decision respected the product:
since the model reads all ten chunks anyway, better ordering buys
little answer quality, so reranking ships as an optional quality
mode, one click away, and NOT as the default.

The project also measured where this complexity must NOT go. Stacking
the reranker on top of the fused rewriting — each remedy treating its
own disease, in theory — made retrieval WORSE than fused alone (0.810
against 0.885, hard subset 0.86 down to 0.76). The mechanism, traced
in the rewriting evaluation: the cross-encoder scores every candidate
against the ORIGINAL question, never sees the translation, and so
systematically demotes exactly the notes the rewrite rescued. Stages
of a retrieval pipeline must share vocabulary. A negative result that
is documented instead of discovered by users is a strength, not a
scar.

## "Query rewriting adds another llm call"

The cheapest trade in the project: about 0.7 seconds and a fraction
of a cent buy 13 points of hit rate, with the hard subset climbing
from 0.68 to 0.86. The design itself was chosen by measurement, not
taste. Two strategies were benchmarked: REPLACE, searching with the
translation only, reached 0.815 overall but broke 22 questions the
baseline already answered — a poor rewrite can drop the exact words
that made an easy question easy. FUSED runs hybrid twice, original
and rewritten, and merges the rankings: the original protects what
already works while the translation adds candidates the original
vocabulary cannot reach — 28 rescued, 2 broken, easy subset intact.
The flip analysis (who was rescued, who was broken, by name) is in
the retrieval notebook.

A moving part is only a liability when it can jam the machine, so
this one was built unable to: the rewriter runs at temperature zero,
and any failure falls back to searching the original question
untouched. It can stop helping; it cannot start hurting. The "extra
call" framing also undersells what is bought: the vocabulary gap it
closes is precisely the failure mode no amount of reranking or better
embeddings could touch, because the right note never entered the
candidate list.

## "The online judge has no reference answer"

By definition: production has no answer key, for this system or any
other. What can differ is whether the judge's blindness is measured
or assumed away. Here it was measured directly: the same 50 answers
were judged twice, once blind (question and answer only, the
production setup) and once by a reference-informed judge that also
read the full expected note. They agreed on 72% of verdicts — 80% on
the binary relevant-or-not read — and the disagreement has a KNOWN
anatomy, visible in the agreement matrix of the judge evaluation
(see [[07-generation-and-judge]]). The blind judge is slightly
generous, mostly
approving answers the informed judge downgrades. But part of the gap
runs the other way: the informed judge, anchored on one expected
note, penalizes correct answers built from ALTERNATIVE notes — its
own bias, inherited from the single-note ground truth. Neither
instrument is perfect; both are characterized.

Two design choices keep the instrument stable: temperature zero (the
same answer always receives the same verdict) and structured output
with the reasoning written before the verdict (the shape is
guaranteed, and the justification precedes the label). Before any
large run was paid for, samples of verdicts were also audited by
hand, label and reasoning both. And because both generation models
were scored by the SAME instrument, the comparison between them is
unaffected by the judge's absolute bias — deltas survive a shifted
zero. The human feedback buttons are the independent check: when the
judge and the humans drift apart, the dashboards show it.

## The pattern, closed end to end

Read the five again and one shape repeats: a limit is found, named,
measured, then either cured (vocabulary gap), priced (reranking),
bounded (judge bias) or fenced (rewriter fallback). The generation
evaluation closes the loop with a ceiling analysis: given the
measured retrieval hit rates and the sample's difficulty mix, a
perfect generator would score about 76% RELEVANT — and the api
default sits on that line, meaning its failures ARE the retrieval
misses, while the local qwen sits 16 points below it, a genuine
generation loss, and luna lands above it by converting alternative
retrieved notes (the single-note ground truth slightly understates
the real system; the per-question cross-check documents both
nuances).

The system was then examined as a whole: fifty questions, five per
course criterion, answered by the assistant about its own
documentation and scored by the validated judge — 94% RELEVANT, all
ten hard questions passing, and each of the three failures traceable
to a named subsystem (two retrieval misses, one generation nuance).
In production the loop keeps running: every answer is logged with its
full retrieval trace, cost and latency, judged automatically, and
open to a human vote (see [[08-monitoring-stack]]). That loop — not
any individual number — is the strong point of the system. The full
stories live in [[06-retrieval-evaluation]] and
[[07-generation-and-judge]].
