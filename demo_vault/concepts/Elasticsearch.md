
Elasticsearch is a search server. It stores JSON documents in indexes and answers queries over them by HTTP. Everything is a REST call: the Python client is a thin wrapper, and any command below can also be a curl or a browser url. My instance runs at localhost:9200 and holds one index, obsidian_notes, with one document per note chunk.

## The three concepts

An index is a collection of documents, like a table. A document is one JSON object with an id, like a row. A field is one key of that JSON, like a column, and every field has a type declared in the mapping. The type decides what you can do with the field:

- text: broken into words and indexed for full text search with bm25. My content and title fields. You search these, you do not filter on them.
- keyword: stored as an exact value. My path, folder, tags, graph_edges and external_links. You filter, aggregate and sort on these, you do not full text search them.
- dense_vector: an embedding, used by knn similarity search. My embedding field with 384 dimensions.
- date and integer: what they sound like. My modified_at and start.

## The mapping is a contract

The mapping is declared once, when the index is created, and every document written afterwards must fit it. It is not optional metadata: the type decides how the field is processed at write time (chopped into terms, stored whole, indexed as a vector), so it cannot change on a living index. Changing your mind about a field means delete, create again, reingest everything.

Creating an index with its mapping:

```python
es.indices.create(index="obsidian_notes", mappings={
    "properties": {
        "content":     {"type": "text"},
        "path":        {"type": "keyword"},
        "start":       {"type": "integer"},
        "modified_at": {"type": "date"},
        "embedding":   {"type": "dense_vector", "dims": 384,
                        "index": True, "similarity": "cosine"},
    }
})
```

The dense_vector line shows why the contract exists: the engine needs to know the vector size and the distance metric before the first vector arrives. The dims value must match whatever embedding model you use, and the model can change under you, so treat this pair as one decision.


The recreate pattern, delete then create, is how a schema change ships. ignore_unavailable makes the delete safe to run whether or not the index exists, so the same cell works on a fresh machine and on a dirty one:

```python
es.indices.delete(index="obsidian_notes", ignore_unavailable=True)
```


## Ids are yours to choose

If you pass an id when indexing, writing the same id again overwrites the document instead of adding a new one. A deterministic id, built from the content's identity, makes ingestion idempotent: running it twice leaves the index identical, no duplicates. Mine is the note path plus the chunk offset:

```python
es.index(index="obsidian_notes",
         id=f"{meta['source']}::{meta['start']}",
         document={...})
```

Without an explicit id Elasticsearch generates a random one, and every rerun of the ingestion doubles the index silently.

## Rich metadata in flat fields

A keyword field accepts an array of strings, and that is enough to smuggle structure through. My graph edges are a Counter, note name to citation count, but the index only takes flat values. Flattening by repetition keeps the weights: the name appears once per citation, and any consumer rebuilds the Counter from the array.

```python
"graph_edges": [name for name, count in edges.items()
                for _ in range(count)]
```

So {'05-search': 4} is stored as four repetitions of '05-search', and Counter(field) on the way out restores the original dict.

## What the index does not tell you

The index remembers nothing about how it was built. It does not know which embedding model produced its vectors, or which version of the cleaning code produced its text. Two traps follow from this.

Changing the embedding model always requires a full reingest: vectors from different models live in incompatible spaces, and searching with a query vector from one model over an index built with another returns garbage without any error, even when both models share the same dimension count.

A count-based freshness check (reingest only when the number of chunks changed) is blind to both cases above. The chunk count stays identical when field names change or the model changes, so the guard happily says up to date while serving a stale index. Quantity is not identity.

## Looking around

List the indexes, the ls of elasticsearch:

```python
es.cat.indices(format="text")
```

See the declared schema of an index:

```python
es.indices.get_mapping(index="obsidian_notes")
```

Count documents:

```python
es.count(index="obsidian_notes")
```

Fetch one document by its exact id:

```python
es.get(index="obsidian_notes",
       id="llm-zoomcamp-2026/01-agentic-rag/14-agentic-loop.md::0")
```

## Searching

The heart of it. A match query runs bm25 over one text field, scoring every document by how rare and frequent the query words are inside it:

```python
es.search(index="obsidian_notes", size=5,
          query={"match": {"content": "agentic loop"}})
```

multi_match searches several fields at once, and a caret boosts one field over another, title hits worth double here:

```python
query = {"multi_match": {
    "query": "agentic loop",
    "fields": ["content", "title^2"],
    "type": "best_fields",
}}
```

bool combines clauses. must scores like a normal search; filter only cuts, never affects the score, and works on keyword fields:

```python
query = {"bool": {
    "must": {"match": {"content": "evaluation metrics"}},
    "filter": {"term": {"folder": "llm-zoomcamp-2026/04-evaluation"}},
}}
```

Two habits worth keeping: pass _source with the fields you want back, otherwise the whole document comes, embedding included; and remember match_all as the give me everything query for exploration.

## Reading a response

Every search answer has the same anatomy:

```
hits.total.value    how many documents matched
hits.hits[]         the results, each one with:
  _id               the document id
  _score            the bm25 relevance score
  _source           the stored document
```

## Aggregations

The group by of elasticsearch. size=0 skips the documents and returns only the counts:

```python
es.search(index="obsidian_notes", size=0, aggs={
    "by_folder": {"terms": {"field": "folder"}}
})
```

## From the terminal or the browser

The same calls as raw HTTP:

```bash
curl -s localhost:9200/_cat/indices?v
curl -s localhost:9200/obsidian_notes/_count | jq
curl -s "localhost:9200/obsidian_notes/_search?q=content:agentic&pretty"
```

And the browser is a valid client too, this url returns pretty json:

```
http://localhost:9200/obsidian_notes/_search?q=agentic&pretty
```


