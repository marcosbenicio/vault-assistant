---
tags: [project, evaluation]
---

# Retrieval evaluation

Retrieval decisions in this project are made with metrics, not by
feel. The method comes from the course ([[04-search-evaluation]],
[[05-search-metrics]], and the transcription in [[evaluation]]): build
a ground truth of question and expected document pairs, run every
retrieval configuration over it, compare hit rate and MRR.

## The ground truth

The dataset is 200 question and note pairs, generated with Claude
reading every note of the vault, and committed at
`data/claude_ground_truth.json` so every number below is reproducible.
Each note was read in full and produced its share of pairs, in two
deliberately different halves.

Fifty easy questions ask directly about note content, reusing the
note's own wording. Retrieval saturates on them (0.98 hit rate), so
they are a sanity floor, not a benchmark. The other 150 are hard on
purpose: adversarial paraphrases instructed to ask about the same
content using vocabulary the note never uses, "the thing doing the
lookups" for a note about a search engine. The hard half is what
separates retrieval methods, and where every remaining failure lives.

The metrics are the course pair. Hit Rate@10 measures presence: did
the expected note appear anywhere in the top 10, regardless of which
chunk. MRR measures position: how early it appeared, scoring 1 for
first place down to 1/10 for tenth.

## The results

Measured over all 200 questions:

```
              hit rate    mrr      easy hit   hard hit
text          0.680       0.463    0.92       0.60
vector        0.715       0.455    0.96       0.63
hybrid        0.755       0.491    0.98       0.68
rerank        0.765       0.543    0.96       0.70
```

Among the three search methods, hybrid wins on both metrics and both
difficulty levels, so it is the application default. Depth was also
measured: the hit rate curve keeps climbing between k=5 and k=10,
which is why the retriever feeds ten chunks to the model rather than
five.

Two embedding models were compared as well: MiniLM against bge-small,
the latter with and without the query instruction prefix its training
expects. A documented tie on this vault, twice measured, so the
lighter MiniLM stayed. The lesson that outlived the experiment:
embedding models have usage protocols, and comparing them fairly means
respecting each one's protocol.

## The error diagnosis

A per-question analysis (which rank did the expected note land at, and
who took first place instead) found two distinct diseases.

Most failures are near misses. Of 151 successful retrievals, 74
delivered the expected note in first place and 77 delivered it late,
behind thematically similar neighbors: intro and revision notes losing
to the specific note of their topic. The searcher finds the right
neighborhood and picks the wrong house.

A smaller tail are vocabulary gaps: hard questions whose words share
nothing with their target note, so neither keyword matching nor the
embedding bridges them. No amount of reordering fixes these, because
the right note never enters the candidate list.

## The reranking story

The near misses have a named remedy. Hybrid brings 30 candidates
instead of 10, a cross-encoder reads each question and chunk pair
jointly and rescores it, and the best 10 survive. The bi-encoder
behind vector search summarizes question and chunk into separate
vectors; the cross-encoder reads them together, which is exactly the
precision needed to tell the specific note from the intro that
mentions everything.

Measured on the full ground truth: hit rate 0.755 to 0.765, MRR 0.491
to 0.543, the largest ordering gain of the project, with rank-1
answers going from 74 to 91 and the hard subset from 0.68 to 0.70. The
costs were measured too: two points lost on the saturated easy subset
(the wide net occasionally demotes a good note out of the top 10), and
about four seconds per question on CPU.

The decision follows the numbers and the product. Since the model
reads all ten chunks anyway, better ordering buys little answer
quality for a heavy latency price: reranking ships as the quality
mode, one argument away, not the default. The measurement was
reproduced twice with identical output.

## The query rewriting story

The vocabulary gap got its own remedy, and it became the largest
improvement in the project. An LLM sits in front of retrieval as a
translator: it rewrites the question into the domain's vocabulary at
temperature zero, and hybrid search runs twice, once with the original
question and once with the translation, the two rankings merged with
reciprocal rank fusion. The original ranking protects what already
works; the translation adds candidates the original wording cannot
reach.

Measured on the same 200 questions: hit rate 0.755 to 0.885, the hard
subset 0.68 to 0.86, with 28 questions rescued and 2 broken, for one
extra cheap LLM call of about 0.7 seconds. A replace design, searching
with the translation only, was measured too and rejected: it broke 22
questions the baseline already answered. Fused is now the retrieval
default in the app.

One negative result is worth keeping. Stacking the reranker on top of
the fused candidates performs worse than fused alone (0.810), because
the cross-encoder scores every candidate against the original
question, never sees the translation, and demotes exactly the notes
the rewrite rescued. Stages of a retrieval pipeline must share
vocabulary.

The [[07-generation-and-judge|generation evaluation]] confirmed
independently that hard-set retrieval is where all answer failures
live, which is what makes this gain matter end to end.
