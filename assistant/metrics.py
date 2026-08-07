"""What one llm call cost: tokens, dollars and wall time. The price
table covers the api models; anything unknown (the local ollama models)
is priced at zero, which is literally true."""

from dataclasses import dataclass

# dollars per million tokens: (input, output). Update here when prices
# or models change; nothing else in the project knows about pricing.
PRICES = {
    "gpt-5.4-mini": (0.25, 2.00),
}


@dataclass
class CallMetrics:
    """One llm call measured: exactly the shape save_conversation
    expects, so the app moves this straight into the diary."""
    model: str
    prompt_tokens: int
    completion_tokens: int
    response_time: float
    cost: float

    @classmethod
    def from_call(cls, model, usage, response_time):
        """Build from the openai usage object plus the wall time the
        caller measured around the request."""
        price_in, price_out = PRICES.get(model, (0.0, 0.0))
        cost = (usage.prompt_tokens * price_in
                + usage.completion_tokens * price_out) / 1_000_000
        return cls(
            model=model,
            prompt_tokens=usage.prompt_tokens,
            completion_tokens=usage.completion_tokens,
            response_time=response_time,
            cost=cost,
        )
