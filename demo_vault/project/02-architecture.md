---
tags: [project, infrastructure]
---

# Architecture

The project runs entirely on Docker. One image holds the Python code
and serves three roles: the web app, a Jupyter environment and a
one-shot ingestion job. Around it, the services that do the heavy
lifting: Elasticsearch for search, Postgres for logging, Grafana for
dashboards, and Ollama serving local LLMs — part of the default
stack, so the assistant answers even when no API key exists.
Everything personal (API key, vault path, model choice) lives in a
`.env` file, never in code — and nobody is required to edit it by
hand: the launcher writes the vault path ([[11-starting-automated]])
and an API key can be typed straight into the app's sidebar. The
compose patterns come from [[13-docker-compose]].

## The services

Elasticsearch is the retrieval engine. It does BM25 text search and
dense vector kNN over the note chunks, fused later in the app with
reciprocal rank fusion. One gigabyte of heap is enough for a personal
vault, and a named volume keeps the index alive across container
recreations. A healthcheck marks the moment it is actually ready to
answer, which matters because starting is not being ready: it takes
around 30 seconds to boot.

Postgres is the conversation and feedback log. The database is created
on first boot by `POSTGRES_DB`, and the app creates its own tables
when it starts, idempotently — there is no init step to remember.
Grafana reads it directly; the datasource and dashboards are
provisioned from files in the repo, so a fresh clone gets the same
panels without clicking anything.

Ollama is the local model server, the reason the assistant works with
no key at all. It is born useful: its entrypoint pulls a basic model
(`qwen2.5:1.5b`) on the first start, so a fresh clone can answer
before any account or download decision is made. Better models are
one Download click away in the app's sidebar, and a named volume
keeps them across recreations. Only one model stays resident at a
time (`OLLAMA_MAX_LOADED_MODELS: 1`), so when a gpu exists the active
model gets the whole card; acceleration itself is a two-line
override, explained in [[09-running-it]].

The app is Streamlit. The vault is mounted read only at `/vault`: the
assistant reads notes, it never touches them. The package folder is
bind mounted over the image copy, so code edits apply live without
rebuilding.

The ingest service is a one-shot: same image, but the command runs the
ingestion script instead of Streamlit. It waits for the Elasticsearch
healthcheck, indexes whatever is mounted at `/vault`, prints the
counts and exits. Bringing the stack up builds the index by itself;
`make ingest` reruns the same job on demand.

## One image, three containers

There are two ways to put code inside a container, and they behave
very differently. COPY in the Dockerfile happens at build time: it
bakes a frozen snapshot into the image, so the image is self contained
and someone can run it without cloning the repository. A bind mount in
the compose file happens at run time: it maps a real folder of the
host into the container, both sides seeing the same files, live.

This project uses both on purpose. The image copies the package into
`/app`, making it distributable; the app service bind mounts the same
folder on top, so during development every edit is live and no rebuild
is needed. The notebook service mounts the whole repository at
`/project`, which is the workshop: notebooks, package, data and the
demo vault, all editable in one place. The three containers split
roles, but what runs in one is exactly what runs in the others,
because the image underneath is the same.

## Configuration

Config flows in three layers, each with its own speed of change. Code
changes many times a day, so it is a bind mount. Dependencies change
weekly, so they are an image layer, cached by copying
`requirements.txt` before the code — every one of them pinned to the
exact version the results were measured on, and the heaviest one
tamed: torch installs from its cpu-only wheel index, because
embeddings run on cpu in this container and gpu inference belongs to
the ollama service (the full reasoning in [[10-trade-offs]]). Config
changes rarely, so it is environment variables: the compose declares
a default for every value (`${EMBED_MODEL:-all-MiniLM-L6-v2}`), and
the `.env` file overrides what is personal. A fresh clone works with
nothing at all: no key (the basic local model answers), no `.env`
(every value has a default), no manual step (the launcher, or a plain
`docker compose up -d`, assembles the rest).

One rule learned the hard way: containers read `.env` at creation
time, so applying a change is a recreate (`make reload-app`), never a
plain restart. Restart keeps the old snapshot of the environment.

Next: [[03-ingestion-pipeline]].
