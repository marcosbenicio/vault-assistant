---
tags: [project, operations]
---

# Starting it, the manual way

The automated door ([[11-starting-automated]]) needs nothing from
this note. This one is for whoever opens the project to *change* it:
the compose lifecycle by hand, the `.env` contract in full, and the
make toolbox that names every routine gesture. The architecture
behind the services is [[02-architecture]].

## The two commands

```bash
git clone https://github.com/marcosbenicio/vault-assistant
cd vault-assistant && docker compose up -d
```

What that first `up` does, in order, with no other step required:
Elasticsearch rises first and the other services wait on its
healthcheck; the one-shot ingest container reads whatever vault is
mounted, cleans, chunks, embeds and indexes it, prints its counts and
exits; the ollama service pulls its basic model (`qwen2.5:1.5b`) so a
local answerer exists before any key or account does; the app creates
the postgres tables on its own first boot, idempotently — there is no
init or migration step. The first `up` pays the downloads (images
plus the basic model); every later `up` is seconds, because
everything lives in named volumes.

Stopping is `docker compose down` — the data survives in the volumes.
`docker compose down --volumes` is the true reset, index and
conversation history included; nothing in normal use ever needs it.

## The .env contract

`.env` exists for overrides only: every value has a working default
without it, which is what lets a fresh clone start with no
configuration at all. What it can override, grouped by why you would:

- `OPENAI_API_KEY` — only if you prefer a file over pasting the key
  in the sidebar (the sidebar field wins when both exist, and the key
  never reaches the database or the logs either way).
- `VAULT_PATH` — the vault being answered from; absent means the
  committed demo vault. Written for you by the launcher's question or
  by `make vault` — hand-editing is never required.
- `LLM_MODEL` — the default selection in the app's model list; the
  stack default is `gpt-5.6-luna`, the measured choice
  ([[07-generation-and-judge]]).
- `LLM_BASE_URL`, `LLM_API_KEY` — an *external* OpenAI-compatible
  server (LM Studio, ollama on the host, vLLM) instead of the bundled
  ollama; the key only when that server validates one.
- `EMBED_MODEL`, `ES_INDEX` — the embedding model and index name the
  measurements were made with; changing them means re-indexing.
- `APP_PORT`, `JUPYTER_PORT`, `GRAFANA_PORT`, `ES_PORT`,
  `POSTGRES_PORT`, `OLLAMA_PORT` — for machines where a default port
  is taken.
- `JUPYTER_TOKEN`, `POSTGRES_USER`, `POSTGRES_PASSWORD`,
  `GRAFANA_PASSWORD` — the service credentials, default dev values.

The rule learned the hard way, worth repeating from
[[02-architecture]]: containers read `.env` at creation time, so
applying a change is a recreate (`make reload-app`,
`make reload-notebook`), never a plain restart — restart keeps the
old snapshot of the environment.

## The make toolbox

Every routine gesture has a name, so none of them has to be
remembered as a compose incantation:

```
make up / down        start and stop the stack
make build            rebuild the image (only when requirements change)
make ingest           reindex the vault (the same one-shot up runs)
make vault VAULT=...  switch vaults in one command (VAULT=demo goes back)
make reload-app       apply .env changes to the app (a quick blink)
make reload-notebook  same for jupyter (kills the kernel, save first)
make init-db          create the tables by hand (the app already does this)
make reset-db         DROP and rebuild the tables: erases the history
make check-db         peek at the last conversations in postgres
make logs             follow the app logs live
make urls             print every service address, honoring .env
make theme-kimbie / theme-friedrich / theme-default
                      switch the app's color palette
```

`make urls` is the map of the whole stack: the app, Jupyter with its
token, Grafana with its login, Elasticsearch — each honoring any port
override in `.env`.

## Resetting the database, on purpose

Table creation is gentle by default: the app runs `create_tables()`
on every boot and `IF NOT EXISTS` makes that a no-op on an existing
database. The gentle path has a blind spot, though — it checks that
tables *exist*, not that they match the current code, so after a
schema change an old database and a new app disagree and inserts
fail. The explicit way out is `make reset-db`, which runs the same
module with its `--recreate` flag: the satellite tables drop first
(feedback and judgements point at conversations by foreign key), then
the fact table, then everything rebuilds empty. It erases the whole
conversation history, which is exactly why it is a separate command
that never runs as part of setup — the same gentle-by-default,
destructive-by-name pattern the search index uses
([[08-monitoring-stack]]).

## Your own notes, by hand

`make vault VAULT=/abs/path` is the one-command switch: it validates
the path, writes `VAULT_PATH` into `.env`, reindexes and recreates
the app with the new mount. Behind it are three steps that can be run
separately when something needs inspecting: set `VAULT_PATH` in
`.env`; `make ingest` so the one-shot rebuilds the index from the new
mount; `make reload-app` so the app container is recreated with the
new mount too. On plain Windows without a POSIX shell, the same two
docker commands are `docker compose run --rm ingest` and
`docker compose up -d --force-recreate app`. A folder without
markdown notes is refused before anything destructive happens — the
guard is in the pipeline itself ([[03-ingestion-pipeline]]).

## The development loop

The code is bind-mounted over the image copy, so edits apply live: a
change to the package or the app needs only a browser rerun, never a
rebuild. A change to `requirements.txt` is the exception — `make
build` rebuilds the image, where every dependency is pinned to the
measured version and torch installs from its cpu-only wheel index
(the reasoning in [[10-trade-offs]]). The gpu, when wanted, is the
two-line override described in [[09-running-it]]; the evaluation
notebooks live on the Jupyter service and run against the same
package the app imports, which is what keeps every number in these
notes re-runnable.
