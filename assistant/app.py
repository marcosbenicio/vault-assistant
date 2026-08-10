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
from elasticsearch import Elasticsearch
from openai import OpenAI

from cleaner import NoteCleaner
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
    embed_model = os.getenv("EMBED_MODEL", "all-MiniLM-L6-v2")
    query_prefix = ("Represent this sentence for searching relevant passages: "
                    if "bge" in embed_model else "")

    es = Elasticsearch(os.getenv("ELASTIC_HOST", "http://elasticsearch:9200"))
    embeddings = SentenceTransformerEmbeddings(embed_model, query_prefix)
    searcher = VaultSearcher(es, embeddings, os.getenv("ES_INDEX", "obsidian_notes"))

    log = ConversationLog(
        host=os.getenv("POSTGRES_HOST", "localhost"),
        user=os.getenv("POSTGRES_USER", "user"),
        password=os.getenv("POSTGRES_PASSWORD", "pswd"),
        dbname=os.getenv("APP_POSTGRES_DB", "obsidian_assistant"),
    )
    log.create_tables()
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
        with requests.post(url, json={"model": name}, stream=True,
                           timeout=None) as resp:
            for line in resp.iter_lines():
                if not line:
                    continue
                info = json.loads(line)
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
        board[name] = {"status": "ready"}
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


searcher, log, embed_model = build_core()

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

    ready = [n for n, s in board.items() if s.get("status") == "ready"]
    if ready:
        # a finished pull means the cached installed list is stale
        list_ollama_models.clear()
        for n in ready:
            if n in installed:
                del board[n]
        if any(n not in installed for n in ready):
            # the Answer model list was built above with the stale cache;
            # rerun so the fresh model appears without a manual refresh
            st.rerun()

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
        "this list refreshes within a minute.")
    st.stop()

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
            chunks = SlidingWindowSplitter(
                chunk_size=2000, chunk_overlap=1000).split_documents(docs)
            indexer = ElasticsearchIndexer(
                searcher.es_client, searcher.embeddings, index=searcher.index)
            indexer.create_index(recreate=True)
            indexer.index_documents(chunks)
            searcher.es_client.indices.refresh(index=searcher.index)
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
    pass

# the host-side vault choice, surfaced so nobody wonders whose notes
# are answering: the demo gets onboarding (dismissable per session,
# back on reload), a real vault gets named
host_vault = os.getenv("HOST_VAULT_PATH", "")
if host_vault:
    st.sidebar.caption(f"vault: {host_vault}")
elif not st.session_state.get("vault_notice_ok"):
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
        st.error(f"The model call failed: {error}")
        st.stop()

    metrics = CallMetrics.from_call(rag.model, result["usage"], elapsed)
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
                    log.save_judgement(conversation_id, verdict.relevance,
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

    if last["feedback_given"]:
        st.caption("feedback saved, thanks")
    else:
        helpful, not_helpful = st.columns(2)
        if helpful.button("Helpful"):
            log.save_feedback(last["id"], 1)
            last["feedback_given"] = True
            st.rerun()
        if not_helpful.button("Not helpful"):
            log.save_feedback(last["id"], -1)
            last["feedback_given"] = True
            st.rerun()

# while any download runs, the page refreshes itself so the progress
# bar stays alive; the thread does the work, this only redraws
if any(s.get("status") == "downloading" for s in download_board().values()):
    time.sleep(2)
    st.rerun()
