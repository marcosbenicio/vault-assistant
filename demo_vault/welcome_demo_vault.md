---
tags: [demo, tutorial]
---

# Welcome to the demo vault

This folder is the knowledge base the assistant uses when you have not
pointed it at a vault of your own. You do not need Obsidian installed,
or even to know what Obsidian is: a vault is just a folder of markdown
files, and this is one.

## How it works

Every `.md` file here is a note. When the stack starts (or when you
run `make ingest`), the ingestion pipeline reads all of them, cleans
the text, splits it into chunks, embeds each chunk and indexes
everything into Elasticsearch. From that moment the app at
`localhost:8501` answers questions using ONLY what these notes say.

Notes reference each other with wikilinks, like this one pointing to
[[01-intro]]. Those links become the note graph that ingestion
extracts and stores. A yaml header like the one at the top of this
file adds tags.

## What is in here

Three areas, densely interlinked:

- `llm-zoomcamp-2026/`: the course notes of LLM Zoomcamp 2026, the
  same corpus the project's retrieval evaluation targets, which makes
  the reported numbers reproducible on a fresh clone.
- `concepts/`: the raw reference material, the explanatory markdown of
  the four course notebooks transcribed verbatim: [[rag]],
  [[rag_vector_search]], [[evaluation]] and [[monitoring]].
- `project/`: the project itself explained note by note, from
  [[01-intro]] through architecture, ingestion, cleaning, search,
  both evaluations, monitoring and operations, each one linking the
  course material it builds on.

## Try it

Open the app and ask questions these notes can answer:

- What is RAG and why not just ask the model directly?
- What is the difference between text search and vector search?
- How does reciprocal rank fusion combine two rankings?
- Why are notes split into overlapping chunks?
- Which retrieval method does this project use by default, and why?
- What did the cross-encoder reranker improve, and what did it cost?
- How does the LLM judge evaluate answers, and who audited the judge?
- What gets logged to postgres after every answer?

Check the Sources panel under each answer: you will see exactly which
notes and chunks grounded it.

## Add your own content

Drop any markdown files in this folder (subfolders work too), then:

    make ingest

Ask about your new content in the app. That is the whole loop — and
it also works without a terminal: the **Reingest vault** button in
the app's sidebar runs the same pipeline in place. To remove
something, delete the file and reingest again: the index is rebuilt
from scratch every time, so it always mirrors the folder exactly.

## Use a real vault instead

When you want the assistant reading your own notes, one command from
the project root does everything:

    make vault VAULT=/abs/path/to/your/notes

It stores the path in `.env`, indexes your notes and reconnects the
app (on WSL, a Windows path like `C:\` becomes `/mnt/c/`). This demo
folder stays untouched, and `make vault VAULT=demo` switches back
anytime. The full story, including the manual steps and the Windows
variants, is in [[09-running-it]].
