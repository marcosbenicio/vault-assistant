# 1. Project Introduction

Vault Assistant is a local-first RAG application I built to query a collection of Markdown notes in natural language.

The knowledge base is simply a folder of `.md` files. I originally designed it around an Obsidian vault, but Obsidian itself is not part of the runtime: the application reads Markdown directly from the filesystem. Frontmatter, wikilinks and the folder structure are parsed when available, but ordinary Markdown notes work without any Obsidian-specific structure. To browse or edit the vault with Obsidian (optional), download it from [https://obsidian.md/download](https://obsidian.md/download).

The pipeline cleans and chunks the notes, generates embeddings, and indexes both text and vectors in Elasticsearch. At query time, the application retrieves the most relevant chunks, sends them as context to the selected LLM, and returns the answer together with the source notes used to produce it.

The default Docker stack also includes Ollama, so the application works without an OpenAI API key. In local mode, retrieval and generation stay on the machine. If an OpenAI model is selected, only the retrieved context needed to answer the question is sent to the API. In either case, the vault itself is mounted read-only.

This is my final project for **LLM Zoomcamp 2026**.
