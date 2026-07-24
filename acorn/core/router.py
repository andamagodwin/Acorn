"""Smart model routing — decides between Flash and Pro per request.

Scores a message on independent signals (size, structure, intent) rather than
matching keywords, because keyword matching misroutes the common cases: a
question that opens with "what is" can still be an expensive whole-codebase
question, and a short imperative like "refactor auth" is expensive despite
being 14 characters long.

Scores that land in the ambiguous middle band can optionally be resolved by
asking Flash to classify the request. That call is cheap, but it is still a
round trip, so it only fires for the messages the heuristics can't separate.
"""
import re


# Score at or above this is Pro; at or below the lower bound is Flash.
# In between, we're not confident from heuristics alone.
PRO_THRESHOLD = 4.0
FLASH_THRESHOLD = -2.0

CHARS_PER_TOKEN = 4

# Verbs that imply mutating a codebase, which needs the stronger model.
ACTION_VERBS = (
    "refactor", "implement", "migrate", "rewrite", "redesign", "architect",
    "build", "create", "add", "fix", "debug", "optimize", "convert",
    "port", "upgrade", "integrate", "extract", "rename", "delete", "remove",
    "test", "deploy", "configure", "generate", "wire", "hook up",
)

# Openers that usually mean "answer me", not "change my code".
QUESTION_OPENERS = (
    "what is", "what's", "what does", "what are", "whats",
    "how do", "how does", "how can", "how would",
    "why is", "why does", "why do", "why would",
    "when should", "when do", "where is", "where do",
    "explain", "describe", "tell me about", "define",
    "is there", "are there", "can you explain", "does",
)

GREETINGS = frozenset({
    "hi", "hello", "hey", "yo", "sup", "thanks", "thank you", "ty",
    "ok", "okay", "k", "yes", "no", "y", "n", "sure", "cool", "nice",
    "got it", "makes sense", "perfect", "great", "bye", "done",
})

# Phrases that mean "touch many things", regardless of message length.
BREADTH_MARKERS = (
    "across all", "across the", "every file", "all files", "entire codebase",
    "whole codebase", "throughout", "everywhere", "each file",
    "multiple files", "the whole project", "all of the",
)

# "entire auth system", "whole pipeline" — breadth without naming the codebase.
BREADTH_PATTERN = re.compile(r"\b(?:entire|whole|all\s+(?:my|the|our))\s+\w+")

# Words that turn a question into a debugging job. "why do we use X" is a
# definition; "why is X failing" is an investigation, and they open the same way.
PROBLEM_WORDS = (
    "wrong", "broken", "break", "breaking", "fail", "failing", "fails",
    "error", "crash", "crashing", "bug", "slow", "hang", "hanging", "stuck",
    "leak", "not working", "doesn't work", "isn't working", "won't",
    "unexpected", "wrong output", "regression", "flaky", "timeout",
)

# Cheap read-only asks that Flash handles fine even without a question opener.
READONLY_VERBS = ("summarize", "list", "show me", "print", "display", "read")

CODE_FENCE = re.compile(r"```")
FILE_PATH = re.compile(r"[\w./-]+\.(?:py|js|ts|tsx|jsx|go|rs|java|rb|php|c|h|cpp|cs|swift|kt|sh|toml|yaml|yml|json|md|html|css|sql)\b")
STACK_TRACE = re.compile(r"(?:Traceback|File \"|\bat [\w.$]+\(|Exception|Error:)")
NUMBERED_STEP = re.compile(r"^\s*\d+[.)]\s+", re.MULTILINE)

CLASSIFIER_PROMPT = """Classify this coding-assistant request as SIMPLE or COMPLEX.

SIMPLE: conversational replies, definitions, explaining a concept, reading or
summarizing one file, a single trivial lookup.

COMPLEX: writing or modifying code, multi-step work, anything touching several
files, debugging, architecture or design decisions, or work needing careful
reasoning.

Answer with exactly one word: SIMPLE or COMPLEX.

Request:
{message}"""


class RouteDecision:
    """The outcome of a routing call, kept for /status and debugging."""

    __slots__ = ("model", "score", "reasons", "source")

    def __init__(self, model: str, score: float, reasons: list[str], source: str):
        self.model = model
        self.score = score
        self.reasons = reasons
        self.source = source  # "heuristic", "classifier", "locked", or "disabled"

    def __repr__(self) -> str:
        return f"<RouteDecision {self.model} score={self.score:+.1f} via {self.source}>"


class ModelRouter:
    """Routes requests to the appropriate model based on estimated complexity."""

    def __init__(
        self,
        pro_model: str,
        flash_model: str,
        enabled: bool = True,
        classifier=None,
    ):
        self.pro_model = pro_model
        self.flash_model = flash_model
        self.enabled = enabled
        # Callable[[str], str] returning "SIMPLE"/"COMPLEX"; injected by the
        # agent so the router doesn't need to know about API clients.
        self.classifier = classifier
        self.current_model = pro_model
        self._history: list[RouteDecision] = []
        self._classifier_calls = 0

    def route(self, message: str, has_tool_context: bool = False) -> str:
        """Picks a model for this message and remembers why."""
        decision = self.decide(message, has_tool_context)
        self.current_model = decision.model
        self._history.append(decision)
        return decision.model

    def decide(self, message: str, has_tool_context: bool = False) -> RouteDecision:
        # Mid-tool-loop turns must stay on the model that started the loop —
        # swapping models mid-conversation invalidates its own tool history.
        if has_tool_context:
            return RouteDecision(self.current_model, 0.0, ["mid tool loop"], "locked")

        if not self.enabled:
            return RouteDecision(self.pro_model, 0.0, ["routing disabled"], "disabled")

        score, reasons = self.score(message)

        if score >= PRO_THRESHOLD:
            return RouteDecision(self.pro_model, score, reasons, "heuristic")
        if score <= FLASH_THRESHOLD:
            return RouteDecision(self.flash_model, score, reasons, "heuristic")

        # Ambiguous. Ask Flash to classify if we have a classifier available.
        if self.classifier is not None:
            verdict = self._classify(message)
            if verdict == "SIMPLE":
                return RouteDecision(self.flash_model, score, reasons + ["classifier: simple"], "classifier")
            if verdict == "COMPLEX":
                return RouteDecision(self.pro_model, score, reasons + ["classifier: complex"], "classifier")

        # No classifier, or it failed: prefer being right over being cheap.
        return RouteDecision(self.pro_model, score, reasons + ["ambiguous, defaulting to pro"], "heuristic")

    def score(self, message: str) -> tuple[float, list[str]]:
        """Returns a complexity score. Positive leans Pro, negative leans Flash."""
        text = message.strip()
        lower = text.lower()
        score = 0.0
        reasons: list[str] = []

        def add(points: float, why: str) -> None:
            nonlocal score
            score += points
            reasons.append(f"{points:+.1f} {why}")

        # A bare greeting or acknowledgement never needs Pro.
        stripped = lower.rstrip("!.? ")
        if stripped in GREETINGS:
            add(-8.0, "greeting/acknowledgement")
            return score, reasons

        # Size. Long prompts carry more requirements to satisfy.
        est_tokens = len(text) / CHARS_PER_TOKEN
        if est_tokens > 400:
            add(4.0, f"very long (~{est_tokens:.0f} tok)")
        elif est_tokens > 150:
            add(2.5, f"long (~{est_tokens:.0f} tok)")
        elif est_tokens > 60:
            add(1.0, f"medium (~{est_tokens:.0f} tok)")
        elif est_tokens < 12:
            add(-1.5, f"very short (~{est_tokens:.0f} tok)")

        # Structure. Pasted code, traces, and step lists all mean real work.
        if CODE_FENCE.search(text):
            add(3.0, "contains code block")
        if STACK_TRACE.search(text):
            add(3.0, "contains error/traceback")
        step_count = len(NUMBERED_STEP.findall(text))
        if step_count >= 2:
            add(2.5, f"{step_count} numbered steps")
        line_count = text.count("\n")
        if line_count > 8:
            add(2.0, f"{line_count} lines")
        elif line_count > 3:
            add(1.0, f"{line_count} lines")

        # Scope. Explicit breadth outweighs everything about phrasing.
        if any(marker in lower for marker in BREADTH_MARKERS):
            add(4.0, "codebase-wide scope")
        elif BREADTH_PATTERN.search(lower):
            add(3.0, "broad scope")

        # Something is misbehaving — that's an investigation, not a lookup.
        is_debugging = any(word in lower for word in PROBLEM_WORDS)
        if is_debugging:
            add(3.5, "problem/debugging signal")

        file_hits = len(set(FILE_PATH.findall(text)))
        if file_hits >= 3:
            add(3.0, f"{file_hits} files referenced")
        elif file_hits == 2:
            add(1.5, "2 files referenced")

        # Intent. An action verb near the start is a request to change code.
        opening = " ".join(lower.split()[:6])
        if any(verb in opening for verb in ACTION_VERBS):
            add(3.0, "action verb (mutating request)")
        elif any(f" {verb} " in f" {lower} " for verb in ACTION_VERBS):
            add(1.5, "action verb present")

        # Multi-part requests ("do X and also Y") need more planning.
        if " and then " in lower or " also " in lower or lower.count(" and ") >= 2:
            add(1.5, "multi-part request")

        # A plain read-only ask about one thing stays cheap.
        if any(lower.startswith(verb) for verb in READONLY_VERBS) and file_hits <= 1 and not is_debugging:
            add(-2.0, "read-only request")

        # Questions lean simple — but only when nothing above flagged real work.
        # This ordering is the fix for "what is wrong with my entire auth
        # system?", where the question opener used to beat the scope and
        # debugging signals purely because of how the sentence started.
        if any(lower.startswith(opener) for opener in QUESTION_OPENERS):
            if score <= 1.0 and not is_debugging:
                add(-3.0, "question opener, no complexity signals")
            else:
                reasons.append("+0.0 question opener (outweighed)")

        if text.endswith("?") and est_tokens < 25 and score <= 0 and not is_debugging:
            add(-1.5, "short question")

        return score, reasons

    def _classify(self, message: str) -> str | None:
        """Asks the injected classifier to break a tie. Never raises."""
        try:
            self._classifier_calls += 1
            raw = self.classifier(CLASSIFIER_PROMPT.format(message=message[:2000]))
            if not raw:
                return None
            verdict = raw.strip().upper()
            if "COMPLEX" in verdict:
                return "COMPLEX"
            if "SIMPLE" in verdict:
                return "SIMPLE"
            return None
        except Exception:
            # A failed tie-break shouldn't fail the user's turn.
            return None

    @property
    def last_decision(self) -> RouteDecision | None:
        return self._history[-1] if self._history else None

    @property
    def stats(self) -> dict:
        pro_count = sum(1 for d in self._history if d.model == self.pro_model)
        flash_count = sum(1 for d in self._history if d.model == self.flash_model)
        return {
            "pro_calls": pro_count,
            "flash_calls": flash_count,
            "classifier_calls": self._classifier_calls,
            "estimated_savings": f"~${flash_count * 0.01:.2f} saved by using Flash",
        }
