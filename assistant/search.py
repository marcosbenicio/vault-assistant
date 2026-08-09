from sentence_transformers import CrossEncoder

from cleaner import Document


class VaultSearcher:
    """The four search modes over the indexed vault: bm25 text, knn
    vector, their reciprocal rank fusion, and cross-encoder reranking
    on top. Holds the elasticsearch client, the embeddings and the
    index name; the cross-encoder loads lazily on first rerank."""

    def __init__(self, es_client, embeddings, index):
        self.es_client = es_client
        self.embeddings = embeddings
        self.index = index
        self._reranker = None

    def text(self, query, num_results=5, folder=None):
        """BM25 over content plus title, title worth double. An
        optional folder narrows the scope to that subtree (prefix
        match, so "a" covers "a/b" too) without touching scores."""
        body = {"bool": {
            "must": {
                "multi_match": {
                    "query": query,
                    "fields": ["content", "title^2"],
                    "type": "best_fields",
                }
            }
        }}
        if folder:
            body["bool"]["filter"] = {"prefix": {"folder": folder}}

        resp = self.es_client.search(
            index=self.index,
            size=num_results,
            query=body,
            _source=["path", "title", "start", "content"],
        )

        return [{**h["_source"], "_score": h["_score"]}
                for h in resp["hits"]["hits"]]

    def vector(self, query, num_results=5, folder=None):
        """kNN over the chunk embeddings: the question becomes a vector
        with the same model that embedded the chunks, and cosine
        similarity ranks the nearest ones."""
        knn = {
            "field": "embedding",
            "query_vector": self.embeddings.embed_query(query),
            "k": num_results,
            "num_candidates": 1000,
        }
        if folder:
            knn["filter"] = {"prefix": {"folder": folder}}

        resp = self.es_client.search(
            index=self.index,
            knn=knn,
            size=num_results,
            _source=["path", "title", "start", "content"],
        )

        return [{**h["_source"], "_score": h["_score"]}
                for h in resp["hits"]["hits"]]

    def hybrid(self, query, num_results=5, k=60, folder=None):
        """Reciprocal rank fusion of the text and vector rankings.
        Scores from bm25 and cosine live on incomparable scales, so the
        fusion combines RANK POSITIONS: first place in each list earns
        1/(k+1), second 1/(k+2), and a chunk ranked well by both
        accumulates."""
        text_hits = self.text(query, num_results=num_results, folder=folder)
        vector_hits = self.vector(query, num_results=num_results, folder=folder)

        scores, docs = {}, {}
        for results in (text_hits, vector_hits):
            for rank, doc in enumerate(results):
                key = (doc["path"], doc["start"])
                scores[key] = scores.get(key, 0) + 1 / (k + rank + 1)
                docs[key] = doc

        ranked = sorted(scores, key=scores.get, reverse=True)
        return [{**docs[key], "_score": scores[key]} for key in ranked[:num_results]]

    def rerank(self, query, num_results=10, candidates=30, folder=None):
        """Wide net, then fine judgment: hybrid brings `candidates`
        chunks, the cross-encoder rescores them reading query and chunk
        together, and only the best num_results survive."""
        if self._reranker is None:
            self._reranker = CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2")
        hits = self.hybrid(query, num_results=candidates, folder=folder)
        scores = self._reranker.predict([(query, h["content"]) for h in hits])
        ranked = sorted(zip(hits, scores), key=lambda pair: -pair[1])
        return [{**h, "_score": float(s)} for h, s in ranked[:num_results]]


class ElasticsearchRetriever:
    """The LangChain retriever interface: get_relevant_documents(query)
    returns chunk Documents, which is all the RAG chain needs to know
    about retrieval. search_fn is any VaultSearcher method."""

    def __init__(self, search_fn, num_results=10):
        self.search_fn = search_fn
        self.num_results = num_results

    def get_relevant_documents(self, query):
        hits = self.search_fn(query, num_results=self.num_results)
        return [Document(
            page_content=h["content"],
            metadata={"source": h["path"], "start": h["start"],
                      "score": h["_score"]},
        ) for h in hits]
