---
tags: [project, operations]
---

# Running it

The path from clone to answers is two commands and one key. This note
is the operational surface of everything described in
[[02-architecture]].

## Setup

```bash
git clone <repo>
cp .env.example .env      # paste your OPENAI_API_KEY
docker compose up -d      # the stack rises, the index builds itself
make init-db              # the three postgres tables
```

The app is at localhost:8501, Jupyter at 8888, Grafana at 3000,
Elasticsearch at 9200. Without any further configuration the
assistant answers over this demo vault; the one-shot ingest indexed
it during the up (see [[03-ingestion-pipeline]]).

The only mandatory value in `.env` is the api key. Everything else is
optional with sensible defaults: `VAULT_PATH` points at a real vault
instead of the demo (on WSL, `C:\` becomes `/mnt/c/`); the
`LLM_BASE_URL` and `LLM_MODEL` pair, set together, switches from the
OpenAI api to a local ollama model (`docker compose --profile ollama
up -d`, then pull a model); port overrides exist for machines where a
default is taken. The environment basics are the same as
[[02-environment]] from the course.

One rule to remember: containers read `.env` at creation, so applying
a change is a recreate (`make reload-app`, `make reload-notebook`),
never a plain restart. Restart keeps the old snapshot of the
environment.

## The make targets

```
make up / down        start and stop the stack
make ingest           reindex the vault (the same one-shot up runs)
make init-db          create the tables, idempotent
make reset-db         rebuild the tables, ERASES the history
make check-db         peek at the last conversations
make reload-app       apply .env changes to the app
make reload-notebook  same for jupyter (kills the kernel, save first)
make logs / urls      follow the app logs, print the addresses
```

## Adding and changing content

Drop markdown files in the demo vault (subfolders work), run `make
ingest`, ask about them: the index always mirrors the folder.

## Pointing the assistant at your own notes

Three steps switch from the demo to a real vault. First, set the path
in `.env`:

```
VAULT_PATH=/mnt/c/Users/you/Documents/your-vault
```

Any folder of markdown files works, an Obsidian vault or not; on WSL,
a Windows path like `C:\Users\you` becomes `/mnt/c/Users/you`. Second,
`make ingest`: the one-shot reads the new mount and rebuilds the index
from your notes. Third, `make reload-app`, so the app container is
recreated with the new mount too. Ask something only your notes know
to confirm the switch.

Coming back to the demo is the same in reverse: comment the
`VAULT_PATH` line out, `make ingest`, `make reload-app`. In both modes
the vault is mounted read only, so the assistant can never modify a
note.

## Reproducing the results

Every number quoted in these notes is reproducible. The ground truth
is committed at `data/claude_ground_truth.json`, and because this demo
vault contains the same course notes the questions target, the
retrieval evaluation runs on a fresh clone. One honest caveat,
measured: evaluated over the full demo vault the hit rate lands around
0.68, because these documentation notes discuss the same topics and
compete for top-10 slots; evaluated over the `llm-zoomcamp-2026/`
subfolder alone, the original corpus, the reported numbers reproduce. The four stable notebooks
(ingestion pipeline, retrieval evaluation, generation evaluation,
database logging) run top to bottom against the package and print the
same tables and charts the project reports; the expensive measurements
(the full rerank pass, the model comparison) are cached or recorded
with their reproduction commands next to them.
