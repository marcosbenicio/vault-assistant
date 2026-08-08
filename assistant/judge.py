"""Answer quality judgement: an llm reads a question and the generated
answer and classifies the relevance, writing its reasoning before the
verdict. Used offline to compare model variants and online to monitor
production answers."""

from typing import Literal

from pydantic import BaseModel

JUDGE_PROMPT = """
You are an expert evaluator for a RAG system.
Your task is to analyze the relevance of the generated answer to the
given question. Classify the answer as "NON_RELEVANT",
"PARTLY_RELEVANT" or "RELEVANT", and explain your reasoning before
deciding.

Here is the data for evaluation:

Question: {question}
Generated Answer: {answer}
""".strip()


class AnswerEvaluation(BaseModel):
    """The judge's verdict, structured: the api guarantees this shape,
    so there is no json parsing and no vocabulary drift. Reasoning
    comes first on purpose: the model justifies before it decides."""
    reasoning: str
    relevance: Literal["RELEVANT", "PARTLY_RELEVANT", "NON_RELEVANT"]


class LLMJudge:
    """The judge in the package pattern: the llm client and the model
    name arrive at birth, nothing in here reads the environment. One
    verdict per call, at temperature zero so the same answer always
    receives the same judgement."""

    def __init__(self, llm_client, model):
        self.llm_client = llm_client
        self.model = model

    def judge(self, question, answer):
        """One verdict for one answer."""
        response = self.llm_client.chat.completions.parse(
            model=self.model,
            temperature=0,
            messages=[{"role": "user", "content": JUDGE_PROMPT.format(
                question=question, answer=answer)}],
            response_format=AnswerEvaluation,
        )
        return response.choices[0].message.parsed
