---
tags: [project, search]
---

# Search and index

The course built retrieval on minsearch and sqlitesearch
([[05-search]], [[05-minsearch-vector]], [[07-sqlitesearch-vector]]);
this project graduates to Elasticsearch, one engine doing both text
and vector search over the same documents, plus filters, aggregations
and persistence for free.

## The index and its mapping

Elasticsearch stores JSON documents in an index, and every field has a
type declared in the mapping. The type decides which data structure is
built at write time, and the data structure decides which queries are
even possible, so types are chosen by the question each field must
answer, not by what the value looks like:

- `content` and `title` are `text`: analyzed, chopped into terms,
  stored in an inverted index. That is what BM25 scores over. You
  search these, you do not filter on them.
- `path`, `folder`, `tags`, `graph_edges` and `external_links` are
  `keyword`: stored whole, exact match only. You filter, aggregate and
  sort on these. `folder` powers an optional scope filter every search
  mode accepts.
- `start` is an integer (the chunk offset, part of the id),
  `modified_at` a date (recency, ready for the dashboards).
- `embedding` is a `dense_vector` of 384 dims with cosine similarity:
  the declaration tells the engine to build the HNSW graph that makes
  approximate nearest neighbor search fast. Dims must match the
  embedding model, so the pair is one decision.

The mapping is a contract declared once at index creation; changing a
field means delete, create again, reingest. The indexer exposes that
as an explicit `recreate=True`, and deterministic ids make the rebuild
harmless.

## The four search modes

`VaultSearcher` holds the es client, the embeddings and the index
name, and offers four modes.

Text search is BM25 over content plus title, title worth double. It
rewards chunks containing the exact words of the question, especially
rare ones: precise when the vocabulary matches, blind when it does
not.

Vector search is kNN over the chunk embeddings: the question becomes a
vector through the same model that embedded the chunks (see
[[02-embeddings]] and the transcription in [[rag_vector_search]]), and
cosine similarity ranks the nearest ones. It finds meaning across
different wording, fuzzy about exact terms.

Hybrid search fuses both with reciprocal rank fusion. BM25 scores and
cosine similarities live on incomparable scales, so the fusion
combines rank positions instead: first place in either list earns
1/(k+1) points, second 1/(k+2), and a chunk ranked well by both
accumulates. Measured on the ground truth, hybrid beats each method
alone on both metrics, which made it the base of the application's
retrieval (numbers in [[06-retrieval-evaluation]]).

Rerank is not a search but a second stage on top of one: hybrid brings
30 candidates, a cross-encoder reads each question and chunk pair
together and rescores it, the best 10 survive. Retrieve then rerank,
recall then precision. The full story of why it exists and what it
bought is in [[06-retrieval-evaluation]].

A fifth mode lives outside the searcher, in `rewriter.py`: query
rewriting. An LLM translates the question into the vault's vocabulary,
and `RewriteFusedSearch` runs hybrid twice, with the original and the
rewritten question, merging the rankings with the same reciprocal rank
fusion. Measured as the biggest retrieval gain of the project, it is
the application default (the story in [[06-retrieval-evaluation]]).

## The retriever

`ElasticsearchRetriever` is the LangChain interface the chain
consumes: `get_relevant_documents(question)` returns chunk Documents,
which is all the RAG chain needs to know about retrieval. It takes any
searcher method as its `search_fn`, so switching the app from hybrid
to rerank is one argument, and returns 10 results, a depth chosen by
measurement: the hit rate curve was still climbing between 5 and 10.

This is how the assistant decides which notes to send to the model:
nothing is hand picked and no note is special. The question runs
through the default rewrite-and-fuse search, the 10 chunks that rank
best across the rankings become the context, and everything else
stays out. The model
never sees the vault, only those 10 excerpts, which is why retrieval
quality bounds answer quality (measured in
[[06-retrieval-evaluation]] and confirmed from the generation side in
[[07-generation-and-judge]]).

Next: [[06-retrieval-evaluation]], where all of this gets numbers.
