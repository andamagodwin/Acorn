"""Cost tracking for Acorn — estimates spending per session."""
from dataclasses import dataclass, field
from datetime import datetime

# Pricing per 1M tokens (Vertex AI pricing)
MODEL_PRICING = {
    "gemini-3.1-pro-preview": {"input": 1.25, "output": 10.00},
    "gemini-3.1-pro-preview-customtools": {"input": 1.25, "output": 10.00},
    "gemini-3-flash-preview": {"input": 0.10, "output": 0.40},
    "gemini-2.5-pro": {"input": 1.25, "output": 10.00},
    "gemini-2.5-flash": {"input": 0.15, "output": 0.60},
}

DEFAULT_PRICING = {"input": 1.25, "output": 10.00}


@dataclass
class CostTracker:
    """Tracks token usage and estimates costs for the session."""

    total_input_tokens: int = 0
    total_output_tokens: int = 0
    calls: list = field(default_factory=list)

    def record(self, model: str, input_tokens: int, output_tokens: int):
        """Records a single API call."""
        pricing = MODEL_PRICING.get(model, DEFAULT_PRICING)
        input_cost = (input_tokens / 1_000_000) * pricing["input"]
        output_cost = (output_tokens / 1_000_000) * pricing["output"]

        self.total_input_tokens += input_tokens
        self.total_output_tokens += output_tokens
        self.calls.append({
            "model": model,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cost": input_cost + output_cost,
            "time": datetime.now().isoformat(),
        })

    def estimate_from_text(self, model: str, input_text: str, output_text: str):
        """Estimates tokens from text length (rough: ~4 chars per token)."""
        input_tokens = len(input_text) // 4
        output_tokens = len(output_text) // 4
        self.record(model, input_tokens, output_tokens)

    @property
    def total_cost(self) -> float:
        return sum(c["cost"] for c in self.calls)

    @property
    def session_summary(self) -> dict:
        pro_calls = sum(1 for c in self.calls if "pro" in c["model"])
        flash_calls = sum(1 for c in self.calls if "flash" in c["model"] or "lite" in c["model"])
        return {
            "total_calls": len(self.calls),
            "pro_calls": pro_calls,
            "flash_calls": flash_calls,
            "input_tokens": self.total_input_tokens,
            "output_tokens": self.total_output_tokens,
            "total_cost": self.total_cost,
        }

    def format_cost(self) -> str:
        """Returns a human-readable cost string."""
        cost = self.total_cost
        if cost < 0.01:
            return f"~${cost:.4f}"
        return f"~${cost:.3f}"
