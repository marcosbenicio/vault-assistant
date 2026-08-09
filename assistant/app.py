"""The face of the assistant: a question box over the vault. Streamlit
reruns this script on every interaction, so everything expensive lives
inside the cached build function and the last answer survives reruns in
the session state."""

import os
import time
import uuid

import streamlit as st
from elasticsearch import Elasticsearch
from openai import OpenAI

from db import ConversationLog
from embeddings import SentenceTransformerEmbeddings
from judge import LLMJudge
from metrics import CallMetrics
from rag import ObsidianRAG, create_llm_client
from rewriter import QueryRewriter, RewriteFusedSearch
from search import VaultSearcher, ElasticsearchRetriever


@st.cache_resource
def build_assistant():
    """The whole stack, assembled once and reused across reruns: the
    same wiring the notebooks validated, read from the environment.
    The judge always talks to the OpenAI api, whatever model answers."""
    model_name = os.getenv("EMBED_MODEL", "all-MiniLM-L6-v2")
    query_prefix = ("Represent this sentence for searching relevant passages: "
                    if "bge" in model_name else "")

    es = Elasticsearch(os.getenv("ELASTIC_HOST", "http://elasticsearch:9200"))
    embeddings = SentenceTransformerEmbeddings(model_name, query_prefix)
    searcher = VaultSearcher(es, embeddings, os.getenv("ES_INDEX", "obsidian_notes"))

    # default retrieval changed from plain hybrid to rewrite+fuse: on the
    # 200 question ground truth, fusing the original question with an
    # llm-rewritten version raised hit rate 0.755 -> 0.885 (hard questions
    # 0.68 -> 0.86, rescued 28 / broke 2), for one cheap extra llm call
    # (~0.7s). Full measurement in the query rewriting section of
    # notebooks/stable/02_retrieval_evaluation.ipynb.
    openai_client = OpenAI()
    rewriter = QueryRewriter(openai_client, model="gpt-5.4-mini")
    fused = RewriteFusedSearch(searcher, rewriter)
    retriever = ElasticsearchRetriever(search_fn=fused.search, num_results=10)

    rag = ObsidianRAG(retriever, create_llm_client(),
                      model=os.getenv("LLM_MODEL", "gpt-5.4-mini"))
    judge = LLMJudge(openai_client, model="gpt-5.4-mini")

    log = ConversationLog(
        host=os.getenv("POSTGRES_HOST", "localhost"),
        user=os.getenv("POSTGRES_USER", "user"),
        password=os.getenv("POSTGRES_PASSWORD", "pswd"),
        dbname=os.getenv("APP_POSTGRES_DB", "obsidian_assistant"),
    )
    log.create_tables()
    return rag, log, judge


rag, log, judge = build_assistant()

if "session_id" not in st.session_state:
    st.session_state["session_id"] = str(uuid.uuid4())

st.title("Obsidian Assistant")
st.caption(f"answering from your vault with {rag.model}")

question = st.text_input("Ask your vault:")

if st.button("Ask") and question.strip():
    with st.spinner("Searching your notes..."):
        started = time.time()
        result = rag.invoke(question)
        elapsed = time.time() - started

    metrics = CallMetrics.from_call(rag.model, result["usage"], elapsed)
    conversation_id = log.save_conversation(
        question=question,
        answer=result["answer"],
        model=metrics.model,
        prompt_tokens=metrics.prompt_tokens,
        completion_tokens=metrics.completion_tokens,
        cost=metrics.cost,
        response_time=metrics.response_time,
        embed_model=os.getenv("EMBED_MODEL", "all-MiniLM-L6-v2"),
        search_mode="fused",
        num_sources=len(result["source_documents"]),
        sources=[{"path": d.metadata["source"], "start": d.metadata["start"],
                  "score": d.metadata["score"]}
                 for d in result["source_documents"]],
        retrieval_time=result["retrieval_time"],
        session_id=st.session_state["session_id"],
    )

    # the judge observes every production answer; it never blocks one
    try:
        verdict = judge.judge(question, result["answer"])
        log.save_judgement(conversation_id, verdict.relevance,
                           verdict.reasoning, judge_model=judge.model)
    except Exception:
        verdict = None

    # the rerun triggered by any later click must still show this answer
    st.session_state["last"] = {
        "id": conversation_id,
        "answer": result["answer"],
        "sources": [(d.metadata["score"], d.metadata["source"])
                    for d in result["source_documents"]],
        "metrics": metrics,
        "verdict": verdict.relevance if verdict else None,
        "feedback_given": False,
    }

last = st.session_state.get("last")
if last:
    st.write(last["answer"])

    m = last["metrics"]
    caption = (f"{m.response_time:.1f}s | {m.prompt_tokens} in / "
               f"{m.completion_tokens} out | ${m.cost:.4f}")
    if last["verdict"]:
        caption += f" | judge: {last['verdict']}"
    st.caption(caption)

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
