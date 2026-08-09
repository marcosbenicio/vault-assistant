import os

import frontmatter
from datetime import datetime, timezone
from pathlib import Path
from elasticsearch import Elasticsearch
from elasticsearch.helpers import bulk

from cleaner import Document, NoteCleaner
from embeddings import SentenceTransformerEmbeddings

class SlidingWindowSplitter:
    """Splits Documents into overlapping chunks.

    Same interface as a LangChain text splitter: split_documents(docs)
    returns a list of chunk Documents. chunk_size and chunk_overlap
    follow the LangChain vocabulary; the window advances by chunk_size
    minus chunk_overlap characters.
    """

    def __init__(self, chunk_size=2000, chunk_overlap=1000):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

    def split_text(self, text):
        """Cut one text into (start, piece) windows. The final window
        ends the loop early so no trailing suffix duplicates appear."""
        step = self.chunk_size - self.chunk_overlap
        pieces = []
        start = 0
        while start < len(text):
            end = min(start + self.chunk_size, len(text))
            pieces.append((start, text[start:end]))
            if end == len(text):
                break
            start += step
        return pieces

    def split_documents(self, documents):
        """Split every Document, each chunk inheriting its parent
        metadata plus its start offset."""
        chunks = []
        for doc in documents:
            for start, piece in self.split_text(doc.page_content):
                chunks.append(Document(
                    page_content=piece,
                    metadata={**doc.metadata, "start": start},
                ))
        return chunks

class VaultLoader:
    """Loads a vault of markdown notes as Documents.

    Same interface as a LangChain document loader: lazy_load() yields
    Documents one at a time, load() returns them as a list. Hidden paths
    and the _playground staging area are skipped, and the glob runs on
    every call so new notes appear without rebuilding the loader.
    """

    def __init__(self, vault_path, cleaner):
        self.vault_path = Path(vault_path)
        self.cleaner = cleaner

    def iter_notes(self):
        """Yield every note file in stable order."""
        for path in sorted(self.vault_path.rglob("*.md")):
            parts = path.relative_to(self.vault_path).parts
            if any(p.startswith(".") or p == "_playground" for p in parts):
                continue
            yield path

    def load_note(self, path):
        """Read one note file into a Document."""
        post = frontmatter.load(path)
        content, graph_edges, external_links = self.cleaner.clean(post.content)
        rel = path.relative_to(self.vault_path)

        tags = post.metadata.get("tags") or []
        if isinstance(tags, str):
            tags = [tags]

        return Document(
            page_content=content,
            metadata={
                "source": str(rel),
                "title": path.stem,
                "folder": str(rel.parent) if str(rel.parent) != "." else "",
                "tags": tags,
                "graph_edges": dict(graph_edges),
                "external_links": external_links,
                "last_modified": datetime.fromtimestamp(
                    path.stat().st_mtime, tz=timezone.utc
                ).isoformat(),
            },
        )
            
    def lazy_load(self):
        """Yield every note as a Document, one at a time. A note that
        fails to parse is reported and skipped: one sick note must not
        kill the whole vault."""
        for path in self.iter_notes():
            try:
                yield self.load_note(path)
            except Exception as error:
                print(f"skipping {path.name}: {error}")


    def load(self):
        """Load the whole vault as a list of Documents."""
        return list(self.lazy_load())
    
    
class ElasticsearchIndexer:
    """Writes chunk Documents into Elasticsearch.

    The index stores flat fields, so metadata is flattened at write time:
    the graph_edges counter becomes a keyword array with one entry per
    citation, which keeps the edge weights inside a flat field (consumers
    rebuild the counts with Counter). With add_context_header on, folder
    and title are prepended to the text before embedding, so bm25 and the
    vector both absorb where the note lives in the vault.
    """

    def __init__(self, es_client, embeddings, index, add_context_header=True):
        self.es_client = es_client
        self.embeddings = embeddings
        self.index = index
        self.add_context_header = add_context_header

    def create_index(self, recreate=False):
        if recreate:
            self.es_client.indices.delete(index=self.index, ignore_unavailable=True)
            
        self.es_client.indices.create(
            index=self.index,
            mappings={
                "properties": {
                    "content":        {"type": "text"},
                    "title":          {"type": "text"},
                    "path":           {"type": "keyword"},
                    "folder":         {"type": "keyword"},
                    "tags":           {"type": "keyword"},
                    "graph_edges":    {"type": "keyword"},
                    "external_links": {"type": "keyword"},
                    "start":          {"type": "integer"},
                    "modified_at":    {"type": "date"},
                    "embedding":      {"type": "dense_vector", "dims": 384,
                                       "index": True, "similarity": "cosine"},
                }
            },
        )
    
    def index_documents(self, documents):
        """Embed everything in one batched call, then bulk-write: the model
        parallelizes inside a batch and elasticsearch takes one request,
        which beats per-chunk calls by an order of magnitude."""

        texts = []
        for doc in documents:
            text = doc.page_content
            if self.add_context_header:
                meta = doc.metadata
                text = f"[{meta['folder']} / {meta['title']}]\n{text}"
            texts.append(text)

        vectors = self.embeddings.embed_documents(texts)

        actions = []
        for doc, text, vector in zip(documents, texts, vectors):
            meta = doc.metadata
            edges = meta["graph_edges"]
            actions.append({
                "_index": self.index,
                "_id": f"{meta['source']}::{meta['start']}",
                "_source": {
                    "content": text,
                    "title": meta["title"],
                    "path": meta["source"],
                    "folder": meta["folder"],
                    "tags": meta["tags"],
                    "graph_edges": [name for name, count in edges.items()
                                    for _ in range(count)],
                    "external_links": meta["external_links"],
                    "start": meta["start"],
                    "modified_at": meta["last_modified"],
                    "embedding": vector,
                },
            })
        bulk(self.es_client, actions)
        
        
        
if __name__ == "__main__":
    model_name = os.getenv("EMBED_MODEL", "all-MiniLM-L6-v2")
    query_prefix = ("Represent this sentence for searching relevant passages: "
                    if "bge" in model_name else "")

    cleaner = NoteCleaner()
    loader = VaultLoader(os.getenv("VAULT_PATH", "/vault"), cleaner)
    splitter = SlidingWindowSplitter(chunk_size=2000, chunk_overlap=1000)
    embeddings = SentenceTransformerEmbeddings(model_name, query_prefix)
    es = Elasticsearch(os.getenv("ELASTIC_HOST", "http://elasticsearch:9200"))
    indexer = ElasticsearchIndexer(es, embeddings,
                                   index=os.getenv("ES_INDEX", "obsidian_notes"))

    documents = loader.load()
    chunks = splitter.split_documents(documents)
    print(f"{len(documents)} notes -> {len(chunks)} chunks")

    indexer.create_index(recreate=True)
    indexer.index_documents(chunks)
    es.indices.refresh(index=indexer.index)
    print("indexed:", es.count(index=indexer.index)["count"])
