---
tags: [project, ingestion]
---

# The ingestion pipeline

Ingestion moves notes from the vault into the search engine. In the
LangChain dialect it is three components chained: a loader turns files
into Documents, a splitter turns Documents into overlapping chunk
Documents, and an indexer writes chunks into Elasticsearch with their
embeddings. The course version of this pipeline is in
[[09-data-ingestion]]; this note is how the project implements it.

## The loader

`VaultLoader` walks the vault with the LangChain loader interface:
`lazy_load()` yields one Document at a time, `load()` returns the full
list. It skips hidden paths and the `_playground` staging area (the
future home of generated notes, which must never contaminate
retrieval), parses the yaml frontmatter of each note, and delegates
text cleaning to the injected [[04-note-cleaning|cleaner]].

Every note becomes a Document whose metadata carries: the source path
(the identifier from here on), title, folder, tags, the weighted note
references (`graph_edges`), the external urls the cleaner pulled out
(`external_links`), and the file's last modified time. A note that
fails to parse, a broken yaml header for example, is reported and
skipped: one sick note must not kill the whole vault.

## The splitter

`SlidingWindowSplitter` cuts each Document into windows of 2000
characters advancing by 1000, so consecutive chunks overlap by half.
Long notes do not retrieve well as wholes: the answer to a question
lives in a passage, an embedding of thousands of characters averages
into mush, and the prompt has a budget. The overlap guarantees that
any idea near a boundary appears whole in some chunk; the redundancy
it creates in the index is cheap, paid once at indexing time.

Each chunk is a Document again, inheriting the note metadata plus
`start`, its character offset inside the note. The concept and the
experiments behind chunk sizing are in [[rag]] and
[[rag_vector_search]].

## The indexer

`ElasticsearchIndexer` is the adapter between the dialect and the
storage: Documents in, flat Elasticsearch fields out. Three details do
the real work.

Ids are deterministic, the source path plus the chunk offset
(`05-search.md::1000`), so re-running the ingestion overwrites instead
of duplicating: the pipeline is idempotent by construction.

The write is batched: all chunks are embedded in a single model call
and written with one bulk request. That took the full ingestion from
about three minutes (one model call and one http request per chunk) to
about fifteen seconds, an order of magnitude, and made reindexing
cheap enough to be automatic.

An optional context header prepends `[folder / title]` to each chunk
before embedding, so both BM25 and the vector absorb where the note
lives in the vault: a chunk from the middle of a note is an orphan
without it.

## Automation

The pipeline runs as a one-shot container on every stack startup: same
image as the app, command `python ingest.py`, waiting for the
Elasticsearch healthcheck before starting, exiting when done (see
[[02-architecture]]). Bring the stack up and the index builds itself
from whatever is mounted at `/vault`. After changing notes, one
command reindexes everything:

```bash
make ingest
```

Because ids are deterministic and the index is recreated on each run,
the index always mirrors the vault folder exactly: add a note and it
becomes searchable, delete one and it disappears.

## The empty-vault guard

Recreating the index on every run has a failure mode that was found
the hard way: point the stack at a folder with no markdown in it, and
the one-shot would happily build an index of nothing — the old index
erased, the assistant answering from a void. The pipeline now
refuses: when the loader finds no documents, or the splitter produces
no chunks, the run stops with an explicit error BEFORE anything
destructive happens, and the existing index is left untouched, with
the message pointing at the recovery (pick another folder with the
launcher, or the demo). The same check guards the Reingest button in
the app, and the launchers refuse to even write a vault path whose
folder has no notes ([[11-starting-automated]]) — three fences around
the same cliff.

Next: [[04-note-cleaning]], the first and smartest link of this chain.
