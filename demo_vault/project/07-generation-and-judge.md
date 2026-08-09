---
tags: [project, evaluation, generation]
---

# Generation and the judge

The answering side of the system: how the chain builds its prompt, how
answers are evaluated without an answer key, and how two models
competed for the default seat.

## The chain

`ObsidianRAG` is the same three step assembly the course teaches from
module one ([[03-rag]], [[06-building-prompt]]): retrieve, build a
prompt, ask the model. The retriever supplies 10 chunk Documents, and
the prompt places the context first and the question last.

The prompt shows the model where each excerpt came from with an
explicit label: every chunk in the context block opens with a
`source:` line carrying its note path, like
`source: llm-zoomcamp-2026/01-agentic-rag/05-search.md`, and the
excerpts are separated by rulers. The system instructions tell the
model that each part starts with its source path and ask it to close
every answer with a Sources list of the paths it actually used, which
is what makes citations possible without the model knowing anything
about the vault. The instructions also restrict the answer to the
provided context and explicitly allow combining information from
multiple excerpts, a line added after observing over-refusals without
it.

Generation runs at temperature zero. That lesson was learned the
expensive way: the local model's answers swung between correct and
rambling on identical inputs, because sampling at the default
temperature is a dice roll. Zero makes every answer reproducible,
which is what a factual assistant over notes wants anyway.

`invoke(question)` returns the answer, the source documents and the
usage, the same contract a LangChain chain exposes, so the app can
show citations and log costs without knowing how retrieval works.

## The judge

Free text has no ground truth, so answers are evaluated by
llm-as-judge, the technique from [[13-llm-as-judge]] (transcribed in
[[evaluation]]): a strong model reads the question and the generated
answer and classifies the relevance as RELEVANT, PARTLY_RELEVANT or
NON_RELEVANT, writing its reasoning before the verdict.

Two details make the judge trustworthy. It runs at temperature zero,
so the same answer always receives the same judgement. And it answers
through the api's structured output (a pydantic schema with the
reasoning field first, so the model justifies before it decides): the
shape is guaranteed, a verdict outside the vocabulary cannot happen.
And before being trusted, the judge was audited by the author, by
hand: samples of its verdicts were read next to the questions and
answers they judge, checking both the label and the written reasoning,
across more than one random sample, before any large run was paid for.
A judge nobody audited is just another opinion.

One structural note: the course's offline setup compares the generated
answer against the original FAQ answer, but this vault has no gold
answers, the ground truth maps questions to notes. So the offline run
uses the reference-free judge, the same one production uses, applied
over a fixed sample.

## The comparison

The same 50 ground truth questions, answered by gpt-5.4-mini through
the api and qwen2.5 7b through the local ollama, every answer judged:

```
                      relevant   partly   non    seconds   dollars
gpt-5.6-luna          0.82       0.10     0.08   2.4       0.001
gpt-5.4-mini          0.76       0.06     0.18   1.4       0.001
qwen2.5:7b-instruct   0.60       0.32     0.08   70.5      0
```

The api models win on every axis but price. The failure profiles
differ in character: when retrieval brings no useful context, mini
refuses honestly (its NON_RELEVANT cases are "could not find it in the
vault" answers, the intended behavior), while qwen wanders around
loosely related content, which the judge scores PARTLY_RELEVANT.

Luna, added to the same bench later, took the crown: 82% RELEVANT with
the refusal rate cut from 18% to 8%, at about a third of mini's token
price and two seconds per answer. It is now the default answer model.
The judge and the query rewriter stay on gpt-5.4-mini: that pair is
validated and deterministic, while the 5.6 family only runs at the
provider's default temperature, so luna's answers can vary between
runs — acceptable for answering, not for judging or measuring.

## The ceiling analysis

The strongest finding ties the two evaluations together. Given the
retrieval hit rates (0.98 easy, 0.68 hard) and the sample's difficulty
mix, a generator that answered perfectly whenever the right note
arrived would score about 76% RELEVANT on this sample. mini sits
exactly on that line: it converts essentially every retrieved context
into a relevant answer, and its failures are the retrieval misses. The
local model sits 16 points below the ceiling, its own generation loss.
Luna lands above the line, at 82%, which sounds impossible until the
ceiling's own assumption is read closely: the line was computed for a
generator answering only from the expected note, and luna converts
the alternative retrieved notes more often — the exact nuance the
cross-check below documents as the single-note ground truth
understating the real system.

A per-question cross-check confirmed the link: good verdicts line up
with retrieval hits, bad ones with misses, with two nuances that
roughly cancel. A few hits still produce bad answers (a small true
generation loss), and a few misses are answered well anyway, because
another retrieved note carried the same information: the single-note
ground truth slightly understates the real system.

The practical conclusion for the whole system: better answers now
depend on better hard-set retrieval (see [[06-retrieval-evaluation]]),
not on a better generator. In production, the same judge scores every
answer the app gives, feeding the [[08-monitoring-stack]].
