---
tags: [concepts, 02-vector-search]
---

# rag_vector_search

Raw reference: the explanatory markdown of `02-vector-search/notebooks/rag_vector_search.ipynb` (module 2 of the
course), transcribed in original order. The project notes cite
this material as the source of the concepts they apply.

---

# Setup

# Data Ingest

# Embedding

An embedding is a mapping

$$
f: \mathcal{T} \rightarrow \mathbb{R}^d
$$

where $\mathcal{T}$ is the space of texts and $d$ is the fixed dimensionality of the vector space. Its central property is geometric:

$$
\text{semantic similarity} \;\Longrightarrow\; \text{proximity in the vector space}
$$

In other words, the model learns an implicit metric of meaning. Texts with similar meaning land close together, and texts about unrelated topics end up far apart. In practice:

- each text becomes a vector $x \in \mathbb{R}^d$;
- searching by meaning becomes a nearest neighbor problem in this space;
- the comparison between two vectors is done through a similarity function $\mathrm{sim}(x, y)$.

The most common similarity function for text is the cosine:

$$
\cos(\theta) = \frac{x \cdot y}{\|x\|\,\|y\|}
$$

the magnitude of the vector is discarded and only the direction matters. This means that two texts can have very different lengths (a short sentence and a long paragraph) and still be considered similar, as long as they point in the same semantic direction.

For each FAQ document we concatenate `question + " " + answer` before embedding. This way the resulting vector ends up close to queries that use either the vocabulary of the question or the vocabulary of the answer, instead of favoring only one of the two sides. This matters because at search time the user's query can either resemble a paraphrase of the original question or describe a specific part of the answer.

The `all-MiniLM-L6-v2` model from `sentence-transformers` implements

$$
x = f_\theta(\text{text})
$$

where $f_\theta$ is a neural network (a BERT variant with 6 layers) trained with **contrastive learning** objectives that push positive pairs (texts with similar meaning) closer together and pull negative pairs (unrelated texts) apart. The general form of the objective is

$$
\mathcal{L} = -\log \frac{\exp\big(\mathrm{sim}(x, x^+)/\tau\big)}{\sum_j \exp\big(\mathrm{sim}(x, x_j)/\tau\big)}
$$

The model produces vectors of **384 dimensions**, already normalized. It is lightweight (around 80 MB) and runs fast on CPU.

When the embeddings are normalized ($\|x\| = \|y\| = 1$), as is the case for the `all-MiniLM-L6-v2` model we use here, they live on the unit hypersphere and the cosine reduces to the inner product:

$$
\cos(\theta) = x \cdot y
$$

This is exactly what we will compute in the next cells with `v.dot(u)`. No norm division, no extra step, because the model has already normalized the vectors for us.

Let's start with a query $q_1$ with vector $v_1$ and a document $d$ with vector $dv$.

The similarity between them is given by the inner product:

$$
\cos(\theta) = v_1 \cdot dv
$$

Now we try an unrelated query:

The first score for $q_1$ vs $d$ ($0.32$) is higher, so that query is more similar to the document about registration. The second score for $q_2$ vs d sits near $0$, because installing Docker has nothing to do with registration. A score near $0$ means the two vectors are about as different as they can be.

We end up with 1350 vectors in a 384 dimensional space and turn them into a 2-dimensional matrix $X$ where

- rows are documents (vectors)
- columns are dimensions of the vectors

# Vector Search

After embedding each of the $N$ documents in our FAQ, we obtain a finite set of vectors

$$
\mathcal{X} = \{x_1, x_2, \ldots, x_N\} \subset \mathbb{R}^d
$$

where each $x_i = f_\theta(\text{doc}_i)$ is the embedding of document $i$ and $d = 384$ is the fixed dimensionality of the space. Searching by meaning means finding, for a given query embedding $v_q \in \mathbb{R}^d$, the document whose vector is closest to $v_q$ under the chosen similarity function. Formally, vector search is the **nearest neighbor** problem:

$$
i^\star = \arg\max_{x_i \in \mathcal{X}} \, \mathrm{sim}(v_q, x_i)
$$

Since our embeddings are normalized, $\mathrm{sim}(v_q, x_i) = v_q \cdot x_i$ and the problem reduces to an arg max of inner products.

To compute every score in a single operation, we stack all vectors into a matrix

$$
X = \begin{bmatrix} x_1^\top \\ x_2^\top \\ \vdots \\ x_N^\top \end{bmatrix} \in \mathbb{R}^{N \times d}
$$

whose row $i$ is the embedding of document $i$. The full score vector is then a matrix vector product:

$$
\mathbf{s} = X v_q \in \mathbb{R}^N, \qquad s_i = x_i \cdot v_q
$$

This is exactly what `scores = X.dot(v_query)` computes in numpy. Internally, numpy delegates the operation to optimized BLAS routines, which is orders of magnitude faster than looping in Python. The result is $N$ scores, one per document.

The highest score is the most similar document:

Usually we want more than the single best match, so let's pull the top 5.

np.argsort sorts from lowest to highest, so the last 5 are the top ones:

This is vector search in its simplest form. We embed the query, compute dot products against all documents, and return the highest-scoring ones.

# Vector Search with minsearch

We pass the numpy array X with all embeddings and the list of documents as payload. The keyword_fields parameter works the same as in the text Index, so we can filter by course later.

Under the hood it does the same thing we just did by hand. It computes the dot product between each vector (after filtering) and our query vector.

Like the text index, we can filter by keyword fields. This matters for user experience. A student in LLM Zoom Camp doesn't care about answers from the data engineering course.

# RAG with Vector Search

To compare documents mathematically, we need to represent them as numerical vectors. The **bag-of-words** approach builds a term-document matrix where each row is a document and each column is a word from the vocabulary. The order of the words is ignored and most entries are zero (a sparse matrix).

The `CountVectorizer` simply counts how many times each word appears in a document. The `TfidfVectorizer`, which is what `minsearch.Index` uses internally, goes further: it weighs each word by how rare it is in the corpus. The idea is that words like "the" or "is" appear in almost every document and do not help distinguish one from another, while words like "docker" or "python" are discriminative.

The weight of a term $t$ in a document $d$ is given by:

$$
\text{TF-IDF}(t, d) = \underbrace{f(t, d)}_{\text{frequency of } t \text{ in } d} \times \underbrace{\log \frac{N}{n_t}}_{\text{inverse document frequency}}
$$

where $N$ is the total number of documents and $n_t$ is the number of documents that contain the term $t$. In the `minsearch.Index` constructor we can pass `vectorizer_params={"stop_words": "english", "min_df": 5}` to remove common words and ignore rare ones, but the library defaults (`min_df=1`, `max_df=1.0`, no stop words removed) already cover typical cases.

The formula above gives a single number per pair $(t, d)$. To turn these weights into a search engine, they have to be laid out on a shared coordinate system. The `TfidfVectorizer` first scans every document in the corpus and builds a vocabulary

$$
V = \{t_1, t_2, \ldots, t_{|V|}\}
$$

of all unique terms. Each term receives a fixed index, and that index becomes the position it occupies in every vector. Each document $d$ is then represented as a vector $\mathbf{x}^{(d)} \in \mathbb{R}^{|V|}$ whose entry at position $i$ is the TF-IDF weight of term $t_i$ in document $d$:

$$
\mathbf{x}^{(d)}_i = \text{TF-IDF}(t_i, d)
$$

If $t_i$ does not appear in $d$, the entry is $0$. Most documents contain only a small fraction of the vocabulary, so most entries are zero. Stacking all $N$ document vectors row by row, we obtain the term-document matrix

$$
X = \begin{bmatrix} \mathbf{x}^{(1)\top} \\ \mathbf{x}^{(2)\top} \\ \vdots \\ \mathbf{x}^{(N)\top} \end{bmatrix} \in \mathbb{R}^{N \times |V|}
$$

stored in **sparse** form so that only non-zero positions occupy memory.

When a query comes in, it is mapped to the same space by `vectorizer.transform([query])`, which uses the vocabulary $V$ already learned during `fit`. Any token in the query that is not in $V$ is silently dropped. The result is a vector $\mathbf{q} \in \mathbb{R}^{|V|}$, also sparse, sharing the exact same coordinate system as the documents. From this point on, comparing the query to a document is a purely geometric operation in $\mathbb{R}^{|V|}$, which is what the next section formalizes.

This still uses keyword search. Text search isn't bad here, so the answer may already look right. Next we replace search with vector search.

We already have:

- All the indexed documents documents
- The embeddings matrix X with all these documents
- The vector search engine vindex

We can't pass vindex to RAG as-is. Text search takes the query string directly, but vector search needs the query as a vector first. So we subclass RAGBase and override search to encode the query before searching.

The `__init__` method adds one extra argument, embedder, for the sentence transformer. Inside search we use it to turn the query into a vector. Then we query vindex with that vector instead of the raw text. Everything else is inherited from RAGBase.

# Vector Search with sqlitesearch

In every nearest neighbor problem we have a set of vectors

$$
\mathcal{X} = \{x_1, x_2, \ldots, x_N\} \subset \mathbb{R}^d
$$

and a query $v_q \in \mathbb{R}^d$. The exact answer is the vector that maximizes the similarity,

$$
x^\star = \arg\max_{x_i \in \mathcal{X}} \, \mathrm{sim}(v_q, x_i)
$$

and finding it requires comparing $v_q$ against every $x_i$ in the set. As $N$ grows, we want to avoid this exhaustive scan and trade a small loss of accuracy for a much faster search. That is what approximate nearest neighbor search does.

The idea is to encode the geometry of $\mathcal{X}$ in a navigable graph $G = (V, E)$, where each vertex represents a vector and edges connect vectors that are locally close in the embedding space. The graph is not necessarily an exact nearest neighbor graph; its edges are built heuristically to make navigation efficient.

At query time, the search starts from an entry vertex and greedily moves to a neighbor that is more similar to the query:

$$
v_{t+1} = \arg\max_{u \in \mathcal{N}(v_t) \cup \{v_t\}} \, \mathrm{sim}(v_q, u)
$$

If the current vertex is already more similar than all of its neighbors, $v_{t+1} = v_t$ and the search stops. Only a small fraction of the graph is visited, and the search usually retrieves vectors close to the true nearest neighbors.

The HNSW (Hierarchical Navigable Small World) variant extends this idea with multiple graph layers. Upper layers contain fewer vertices and provide long-range navigation; lower layers refine the search locally. In practice this gives much lower query cost than scanning all $N$ vectors, with a tunable tradeoff between latency and recall controlled by search parameters such as `ef_search`.

sqlitesearch supports three ANN modes:

- lsh (default): up to 100K vectors, random hyperplane projections
- ivf: 10K-500K vectors, K-means clustering
- hnsw: 10K-1M+ vectors, proximity graph (highest recall)

For our small dataset, `lsh` is fine. All modes use two-phase search: approximate candidate retrieval, then exact cosine similarity reranking.
Fit the index with our vectors and documents. The index is saved to faq_vectors2.db. Unlike minsearch, this file persists on disk. You can search immediately after indexing, or reopen the index later without re-indexing.

Search works the same way as with minsearch. We always encode the query into a vector first. This is one thing that makes vector search heavier than text search. With text search we'd throw the raw query straight at the engine.

Encode, then search:

We still load the embedding model to encode the query, but we don't re-embed all the documents. No fit call needed, because the index is already built and waiting on disk.

This is the same two-process split we used for text search in module 1. One process ingests and builds the index, another queries it.

It matters more here than with text search. Embedding the whole dataset takes about a minute. We don't want a user waiting that long when the app starts up. We pay that cost once during ingestion, and the query side starts up instantly.

Here is how the two compare:

- minsearch VectorSearch: in-memory (numpy), exact cosine similarity, must re-compute embeddings on startup, good for experiments and notebooks
- sqlitesearch VectorSearchIndex: persistent (SQLite .db file), ANN (LSH/IVF/HNSW) with exact rerank, can open an existing index, good for projects and persistence
