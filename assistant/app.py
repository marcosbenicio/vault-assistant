"""The face of the assistant: a question box over the vault. Streamlit
reruns this script on every interaction, so the heavy pieces live in
cached resources, the sidebar decides the wiring, and the llm objects
are only built when a question is actually asked; the last answer
survives reruns in the session state."""

import json
import os
import threading
import time
import uuid
from functools import partial

import requests
import streamlit as st
from pathlib import Path as _Path
from elasticsearch import Elasticsearch
from openai import OpenAI

from cleaner import NoteCleaner


class EmptyVaultError(Exception):
    """HARDENING 2026-08-13: dedicated sentinel for the reingest guard.
    The first version raised LookupError — but KeyError and IndexError
    are LookupError subclasses, so a real indexing bug would have worn
    the friendly 'no notes found' message as a disguise."""
from db import ConversationLog
from embeddings import SentenceTransformerEmbeddings
from ingest import VaultLoader, SlidingWindowSplitter, ElasticsearchIndexer
from judge import LLMJudge
from metrics import CallMetrics, PRICES
from rag import ObsidianRAG
from rewriter import QueryRewriter, RewriteFusedSearch
from search import VaultSearcher, ElasticsearchRetriever


@st.cache_resource
def build_core():
    """The heavy pieces, loaded once and shared across reruns: the es
    client, the embedding model, the searcher and the postgres diary.
    Everything the sidebar can change stays out of here."""
    # BUGFIX 2026-08-12 / REORDERED 2026-08-13: postgres still booting
    # used to explode here as a raw traceback page. It is probed FIRST
    # and cheaply (a refused connection fails in ~0ms) because the retry
    # pulse re-runs this whole function every 2s — with the embedding
    # model loaded first, each retry cost ~3s of cpu and a HuggingFace
    # network touch. Fail fast, then pay the heavy loads once.
    try:
        log = ConversationLog(
            host=os.getenv("POSTGRES_HOST", "localhost"),
            user=os.getenv("POSTGRES_USER", "user"),
            password=os.getenv("POSTGRES_PASSWORD", "pswd"),
            dbname=os.getenv("APP_POSTGRES_DB", "obsidian_assistant"),
        )
        log.create_tables()
    except Exception as exc:
        raise RuntimeError(f"postgres-unavailable: {exc}") from exc

    embed_model = os.getenv("EMBED_MODEL", "all-MiniLM-L6-v2")
    query_prefix = ("Represent this sentence for searching relevant passages: "
                    if "bge" in embed_model else "")

    # HARDENING 2026-08-13: a malformed ELASTIC_HOST (missing scheme)
    # raised inside the constructor and produced the raw-traceback page;
    # config problems get their own marker and a no-retry message.
    try:
        es = Elasticsearch(os.getenv("ELASTIC_HOST", "http://elasticsearch:9200"))
        embeddings = SentenceTransformerEmbeddings(embed_model, query_prefix)
    except Exception as exc:
        raise RuntimeError(f"core-config: {exc}") from exc
    searcher = VaultSearcher(es, embeddings, os.getenv("ES_INDEX", "obsidian_notes"))
    return searcher, log, embed_model


@st.cache_resource
def get_client(base_url, api_key):
    """One OpenAI client per (endpoint, key) pair, shared across reruns
    so the connection pool is reused instead of rebuilt and leaked."""
    if base_url:
        return OpenAI(base_url=base_url, api_key=api_key)
    return OpenAI(api_key=api_key)


@st.cache_data(ttl=60)
def list_ollama_models(base_url):
    """Chat models already pulled into the local ollama, [] when it is
    not reachable. Embedding-only models are filtered out; the tags
    endpoint lives at the ollama root, not under /v1."""
    try:
        resp = requests.get(base_url.rstrip("/").removesuffix("/v1") + "/api/tags",
                            timeout=1)
        return [m["name"] for m in resp.json().get("models", [])
                if "embed" not in m["name"]]
    except Exception:
        return []


# the local model ladder, lightest to heaviest: (download size, ram it
# needs, one-line note). The stack is born with the first one; the rest
# are one Download click away in the sidebar.
LOCAL_CATALOG = {
    "qwen2.5:1.5b": ("1 GB", "~2 GB RAM", "factory default, basic quality"),
    "llama3.2:3b": ("2 GB", "~4 GB RAM", "light upgrade"),
    "qwen2.5:7b-instruct": ("4.7 GB", "~8 GB RAM",
                            "the project's measured local model"),
    "qwen2.5:14b": ("9 GB", "~12 GB RAM", "heavy, not benchmarked"),
    "gpt-oss:20b": ("13 GB", "~16 GB RAM", "MoE, strong, not benchmarked"),
    "qwen3:30b-a3b": ("19 GB", "~24 GB RAM", "MoE ceiling, big machines"),
}


@st.cache_resource
def download_board():
    """model -> pull progress, shared by every rerun and session. It
    belongs to the process, so a running download survives clicks and
    page refreshes; only a container restart clears it."""
    return {}


def _pull_model(base_url, name, board):
    """Body of the download thread: streams ollama's pull progress into
    the board. Threads outlive script reruns, so the page can rerun or
    refresh freely while this keeps pulling."""
    try:
        url = base_url.rstrip("/").removesuffix("/v1") + "/api/pull"
        done, total = {}, {}
        # HARDENING 2026-08-13: timeout=None meant a STALLED stream (a
        # connection that stops delivering bytes without closing) blocked
        # this thread forever with the bar frozen and Retry unreachable.
        # The read timeout counts BETWEEN chunks, so a healthy download
        # (ollama emits frequent progress lines) never trips it.
        with requests.post(url, json={"model": name}, stream=True,
                           timeout=(5, 300)) as resp:
            for line in resp.iter_lines():
                if not line:
                    continue
                # HARDENING 2026-08-13: a proxy/gateway error page here is
                # not NDJSON; the raw decode error confused more than it
                # explained
                try:
                    info = json.loads(line)
                except ValueError:
                    board[name] = {"status": "error",
                                   "msg": "unexpected response from the "
                                          "model service (not an ollama "
                                          "pull endpoint?)"}
                    return
                if "error" in info:
                    board[name] = {"status": "error", "msg": info["error"]}
                    return
                digest = info.get("digest")
                if digest and info.get("total"):
                    total[digest] = info["total"]
                    done[digest] = info.get("completed", 0) or 0
                    board[name] = {"status": "downloading",
                                   "done": sum(done.values()),
                                   "total": sum(total.values())}
                if info.get("status") == "success":
                    board[name] = {"status": "ready"}
                    return
        # BUGFIX 2026-08-12: a stream that ENDS without ollama's explicit
        # success line is an interrupted download, not a finished one.
        # Marking it "ready" here used to spin the ui in an endless
        # rerun loop; an error state offers Retry (which resumes).
        board[name] = {"status": "error",
                       "msg": "download interrupted - Retry resumes it"}
    except Exception as exc:
        board[name] = {"status": "error", "msg": str(exc)}


@st.cache_data(ttl=30)
def gpu_active(base_url):
    """True when the loaded local model sits in vram, False when it is
    on cpu, None when nothing is loaded yet."""
    try:
        resp = requests.get(base_url.rstrip("/").removesuffix("/v1") + "/api/ps",
                            timeout=1)
        models = resp.json().get("models", [])
        if not models:
            return None
        return any(m.get("size_vram", 0) > 0 for m in models)
    except Exception:
        return None


@st.cache_data(ttl=60)
def vault_has_notes():
    """GUARD 2026-08-13: an empty mount used to produce mysterious
    'could not find' answers; the sidebar now says it plainly."""
    return next(_Path("/vault").rglob("*.md"), None) is not None


@st.cache_data(ttl=60)
def index_stats(_searcher):
    """Notes and chunks currently in the index, for the caption under
    the reingest button. Raises on an empty index (mid-reingest read)
    so a transient zero is never cached."""
    resp = _searcher.es_client.search(
        index=_searcher.index, size=0, request_timeout=3,
        aggs={"notes": {"cardinality": {"field": "path"}}})
    chunks = _searcher.es_client.count(index=_searcher.index)["count"]
    if not chunks:
        raise RuntimeError("index is empty")
    return resp["aggregations"]["notes"]["value"], chunks


@st.cache_data(ttl=300)
def list_folders(_searcher):
    """Top-level folders of the indexed vault, for the scope filter.
    Raises instead of returning empty, so a read taken mid-reingest
    (index briefly empty) is never cached; the caller treats the
    failure as no folders and the next rerun simply retries."""
    resp = _searcher.es_client.search(
        index=_searcher.index, size=0, request_timeout=3,
        aggs={"folders": {"terms": {"field": "folder", "size": 500}}})
    buckets = resp["aggregations"]["folders"]["buckets"]
    folders = sorted({b["key"].split("/")[0] for b in buckets if b["key"]})
    if not folders:
        raise RuntimeError("no folders visible in the index")
    return folders


try:
    searcher, log, embed_model = build_core()
except RuntimeError as exc:
    detail = str(exc)
    if "core-config" in detail:
        # configuration errors are permanent: no retry pulse, show cause
        st.error("Configuration problem while starting the app - check "
                 "your .env values (ELASTIC_HOST, EMBED_MODEL).")
        st.caption(detail.split("core-config: ", 1)[-1])
        st.stop()
    if "postgres-unavailable" not in detail:
        raise
    # HARDENED 2026-08-13: the first version showed the same soothing
    # message forever, hiding a wrong password behind "still starting".
    # The underlying cause is shown, and after ~30s the message stops
    # pretending and the pulse backs off.
    tries = st.session_state.get("pg_tries", 0) + 1
    st.session_state["pg_tries"] = tries
    if tries <= 15:
        st.error("The conversation database is not reachable yet - "
                 "postgres is probably still starting. This page "
                 "retries by itself.")
    else:
        st.error("The conversation database is STILL unreachable after "
                 "many retries - this looks like configuration, not "
                 "boot time. Check POSTGRES_USER / POSTGRES_PASSWORD "
                 "in .env and: docker compose logs postgres")
    st.caption(detail.split("postgres-unavailable: ", 1)[-1])
    time.sleep(2 if tries <= 15 else 10)
    st.rerun()
st.session_state.pop("pg_tries", None)

if "session_id" not in st.session_state:
    st.session_state["session_id"] = str(uuid.uuid4())


def start_download(name):
    """Fire one pull thread for a catalog model, guarded against a
    second click while the first is still running."""
    board = download_board()
    if board.get(name, {}).get("status") == "downloading":
        return
    board[name] = {"status": "downloading", "done": 0, "total": 0}
    threading.Thread(target=_pull_model, args=(llm_base_url, name, board),
                     daemon=True).start()


def render_local_models(installed):
    """The Local models expander: the catalog with each model's state,
    download buttons, live progress and the gpu/cpu indicator."""
    board = download_board()

    ready = [n for n, s in list(board.items()) if s.get("status") == "ready"]
    if ready:
        # a finished pull means the cached installed list is stale
        list_ollama_models.clear()
        for n in ready:
            if n in installed:
                del board[n]
                st.session_state.pop("ready_tries", None)
        if any(n not in installed for n in ready):
            # HARDENED 2026-08-13: this rerun had no sleep and no bound -
            # if ollama lost the model right after the pull (oom kill),
            # it spun the page in a tight infinite loop. Now it breathes
            # 2s per try and gives up after ~30s, falling back to the
            # tags list as the source of truth.
            tries = st.session_state.get("ready_tries", 0) + 1
            st.session_state["ready_tries"] = tries
            if tries <= 15:
                time.sleep(2)
                st.rerun()
            for n in ready:
                board.pop(n, None)
            st.session_state.pop("ready_tries", None)

    gpu = gpu_active(llm_base_url)
    label = ("Local models"
             + (" (GPU)" if gpu else " (CPU)" if gpu is False else ""))
    with st.sidebar.expander(label):
        for name, (size, ram, note) in LOCAL_CATALOG.items():
            state = board.get(name, {})
            status = state.get("status")
            if status == "downloading":
                done, tot = state.get("done", 0), state.get("total", 0)
                st.write(name)
                st.progress(min(done / tot, 1.0) if tot else 0.0,
                            text=f"{done / 1e9:.1f} / {tot / 1e9:.1f} GB")
            elif status == "error":
                st.write(name)
                st.error(state.get("msg", "download failed"))
                if st.button("Retry", key=f"dl-{name}"):
                    del board[name]
                    start_download(name)
                    st.rerun()
            elif status == "ready" or name in installed:
                st.write(f"{name} — installed")
                st.caption(note)
            else:
                st.write(f"{name} — {size} download, {ram}")
                st.caption(note)
                if st.button(f"Download {size}", key=f"dl-{name}"):
                    start_download(name)
                    st.rerun()
        if gpu is False:
            st.caption("Local models run on CPU here. NVIDIA gpu? "
                       "`cp docker-compose.gpu.yml docker-compose.override.yml` "
                       "then `docker compose up -d`.")

# ---- sidebar: everything the person can point the assistant with ----

st.sidebar.header("Settings")

typed_key = st.sidebar.text_input(
    "OpenAI API key", type="password",
    help="Kept in memory for this session only. Leave empty to use the "
         "key from .env, if one is set there.")
api_key = typed_key.strip() or os.getenv("OPENAI_API_KEY", "")

# the stack ships an ollama service at this address; LLM_BASE_URL in
# .env overrides it for an external OpenAI-compatible server
llm_base_url = os.getenv("LLM_BASE_URL") or "http://ollama:11434/v1"
local_key = os.getenv("LLM_API_KEY", "ollama")
local_models = list_ollama_models(llm_base_url)

api_models = list(PRICES) if api_key else []
model_options = api_models + [m for m in local_models if m not in api_models]

if not model_options:
    # the person can still bootstrap entirely from here: the catalog
    # below downloads local models the moment the service is reachable
    render_local_models(local_models)
    st.sidebar.error(
        "No model available yet. Paste an OpenAI API key above, or wait "
        "for the local service: the stack's first start pulls a basic "
        "local model (follow it with: docker compose logs -f ollama); "
        "this list refreshes within a minute. Pasted a key? Press "
        "Enter to apply it.")
    # BUGFIX 2026-08-12: st.stop() here froze the page forever (streamlit
    # only reruns on interaction, and the auto-refresh loop lives at the
    # end of the file, never reached). The pulse below keeps the promise
    # of "refreshes within a minute" true, and keeps download bars alive.
    time.sleep(2)
    st.rerun()

# the model configured in .env stays the default, exactly as documented;
# the selectbox only adds the ability to switch without editing files
env_model = os.getenv("LLM_MODEL", "gpt-5.4-mini")
default_model = (env_model if env_model in model_options
                 else "gpt-5.4-mini" if "gpt-5.4-mini" in model_options
                 else model_options[0])
model = st.sidebar.selectbox(
    "Answer model", model_options,
    index=model_options.index(default_model),
    format_func=lambda m: m if m in PRICES else f"{m} (local)")
model_is_api = model in PRICES

# the judge and the rewriter get the api when a key exists (the
# validated setup), otherwise the same local model chosen for answers
if api_key:
    aux_base, aux_key, aux_model = "", api_key, "gpt-5.4-mini"
else:
    aux_base, aux_key, aux_model = llm_base_url, local_key, model

use_rewriter = st.sidebar.toggle(
    "Query rewriter (fused search)", value=True,
    help="Puts a translation step in front of retrieval: an LLM rewrites "
         "your question using the vocabulary of the vault, then search "
         "runs on both the original and rewritten versions and fuses the "
         "results. This helps when your wording differs from the "
         "terminology used in the notes.\n\n"
         "Turning it off disables query rewriting and removes the fused "
         "mode from the available search options.")
use_judge = st.sidebar.toggle(
    "LLM judge", value=True,
    help="A second LLM call scores every answer's relevance; the verdict "
         "is logged and shown under the answer. Never blocks an answer.")

search_modes = ((["fused"] if use_rewriter else [])
                + ["hybrid", "rerank", "text", "vector"])
search_mode = st.sidebar.selectbox(
    "Search mode", search_modes, index=0,
    help="How your notes are searched before the model answers:\n"
         "- **fused** *(default)*: an LLM first rewrites the question "
         "using the vocabulary of the vault. Hybrid search then runs on "
         "both the original and rewritten queries, and the two rankings "
         "are fused. This is the best-performing retrieval mode in the "
         "evaluation.\n"
         "- **hybrid**: combines keyword search (BM25) with semantic "
         "search (embeddings), then merges the two result sets. Fast and "
         "requires no additional LLM call.\n"
         "- **rerank**: hybrid search first retrieves 30 candidates, then "
         "a cross-encoder scores each query-chunk pair and keeps the best "
         "10. It gives the most precise ranking, at a cost of roughly 4 "
         "additional seconds per query on CPU.\n"
         "- **text**: keyword-only search using BM25. Best when the query "
         "shares exact terms with the notes.\n"
         "- **vector**: embedding-only semantic search. Matches by "
         "meaning rather than exact wording.")

try:
    folders = list_folders(searcher)
except Exception:
    folders = []
folder_choice = st.sidebar.selectbox(
    "Folder", ["whole vault"] + folders,
    help="Restrict the search to one subtree of the vault.")
folder = None if folder_choice == "whole vault" else folder_choice

# the index always mirrors the whole vault folder; the Folder selector
# above only scopes the SEARCH, never what gets indexed
if st.sidebar.button(
        "Reingest vault",
        help="Rebuild the search index from the files in the vault. "
             "Run it after adding, editing or deleting notes."):
    try:
        with st.spinner("Reindexing the vault..."):
            docs = VaultLoader(os.getenv("VAULT_PATH", "/vault"),
                               NoteCleaner()).load()
            # BUGFIX 2026-08-12 / HARDENED 2026-08-13: an empty folder
            # used to WIPE the index and celebrate "0 notes" in green —
            # and a vault of frontmatter-only stubs passed the first
            # guard with zero CHUNKS, wiping it anyway. Both checked
            # BEFORE anything destructive: zero content, zero touch.
            if not docs:
                raise EmptyVaultError
            chunks = SlidingWindowSplitter(
                chunk_size=2000, chunk_overlap=1000).split_documents(docs)
            if not chunks:
                raise EmptyVaultError
            indexer = ElasticsearchIndexer(
                searcher.es_client, searcher.embeddings, index=searcher.index)
            indexer.create_index(recreate=True)
            indexer.index_documents(chunks)
            searcher.es_client.indices.refresh(index=searcher.index)
    except EmptyVaultError:
        st.sidebar.error("No indexable notes found in the vault folder "
                         "(empty, or only frontmatter stubs) - nothing "
                         "was changed. Check the folder (or VAULT_PATH "
                         "in .env).")
    except Exception as exc:
        st.sidebar.error(f"Reingest failed: {exc}. The index may be "
                         "partial; click again to rebuild.")
    else:
        list_folders.clear()
        index_stats.clear()
        st.sidebar.success(f"{len(docs)} notes -> {len(chunks)} chunks")

try:
    st.sidebar.caption("index: {} notes · {} chunks".format(*index_stats(searcher)))
except Exception:
    # C2 2026-08-13: an empty index with a HEALTHY vault means the
    # startup indexing is still running (or was interrupted) - say so,
    # instead of a mute sidebar and answers from nothing
    if vault_has_notes():
        st.sidebar.info("The index is empty or still building - it "
                        "fills itself on startup (about a minute), or "
                        "click 'Reingest vault'.")

if not vault_has_notes():
    st.sidebar.warning("The mounted vault has no markdown notes. Run "
                       "the launcher (start.sh or \"Start Assistant.bat\") "
                       "to pick a different folder, or the demo.")

# the host-side vault choice, surfaced so nobody wonders whose notes
# are answering: the demo gets onboarding (dismissable per session,
# back on reload), a real vault gets named
host_vault = os.getenv("HOST_VAULT_PATH", "")
# STATUS 2026-08-13: the vault line is now UNCONDITIONAL - the demo
# state used to go mute once the onboarding box was dismissed, leaving
# nobody sure which vault was answering
st.sidebar.caption(f"vault: {host_vault or 'demo (the project example notes)'}")
if not host_vault and not st.session_state.get("vault_notice_ok"):
    st.sidebar.info(
        "**Demo vault active.** `VAULT_PATH` is not set, so every "
        "answer comes from the project's example notes.\n\n"
        "To answer from your own notes, run this from the project "
        "root:\n\n"
        "`make vault VAULT=/abs/path/to/your/notes`\n\n"
        "Any folder of markdown files works, including an "
        "[Obsidian](https://obsidian.md/download) vault. The "
        "path must be absolute:\n"
        "- **Linux**: `/home/you/Notes`\n"
        "- **macOS**: `/Users/you/Notes`\n"
        "- **Windows (WSL2)**: `C:\\Users\\you\\Notes` becomes "
        "`/mnt/c/Users/you/Notes`\n"
        "- **Windows without WSL**: the make targets need a POSIX "
        "shell; without one, set `VAULT_PATH` in `.env` by hand and "
        "run `docker compose run --rm ingest` followed by "
        "`docker compose up -d --force-recreate app`\n\n"
        "The command stores the path in `.env`, indexes your notes "
        "and reconnects the app; from then on, answers come from your "
        "vault. Back to the demo: `make vault VAULT=demo`.",
        icon="ℹ️")
    # the OK visually docks onto the info balloon: full width, no gap,
    # same blue family (native widgets cannot live inside st.info)
    st.sidebar.markdown("""
        <style>
        .st-key-vault-notice-ok button {
            width: 100%;
            margin-top: -0.9rem;
            background-color: rgba(61, 157, 243, 0.12);
            border: 1px solid rgba(61, 157, 243, 0.45);
            color: #9ec9f5;
        }
        .st-key-vault-notice-ok button:hover {
            border-color: #3d9df3;
            color: #d6e9ff;
        }
        </style>""", unsafe_allow_html=True)
    if st.sidebar.button("OK", key="vault-notice-ok"):
        st.session_state["vault_notice_ok"] = True
        st.rerun()

render_local_models(local_models)

# ---- contextual notes: always say what is wired and what is not ----

if typed_key:
    st.sidebar.caption("Key from the sidebar, kept in memory only.")
elif api_key:
    st.sidebar.caption("Key from .env.")
else:
    st.sidebar.caption("No OpenAI key: local models only, and the judge "
                       "and rewriter run on the local model too.")
if model == "qwen2.5:1.5b":
    st.sidebar.caption("Basic local model: limited answers. Download a "
                       "better one under Local models.")
if not model_is_api and model in ("qwen2.5:14b", "gpt-oss:20b",
                                  "qwen3:30b-a3b"):
    st.sidebar.caption("Not benchmarked in this project; "
                       "qwen2.5:7b-instruct is the measured local "
                       "reference.")
if not model_is_api and gpu_active(llm_base_url) is not True:
    st.sidebar.caption("Local answers are slow on cpu: qwen2.5:7b "
                       "measured ~70s per answer.")
if not use_judge:
    st.sidebar.caption("Judge off: answers get no verdict and no row in "
                       "the judgements table.")
if search_mode == "rerank":
    st.sidebar.caption("The first rerank question downloads the "
                       "cross-encoder (~80 MB) on a fresh install.")
if not host_vault:
    st.sidebar.caption(
        "\U0001F4AC Questions about the project? Ask the assistant "
        "itself. With the demo vault active, it answers directly from "
        "the project's own documentation. Try questions like \"explain "
        "the sidebar settings\", \"how do I point this at my own "
        "notes?\", or \"how do I run the local models on GPU?\".\n\n"
        "Stronger models generally produce more complete and precise "
        "answers from the same retrieved context.")

# ---- the page ----

st.title("Vault Assistant")
st.caption(f"answering from your vault with {model} | search: {search_mode}"
           + (f" | folder: {folder}" if folder else ""))

question = st.text_input("Ask your vault:")

if st.button("Ask") and question.strip():
    # the wiring happens only when a question is asked: cheap objects
    # over the cached core, clients reused through get_client
    answer_client = get_client("" if model_is_api else llm_base_url,
                               api_key if model_is_api else local_key)

    search_fns = {"hybrid": searcher.hybrid, "rerank": searcher.rerank,
                  "text": searcher.text, "vector": searcher.vector}
    if use_rewriter:
        rewriter = QueryRewriter(get_client(aux_base, aux_key), model=aux_model)
        search_fns["fused"] = RewriteFusedSearch(searcher, rewriter).search

    search_fn = search_fns[search_mode]
    if folder:
        search_fn = partial(search_fn, folder=folder)

    rag = ObsidianRAG(ElasticsearchRetriever(search_fn=search_fn, num_results=10),
                      answer_client, model=model)

    spinner = ("Searching your notes (local model, this takes a while)..."
               if not model_is_api else "Searching your notes...")
    with st.spinner(spinner):
        started = time.time()
        try:
            result = rag.invoke(question)
        except Exception as exc:
            result, error = None, exc
        elapsed = time.time() - started

    # the spinner must close before the error renders, or it spins forever
    if result is None:
        # BUGFIX 2026-08-12: retrieval failures used to be reported as
        # "model call failed", sending people to debug their key when
        # the index was the problem. Elasticsearch-family exceptions
        # are now named for what they are.
        if type(error).__module__.startswith(("elasticsearch",
                                              "elastic_transport")):
            st.error("The search index is unreachable or missing - the "
                     "first ingest may still be running. Wait a minute, "
                     "or click 'Reingest vault' in the sidebar.")
        else:
            st.error(f"The model call failed: {error}")
        # HARDENING 2026-08-13: this used to st.stop() - which also
        # erased the PREVIOUS answer from the page and froze active
        # download bars (the end-of-file pulse below was never reached).
        # Falling through renders the error above the old answer.
    else:

        metrics = CallMetrics.from_call(rag.model, result["usage"], elapsed)
        if not result["source_documents"]:
            # HARDENING 2026-08-13: an EXISTING but empty index raised
            # nothing - the model answered from thin air with no sources
            st.warning("No notes matched this question - the index may "
                       "be empty. Click 'Reingest vault' in the sidebar.")
        # HARDENING 2026-08-13: postgres dying AFTER boot was unguarded -
        # the save exploded as a raw traceback and ate the answer. The
        # answer always renders; losing the log line costs a warning.
        try:
            conversation_id = log.save_conversation(
            question=question,
            answer=result["answer"],
            model=metrics.model,
            prompt_tokens=metrics.prompt_tokens,
            completion_tokens=metrics.completion_tokens,
            cost=metrics.cost,
            response_time=metrics.response_time,
            embed_model=embed_model,
            search_mode=search_mode,
            num_sources=len(result["source_documents"]),
            sources=[{"path": d.metadata["source"], "start": d.metadata["start"],
                      "score": d.metadata["score"]}
                     for d in result["source_documents"]],
            retrieval_time=result["retrieval_time"],
            session_id=st.session_state["session_id"],
            )
        except Exception:
            conversation_id = None
            st.warning("Answer not logged - the conversation database "
                       "is unreachable right now.")

        # the judge observes every answer it is enabled for; a failure can
        # only cost the verdict, never the answer
        judge_status = "off"
        if use_judge:
            judge = LLMJudge(get_client(aux_base, aux_key), model=aux_model)
            with st.spinner("Judging the answer..."):
                try:
                    verdict = judge.judge(question, result["answer"])
                    judge_status = verdict.relevance
                except Exception:
                    judge_status = "failed"
                else:
                    try:
                        if conversation_id is not None:
                            log.save_judgement(conversation_id,
                                               verdict.relevance,
                                               verdict.reasoning,
                                               judge_model=judge.model)
                    except Exception:
                        pass

        # the rerun triggered by any later click must still show this answer
        st.session_state["last"] = {
            "id": conversation_id,
            "answer": result["answer"],
            "sources": [(d.metadata["score"], d.metadata["source"])
                        for d in result["source_documents"]],
            "metrics": metrics,
            "judge": judge_status,
            "feedback_given": False,
        }

last = st.session_state.get("last")
if last:
    st.write(last["answer"])

    m = last["metrics"]
    st.caption(f"{m.response_time:.1f}s | {m.prompt_tokens} in / "
               f"{m.completion_tokens} out | ${m.cost:.4f}"
               f" | judge: {last['judge']}")

    with st.expander("Sources"):
        for score, source in last["sources"]:
            st.write(f"{score:.4f}  {source}")

    if last["id"] is None:
        st.caption("feedback unavailable (conversation was not logged)")
    elif last["feedback_given"]:
        st.caption("feedback saved, thanks")
    else:
        helpful, not_helpful = st.columns(2)
        # HARDENING 2026-08-13: feedback writes share the same fate as
        # the conversation save - db down must not crash the page
        if helpful.button("Helpful"):
            try:
                log.save_feedback(last["id"], 1)
                last["feedback_given"] = True
            except Exception:
                st.warning("Vote not saved - database unreachable.")
            st.rerun()
        if not_helpful.button("Not helpful"):
            try:
                log.save_feedback(last["id"], -1)
                last["feedback_given"] = True
            except Exception:
                st.warning("Vote not saved - database unreachable.")
            st.rerun()

# while any download runs, the page refreshes itself so the progress
# bar stays alive; the thread does the work, this only redraws
if any(s.get("status") == "downloading"
       for s in list(download_board().values())):
    time.sleep(2)
    st.rerun()
