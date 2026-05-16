"""Context window management — keeps Nova from crashing on long conversations."""
from dataclasses import dataclass, field


@dataclass
class Message:
    role: str  # "user", "model", "tool_call", "tool_result"
    content: str
    token_estimate: int = 0
    pinned: bool = False  # pinned messages survive compaction

    def __post_init__(self):
        if not self.token_estimate:
            self.token_estimate = len(self.content) // 3  # rough estimate


class ContextManager:
    """Manages conversation history with intelligent compaction."""

    def __init__(self, max_tokens: int = 900_000, compaction_ratio: float = 0.75):
        self.max_tokens = max_tokens
        self.compaction_ratio = compaction_ratio
        self.messages: list[Message] = []
        self.compaction_count = 0

    @property
    def total_tokens(self) -> int:
        return sum(m.token_estimate for m in self.messages)

    @property
    def needs_compaction(self) -> bool:
        return self.total_tokens > (self.max_tokens * self.compaction_ratio)

    def add(self, role: str, content: str, pinned: bool = False) -> None:
        self.messages.append(Message(role=role, content=content, pinned=pinned))

    def get_history(self) -> list[dict]:
        """Returns conversation history in the format the API expects."""
        return [{"role": m.role, "parts": [{"text": m.content}]} for m in self.messages]

    def compact(self, summarizer_fn) -> str:
        """Compacts old messages into a summary, preserving pinned messages."""
        if not self.needs_compaction:
            return ""

        pinned = [m for m in self.messages if m.pinned]
        unpinned = [m for m in self.messages if not m.pinned]

        # Keep the most recent 30% of unpinned messages
        keep_count = max(4, len(unpinned) // 3)
        to_summarize = unpinned[:-keep_count]
        to_keep = unpinned[-keep_count:]

        if not to_summarize:
            return ""

        summary_text = "\n".join(
            f"[{m.role}]: {m.content[:500]}" for m in to_summarize
        )

        summary = summarizer_fn(summary_text)

        self.messages = (
            pinned
            + [Message(role="user", content=f"[Context summary]: {summary}", pinned=True)]
            + to_keep
        )
        self.compaction_count += 1
        return summary

    def clear(self) -> None:
        self.messages.clear()
        self.compaction_count = 0
