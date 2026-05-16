"""Smart model routing — use Flash for simple, Pro for complex."""


class ModelRouter:
    """Routes requests to the appropriate model based on complexity."""

    def __init__(self, pro_model: str, flash_model: str):
        self.pro_model = pro_model
        self.flash_model = flash_model
        self.current_model = pro_model
        self._route_history: list[tuple[str, str]] = []

    def route(self, message: str, has_tool_context: bool = False) -> str:
        """Decides which model to use for this message."""
        # If we're mid-tool-loop, always use the same model
        if has_tool_context:
            return self.current_model

        # Complex tasks always get Pro
        if self._is_complex(message):
            self.current_model = self.pro_model
        # Simple tasks get Flash
        elif self._is_simple(message):
            self.current_model = self.flash_model
        # Default to Pro for ambiguous cases
        else:
            self.current_model = self.pro_model

        self._route_history.append((message[:50], self.current_model))
        return self.current_model

    def _is_complex(self, message: str) -> bool:
        msg = message.lower()
        complex_keywords = [
            "refactor", "redesign", "architect", "implement",
            "across all files", "multiple files", "entire codebase",
            "build me", "create a", "migrate", "convert all",
            "debug this", "fix the bug", "why is this",
        ]
        return (
            any(kw in msg for kw in complex_keywords)
            or len(message) > 500
            or message.count("\n") > 5
        )

    def _is_simple(self, message: str) -> bool:
        msg = message.lower().strip()
        simple_patterns = [
            len(message) < 100,
            msg in ("hi", "hello", "hey", "thanks", "ok", "yes", "no"),
            msg.startswith(("what is", "what's", "explain", "how do", "why do")),
            msg.endswith("?") and len(message) < 150,
        ]
        return any(simple_patterns)

    @property
    def stats(self) -> dict:
        pro_count = sum(1 for _, m in self._route_history if m == self.pro_model)
        flash_count = sum(1 for _, m in self._route_history if m == self.flash_model)
        return {
            "pro_calls": pro_count,
            "flash_calls": flash_count,
            "estimated_savings": f"~${flash_count * 0.01:.2f} saved by using Flash",
        }
