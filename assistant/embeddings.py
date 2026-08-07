from sentence_transformers import SentenceTransformer


class SentenceTransformerEmbeddings:
    """The LangChain embeddings interface over sentence-transformers.
    Some models (the bge family) were trained with an instruction
    prefixed to retrieval queries; query_prefix carries it, applied to
    questions only, never to documents."""

    def __init__(self, model_name, query_prefix=""):
        self.model = SentenceTransformer(model_name)
        self.query_prefix = query_prefix

    def embed_documents(self, texts):
        return [vector.tolist() for vector in self.model.encode(texts)]

    def embed_query(self, text):
        return self.model.encode(self.query_prefix + text).tolist()
