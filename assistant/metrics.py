"""What one llm call cost: tokens, dollars and wall time. The price
table covers the api models; anything unknown (the local ollama models)
is priced at zero, which is literally true."""

from dataclasses import dataclass

# dollars per million tokens: (input, output). Update here when prices
# or models change; nothing else in the project knows about pricing.
# dollars per million tokens (input, output), short context, standard tier.
# Source: openai pricing page, copied 2026-08-09 (demo_vault/gpt_pricing.md)
PRICES = {
    "gpt-5.6-sol":   (5.00, 30.00),
    "gpt-5.6-terra": (2.00, 12.00),
    "gpt-5.6-luna":  (0.20, 1.20),
    "gpt-5.4":       (2.50, 15.00),
    "gpt-5.4-mini":  (0.75, 4.50),   # corrigido, era 0.25/2.00
    "gpt-5.4-nano":  (0.20, 1.25),
    "gpt-5-mini":    (0.25, 2.00),
    "gpt-5-nano":    (0.05, 0.40),
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
