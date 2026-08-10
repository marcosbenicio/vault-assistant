---
tags: [project, operations]
---

# Running it

The path from clone to first answer is two commands and a browser
tab, and that simplicity is a design result, not luck: every piece of
the stack builds itself. This note is the operational surface of
everything described in [[02-architecture]].

## From clone to first answer

```bash
git clone <repo> && cd obsidian-assistant
docker compose up -d
```

That is the whole setup. No config file needs to exist: the compose
carries a working default for every value, and the pieces assemble
themselves during the first `up`, in order. Elasticsearch rises first
(the other services wait on its healthcheck); the one-shot ingest
container then reads the committed demo vault, cleans, chunks, embeds
and indexes it, prints its count and exits — the index is never a
manual step. The local llm service pulls its basic model
(`qwen2.5:1.5b`, about 1 GB) so a model exists even with no api key.
The app creates the three postgres tables on its first boot,
idempotently — there is no migration step. The first `up` therefore
pays some minutes of downloads (docker images plus the basic model);
every later `up` is seconds, because everything lives in volumes.

Then open http://localhost:8501 and pick a lane:

1. **With an OpenAI key**: paste it in the sidebar field — memory
   only, no file edited — and ask. Answers come from `gpt-5.6-luna`,
   the measured default, in a few seconds.
2. **Without any key**: just ask. The basic local model answers,
   slower and simpler, fully private. Better local models are one
   Download click away (the sidebar section below covers the ladder).

Everything after that is optional and one gesture each, in whatever
order matters to you: a better local model (Download button in the
sidebar), gpu acceleration (`cp docker-compose.gpu.yml
docker-compose.override.yml`, section below), your own notes instead
of the demo (`make vault VAULT=/abs/path`, section below), new
content into the index (the Reingest button, or `make ingest`).

The other services ride along at their own ports: Jupyter at 8888
(the evaluation notebooks), Grafana at 3000, Elasticsearch at 9200,
Postgres at 5432. `make urls` prints them all with any overrides
applied.

Why this is the project's strong point, spelled out: reproducibility
is a graded criterion, but more importantly it is what makes every
other claim in these notes checkable. The evaluation notebooks run
against the same package the app uses, the demo vault documents the
system it feeds, and a reviewer goes from `git clone` to
interrogating the assistant about its own trade-offs in the time a
coffee takes. Nothing needs to be believed on faith; everything can
be re-run.

The `.env` file exists for overrides only, and every value has a
sensible default without it: the api key (if you prefer it over the
sidebar field), `VAULT_PATH` (written by `make vault`), `LLM_MODEL`
(the default selection in the app), `LLM_BASE_URL` (an external
OpenAI-compatible server instead of the bundled ollama), and port
overrides for machines where a default is taken. The environment
basics are the same as [[02-environment]] from the course.

One rule to remember: containers read `.env` at creation, so applying
a change is a recreate (`make reload-app`, `make reload-notebook`),
never a plain restart. Restart keeps the old snapshot of the
environment.

## The sidebar

Every knob the assistant has lives in the Streamlit sidebar, under
Settings. The design rule behind it: anything a reviewer would
otherwise have to edit `.env` for should be one click in the browser,
and the interface always says what is wired, what is being called and
what is off. Six controls, top to bottom.

**OpenAI API key** is a password field. The resolution order is:
a key typed here wins, otherwise the `OPENAI_API_KEY` from `.env` is
used, and with neither the app runs on local models only. The typed
key lives in the session's memory, masked on screen, never written to
the database or the logs. This field is the reproducibility shortcut:
someone evaluating the project can clone, `docker compose up`, paste a
key in the browser and ask, without editing any file. A wrong key
fails with a clean error message under the question box; deleting it
from the field recovers immediately.

**Answer model** selects who writes the answers. The list has two
origins. The api models come from the price table in `metrics.py`,
the single place in the project that knows about pricing, so a model
appears here with its cost accounted for in the caption under every
answer. The local models are discovered live: the app queries the
bundled ollama service and lists every chat model already pulled,
marked `(local)`; embedding-only models are filtered out because they
cannot chat. The
default selection honors the `LLM_MODEL` from `.env`, exactly as the
environment documentation promises, falling back to the stack default
`gpt-5.6-luna`. That default is a measured choice, not a taste: 82%
of its answers were judged RELEVANT against 76% for gpt-5.4-mini and
60% for the local qwen2.5:7b (see [[07-generation-and-judge]]); the
judge and the rewriter stay on gpt-5.4-mini, the validated
deterministic pair. The
local models stay available as the free and private mode, and the
caption prices every answer so the trade-off is visible per question:
switching to a cheaper api model shows up in dollars immediately.

**Query rewriter (fused search)** toggles the translator in front of
retrieval. On, an LLM rewrites the question into the vault's
vocabulary at temperature zero, hybrid search runs twice, once with
the original and once with the rewritten question, and the two
rankings merge with reciprocal rank fusion. This is the largest
measured improvement in the project: hit rate 0.755 to 0.885 on the
ground truth, hard questions 0.68 to 0.86, 28 questions rescued and 2
broken, for one cheap extra llm call of about 0.7 seconds (the full
story in [[06-retrieval-evaluation]]). The rewriter is built to be
absent, never in the way: if its call fails, the original question is
searched untouched. Toggling it off removes `fused` from the search
mode list, because fused without a rewriter would just be hybrid run
twice. With an api key the rewriter uses `gpt-5.4-mini`, the setup
every number above was measured on; without one it runs on the
selected local model, which works but was never benchmarked.

**LLM judge** toggles the automatic evaluator. On, a second llm call
reads every question and answer pair after the answer is produced and
returns a structured verdict, reasoning first, then RELEVANT,
PARTLY_RELEVANT or NON_RELEVANT. The verdict is written to the
judgements table and shown at the end of the answer's caption. The
judge is an observer by design: it runs after the answer exists, and
a judge failure can only cost the verdict, never the answer. The
caption always tells the truth about it, with three visible states:
the verdict itself, `judge: off` when the toggle is off, and
`judge: failed` when the call errored, so a broken judge can never be
mistaken for a silent approval. Off also means no row in the
judgements table, so the relevance panel in Grafana covers only the
answers the judge actually saw.

**Search mode** selects the retrieval strategy, and the five options
are the project's measured history kept comparable on purpose: `fused`
is the default (the rewriting design that won), `hybrid` is the base
it builds on (0.755 hit rate), `rerank` is the quality mode (a
cross-encoder rescores 30 hybrid candidates, best ordering gain,
about 4 seconds per question), `text` is plain BM25 and `vector` is
plain kNN, each strong exactly where the other is blind. Switching
modes here reproduces live what the retrieval evaluation notebook
measured offline, and every conversation row records which mode
produced it, so the modes can be compared on the dashboards later.
On a fresh install the first rerank question downloads the
cross-encoder model (about 80 MB), once.

**Folder** narrows the search to one subtree of the vault. The
options are discovered from the index itself, an aggregation over the
folder field collapsed to top-level folders. The filter is an exact
subtree match, the folder itself or anything under it, so scoping to
`project` can never leak in a sibling like `project-archive`. With a
scope selected, chunks from anywhere else simply do not enter the
candidate list, and the page caption shows the active folder next to
the model and search mode.

**Local models** is the expander below the controls: the ladder of
local models the project curates, lightest to heaviest, each with its
download size and the ram it needs. The stack is born with
`qwen2.5:1.5b`, the basic one; anything better is one Download click
away — a progress bar fills in the sidebar, the download runs on the
server side (it survives page refreshes), and the finished model
joins the Answer model list marked `(local)`. The expander's title
also reports whether the local models are running on GPU or CPU.
Above `qwen2.5:7b-instruct`, the only local model the project
benchmarked, the bigger entries are labeled as such.

The gpu section below covers acceleration for these local models in
detail.

## The gpu, optional

The stack is CPU-only by default so it runs anywhere; an NVIDIA card
turns local models from patient to instant. Enabling it is two
commands, the same idiom as `.env.example` becoming `.env`:

```bash
cp docker-compose.gpu.yml docker-compose.override.yml
docker compose up -d
```

Docker compose merges `docker-compose.override.yml` automatically
when it exists; the file only adds a device reservation handing the
NVIDIA gpu to the ollama service. It is gitignored on purpose:
personal hardware configuration never reaches the repo.

The override's whole content, worth reading before copying:

```yaml
services:
  ollama:
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: all
              capabilities: [gpu]
```

Line by line. `services: ollama:` — an override patches by service
name, so only the ollama service changes and the rest of the stack is
untouched; the file does not repeat anything the base compose already
says. `deploy.resources.reservations.devices` is compose's syntax for
handing hardware devices to a container: a reservation, meaning the
container will not start without it. `driver: nvidia` routes the
request through the nvidia-container-toolkit runtime. `count: all`
exposes every gpu in the machine — on a laptop that is the one card;
on a multi-gpu box, `count: 1` takes the first, or `device_ids:
["1"]` (replacing `count`) pins a specific card by its `nvidia-smi`
index. `capabilities: [gpu]` requests compute capability, the minimum
the toolkit accepts. Nothing here names a model or a memory size:
which model uses how much VRAM is ollama's runtime decision (the
sizing table below).

The same shape extends to any other service: to hand the gpu to a
second container one day, the identical block under that service's
name in the same file is all it takes.

Prerequisites, checked in order:

1. An NVIDIA gpu with a current driver: `nvidia-smi` on the host must
   print the card. On WSL2, the WINDOWS driver provides CUDA to
   Linux; nothing extra is installed inside WSL.
2. The nvidia-container-toolkit, which lets Docker hand gpus to
   containers: `docker info | grep -i nvidia` should list an `nvidia`
   runtime. Without it, the override makes `docker compose up` fail
   with "could not select device driver" — install the toolkit or
   remove the override.

Verifying it worked, three independent ways: `docker exec
assistant_ollama nvidia-smi` prints the card from inside the
container; `docker exec assistant_ollama ollama ps` shows the loaded
model with `100% GPU` as its processor; and the app's Local models
expander title reads `(GPU)` instead of `(CPU)` once a local model
has answered.

What to expect: the quality model measured at ~70 seconds per answer
on CPU (qwen2.5:7b) drops to a few seconds when it fits entirely in
VRAM. Sizing rule of thumb per model, download size roughly equal to
the VRAM it wants: the basic 1.5b fits in ~2 GB, the 3b in ~4 GB, the
7b in ~6-8 GB, the 14b wants ~10-12 GB and the 20b-class MoE models
~14-16 GB. A model larger than the free VRAM still runs, split
between gpu and system ram, at intermediate speed. Two related
settings in the compose keep this healthy: `OLLAMA_MAX_LOADED_MODELS:
1` evicts the previous model when switching, so the active one always
gets the whole card (on an 8 GB gpu, two resident models would
suffocate it), and the model volume persists downloads across
restarts.

Below the controls, the sidebar prints contextual notes for whatever
the current combination implies: where the key came from, that local
answers are slow on cpu, that a local judge and rewriter are
unvalidated, that the judge is off, that rerank downloads a model on
first use. The principle is the same one the whole project follows:
nothing silent, everything measured or stated.

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

One command switches from the demo to a real vault:

```bash
make vault VAULT=/mnt/c/Users/you/Documents/your-vault
```

It validates the path, writes `VAULT_PATH` into `.env`, reindexes
your notes and recreates the app with the new mount; `make vault
VAULT=demo` is the way back. The same can be done by hand, in three
steps. First, set the path in `.env`:

```
VAULT_PATH=/mnt/c/Users/you/Documents/your-vault
```

Any folder of markdown files works; on WSL,
a Windows path like `C:\Users\you` becomes `/mnt/c/Users/you`. Second,
`make ingest`: the one-shot reads the new mount and rebuilds the index
from your notes. Third, `make reload-app`, so the app container is
recreated with the new mount too. Ask something only your notes know
to confirm the switch.

## Using it with Obsidian

The assistant is fully compatible with an Obsidian vault, its original
use case: point `VAULT_PATH` at the vault folder and everything
Obsidian writes becomes signal. Wikilinks turn into the note graph and
into readable labels inside the chunks, frontmatter tags become
indexed metadata, and the folder tree becomes the scope filter in the
app's sidebar. Nothing needs to change on the Obsidian side, and no
plugin is involved.

The mount is read only, so the assistant can never modify a note, and
it is safe to keep Obsidian open while the assistant reads: Obsidian
edits the files, and the next `make ingest` picks the changes up. The
same applies to any tool that speaks the wikilink dialect — Logseq,
Foam, Dendron, or a plain text editor.

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
subfolder alone, the original corpus, the reported numbers reproduce
(the retrieval notebook builds that scoped index itself). The five
stable notebooks (ingestion pipeline, retrieval evaluation, llm judge
evaluation, database logging, course criteria evaluation) run top to
bottom against the package and print the
same tables and charts the project reports; the expensive measurements
(the full rerank pass, the model comparison) are cached or recorded
with their reproduction commands next to them.
