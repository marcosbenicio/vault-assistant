---
tags: [project, monitoring]
---

# The monitoring stack

Elasticsearch stores the knowledge; Postgres stores the history. Every
use of the assistant leaves a triple record, following the pattern of
the course's monitoring module ([[05-database]], [[08-user-feedback]],
[[09-built-in-judge]], transcribed in [[monitoring]]) and extending it
with richer fields and an automatic judge.

## The star schema

The schema is a small star: one fact table in the center, one row per
answered question, and two satellite tables pointing at it by foreign
key.

```
conversations   <- the llm's side: question, answer, models, tokens,
    ^    ^         cost, retrieval and total time, sources, session
    |    |
feedback  judgements
(human,   (machine: the judge's verdict on every
 sparse)   production answer)
```

The conversations table is deliberately rich, every column with a
consumer waiting: question and answer, the llm that answered, the
embedding model active, the search mode (fused today, rerank when the
quality toggle lands), how many chunks were retrieved and which ones
(a jsonb list with path, offset and score, the full retrieval trace
for debugging any answer after the fact), tokens in and out, cost in
dollars, retrieval time separated from total time, the channel that
asked (streamlit today, other entry points can share the table), a
session id grouping the questions of one sitting, and a timezone aware
timestamp.

Feedback holds the human vote: a thumbs up or down pointing at its
conversation, plus an optional free-text comment. Sparse by nature,
most conversations get no vote. Judgements holds the machine vote: the
judge scores every production answer automatically (verdict, its
written reasoning, and which model judged), so machine coverage is
total. Where human and machine disagree is where the interesting rows
live.

## Write path and safety

The app writes the conversation right after answering and keeps its
id; the judge call runs next, wrapped so a judging failure can never
block an answer, the observer never stops the show; the thumbs write
whenever the user clicks. Each write opens one short-lived connection,
the safe pattern under Streamlit reruns.

Table creation is idempotent (`make init-db`, safe on every startup),
and schema changes have an explicit destructive path (`make
reset-db`), mirroring the recreate pattern of the search index: gentle
by default, explicit when erasing.

## Grafana

Grafana reads the three tables joined by conversation id, the same
LEFT JOIN shape validated in the database notebook (a conversation
without feedback must still appear). The datasource and dashboards are
provisioned from files in the repo, following [[12-grafana]]: a fresh
clone gets the same panels without clicking anything. The panels draw
volume, cost, latency, tokens, human feedback and judge verdicts over
time, which closes the loop the course opened in
[[01-intro-monitoring]]: from a question typed in the app to a dot on
a chart, everything local.

Next: [[09-running-it]].
