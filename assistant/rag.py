import os
import time

from openai import OpenAI


def create_llm_client():
    """OpenAI by default; any OpenAI-compatible server (Ollama) when
    LLM_BASE_URL is set. The api key for local servers is a dummy,
    because they do not check keys."""
    base_url = os.getenv("LLM_BASE_URL")
    if base_url:
        return OpenAI(base_url=base_url, api_key=os.getenv("LLM_API_KEY", "ollama"))
    return OpenAI()


class ObsidianRAG:
    """The retrieval chain in the LangChain shape.

    A retriever supplies Documents and the llm answers only from them.
    invoke(question) returns the answer plus the source documents, so
    any interface can show citations without knowing about retrieval.
    """

    INSTRUCTIONS = """
    You are the assistant for a personal Obsidian vault.

    Answer the question using only the provided context,
    which contains parts of the owner's notes. Each part starts with its source path.

    Be direct and concise. After the answer, list the notes you actually
    used, one per line, in the form:
    Sources:
    - <path>

    If the context does not contain the answer, say you could not find it
    in the vault, and do not invent anything.

    You may combine information from multiple excerpts and state what
    follows from them. Only say you could not find it when the context
    contains nothing relevant to the question.

    """.strip()

    PROMPT_TEMPLATE = """
    CONTEXT:
    {context}

    QUESTION: {question}
    """.strip()


    def __init__(self, retriever, llm_client, model):
        self.retriever = retriever
        self.llm_client = llm_client
        self.model = model

    def build_context(self, documents):
        """One block per chunk, opened by its source path so the model
        can cite notes by name."""
        blocks = [f"source: {d.metadata['source']}\n{d.page_content}"
                  for d in documents]
        return "\n\n---\n\n".join(blocks)

    def build_prompt(self, question, documents):
        return self.PROMPT_TEMPLATE.format(
            question=question, context=self.build_context(documents)
        )

    def invoke(self, question):
        retrieval_started = time.time()
        documents = self.retriever.get_relevant_documents(question)
        retrieval_time = time.time() - retrieval_started
        prompt = self.build_prompt(question, documents)

        response = self.llm_client.chat.completions.create(
            model=self.model,
            temperature=0.0,
            messages=[
                {"role": "system", "content": self.INSTRUCTIONS},
                {"role": "user", "content": prompt},
            ],
        )

        return {
            "answer": response.choices[0].message.content,
            "source_documents": documents,
            "usage": response.usage,
            "retrieval_time": retrieval_time,
        }
