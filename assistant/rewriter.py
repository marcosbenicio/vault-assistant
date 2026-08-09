"""Query rewriting: a translator between the user's vocabulary and the
vault's. The rewriter turns a vague question into a keyword-rich query;
the fused search runs hybrid with BOTH versions and merges the two
rankings, so the translation can only add evidence, never replace it."""


class QueryRewriter:
    """The translator in front of the search: rewrites a user question
    into the domain's vocabulary, at temperature zero. If the llm call
    fails, the original question comes back untouched: the translator
    can be absent, never in the way."""

    REWRITE_PROMPT = """
You rewrite search queries for a knowledge base about building RAG
systems: retrieval, embeddings, vector search, elasticsearch, llm
evaluation, monitoring, docker, and the tooling around them.

Rewrite the user question as a keyword-rich search query using the
vocabulary this domain would use in its notes. Keep the original
intent, expand vague references into concrete terms, and output ONLY
the rewritten query, nothing else.

Question: {question}
""".strip()

    def __init__(self, llm_client, model):
        self.llm_client = llm_client
        self.model = model

    def rewrite(self, question):
        """One translation for one question, original on any failure."""
        try:
            response = self.llm_client.chat.completions.create(
                model=self.model,
                temperature=0,
                messages=[{"role": "user", "content": self.REWRITE_PROMPT.format(
                    question=question)}],
            )
            rewritten = response.choices[0].message.content.strip()
            return rewritten if rewritten else question
        except Exception:
            return question


class RewriteFusedSearch:
    """Hybrid search with the original AND the rewritten query, the two
    rankings merged with reciprocal rank fusion. Measured on the 200
    question ground truth: hit rate 0.755 -> 0.885, hard questions
    0.68 -> 0.86, for one extra llm call (~0.7s) per question."""

    def __init__(self, searcher, rewriter, k=60):
        self.searcher = searcher
        self.rewriter = rewriter
        self.k = k

    def search(self, query, num_results=10, folder=None):
        """The same signature the plain search modes expose, so this
        plugs into ElasticsearchRetriever as a search_fn."""
        original = self.searcher.hybrid(query, num_results=num_results,
                                        folder=folder)
        rewritten = self.searcher.hybrid(self.rewriter.rewrite(query),
                                         num_results=num_results, folder=folder)

        scores, hits = {}, {}
        for ranking in (original, rewritten):
            for rank, hit in enumerate(ranking):
                key = (hit["path"], hit["start"])
                scores[key] = scores.get(key, 0) + 1 / (self.k + rank + 1)
                hits[key] = hit
        ranked = sorted(scores, key=scores.get, reverse=True)
        return [{**hits[key], "_score": scores[key]}
                for key in ranked[:num_results]]
