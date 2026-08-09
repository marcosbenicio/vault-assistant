---
tags: [project, intro]
---

# Vault Assistant

A RAG assistant that answers questions about a vault. **What counts as a vault**: a folder of markdown notes, optionally connected by wikilinks and annotated with frontmatter. Links and metadata enrich the search when they exist; nothing is required. An Obsidian vault fits this definition as-is (see [[09-running-it]] for connecting one), but nothing here depends on Obsidian — the vault being plain files is the whole reason an external application can read it: ingestion parses the notes, indexes them into Elasticsearch, and a Streamlit app answers questions over that index with an LLM, citing the notes it used. Every answer is logged, judged and drawn on a dashboard. This is the final project of LLM Zoomcamp 2026, and it applies the full arc of the course to a personal use case: the RAG flow from [[03-rag]], vector and hybrid search from [[04-vector-search]], evaluation with ground truth and LLM-as-judge from [[04-search-evaluation]] and [[13-llm-as-judge]], and the monitoring stack from [[05-database]] and [[12-grafana]].

## How the pieces fit

```
vault (markdown files, read only)
   |
   |  ingestion: clean -> chunk -> embed -> index
   v
elasticsearch  <---  search: bm25 + knn, fused with RRF
   |
   v
rag chain: retrieve -> build prompt -> llm answers with sources
   |
   v
streamlit app --- postgres diary (conversations, feedback, judgements)
                        |
                        v
                     grafana dashboards
```

Between typing a question and seeing the answer, the full loop runs in four steps. First, retrieval: an LLM rewrites the question into the vault's vocabulary, the searcher runs BM25 and vector search with both the original and the rewritten question, and the rankings are fused; the 10 best chunks come back. Second, the prompt: the chain assembles a context block where every excerpt opens with its source path, places the context first and the question last, and instructs the model to answer only from what is there. Third, generation: the model answers at temperature zero and lists the notes it actually used. Fourth, the record: three writes go to Postgres, the conversation with tokens, cost and latency, the automatic verdict of an LLM judge on the answer, and, if the user clicks a thumb, the human vote.

## The package

The code is a small python package, one file per responsibility, and it speaks the LangChain dialect without depending on LangChain: the same names and shapes the ecosystem uses, in plain python that can be read end to end.

- `cleaner.py`: `Document` (page_content plus metadata) and `NoteCleaner`, which turns raw vault markdown into clean text and extracts the note graph. See [[04-note-cleaning]].
- `embeddings.py`: `SentenceTransformerEmbeddings`, with `embed_documents()` for chunks and `embed_query()` for questions, the two sides guaranteed to live in the same vector space.
- `ingest.py`: `VaultLoader` (the LangChain loader interface, `lazy_load()` and `load()`), `SlidingWindowSplitter` (`chunk_size`, `chunk_overlap`) and `ElasticsearchIndexer`. See [[03-ingestion-pipeline]].
- `search.py`: `VaultSearcher` with the four search modes (text, vector, hybrid, rerank) and `ElasticsearchRetriever`, the `get_relevant_documents()` interface the chain consumes. See [[05-search-and-index]].
- `rewriter.py`: `QueryRewriter`, the vocabulary translator in front of the search, and `RewriteFusedSearch`, the default retrieval mode: hybrid with the original and the rewritten question, fused. See [[06-retrieval-evaluation]].
- `rag.py`: `ObsidianRAG`, the chain: retrieve, build prompt, call the model at temperature zero, return answer plus source documents. The provider (OpenAI api or a local server) is decided by the app's sidebar and environment.
- `judge.py`: `LLMJudge`, the automatic evaluator with a structured verdict. See [[07-generation-and-judge]].
- `db.py`: `ConversationLog`, the three-table diary over postgres. See [[08-monitoring-stack]].
- `metrics.py`: `CallMetrics`, tokens, dollars and seconds of one llm call.
- `app.py`: the Streamlit face wiring everything together.

Every class receives its dependencies at birth (the searcher gets the es client, the embeddings and the index name; the chain gets a retriever and an llm client), nothing inside the package reads the environment, and only the entry points (the app, the ingest main) wire things from env. That is what keeps every piece testable in a notebook before it ships.

## The decisions, all measured

Two rules shape the project. The vault is mounted read only: the assistant reads notes and can never touch them. And everything is measured against a committed ground truth of 200 questions, so every choice below has a number behind it:

- Hybrid search is the retrieval base: 0.755 hit rate at 10 against 0.680 for text and 0.715 for vector alone.
- Query rewriting, fused, is the default retrieval: an LLM translates the question into the vault's vocabulary and hybrid runs with both versions, merged with RRF. The largest measured gain of the project, hit rate 0.755 to 0.885 and hard questions 0.68 to 0.86, for one cheap extra LLM call.
- Reranking with a cross-encoder is the quality mode over plain hybrid: the largest pure ordering gain of the project (rank-1 hits 74 to 91), at 4 seconds per question of latency, which is why it is not the default.
- The embedding model is the small MiniLM: a stronger challenger tied with it on this vault, measured twice.
- gpt-5.6-luna answers by default: 82% of its answers judged RELEVANT against 76% for gpt-5.4-mini and 60% for the local qwen, with refusals cut from 18% to 8%, at about a third of mini's token price. The judge and the query rewriter stay on gpt-5.4-mini, the validated deterministic pair; the local models remain the free and private mode.

The full stories are in [[06-retrieval-evaluation]] and [[07-generation-and-judge]].

## The notes in this folder

Each stage has its own note, in reading order: [[02-architecture]], [[03-ingestion-pipeline]], [[04-note-cleaning]], [[05-search-and-index]], [[06-retrieval-evaluation]], [[07-generation-and-judge]], [[08-monitoring-stack]], [[09-running-it]] and [[10-trade-offs]]. The raw course material these notes build on is transcribed in the concepts folder: [[rag]], [[rag_vector_search]], [[evaluation]] and [[monitoring]]; the project's own evaluation notebooks are stitched, almost verbatim, in [[project_notebooks]]. The original course notes live beside them in this same vault, and are linked wherever a concept is applied.
