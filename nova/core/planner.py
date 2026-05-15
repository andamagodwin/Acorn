"""Task planning and decomposition for multi-step operations."""
from dataclasses import dataclass, field
from enum import Enum


class TaskStatus(Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class Task:
    id: int
    description: str
    status: TaskStatus = TaskStatus.PENDING
    result: str = ""

    @property
    def status_icon(self) -> str:
        icons = {
            TaskStatus.PENDING: "○",
            TaskStatus.IN_PROGRESS: "◐",
            TaskStatus.COMPLETED: "●",
            TaskStatus.FAILED: "✗",
            TaskStatus.SKIPPED: "⊘",
        }
        return icons[self.status]


class Planner:
    """Manages multi-step task execution plans."""

    def __init__(self):
        self.tasks: list[Task] = []
        self._next_id = 1

    def create_plan(self, tasks: list[str]) -> list[Task]:
        """Creates a new execution plan from a list of task descriptions."""
        self.tasks.clear()
        self._next_id = 1
        for desc in tasks:
            self.tasks.append(Task(id=self._next_id, description=desc))
            self._next_id += 1
        return self.tasks

    def start_task(self, task_id: int) -> None:
        task = self._get_task(task_id)
        if task:
            task.status = TaskStatus.IN_PROGRESS

    def complete_task(self, task_id: int, result: str = "") -> None:
        task = self._get_task(task_id)
        if task:
            task.status = TaskStatus.COMPLETED
            task.result = result

    def fail_task(self, task_id: int, error: str = "") -> None:
        task = self._get_task(task_id)
        if task:
            task.status = TaskStatus.FAILED
            task.result = error

    def get_next_pending(self) -> Task | None:
        for task in self.tasks:
            if task.status == TaskStatus.PENDING:
                return task
        return None

    @property
    def is_complete(self) -> bool:
        return all(
            t.status in (TaskStatus.COMPLETED, TaskStatus.SKIPPED, TaskStatus.FAILED)
            for t in self.tasks
        )

    @property
    def progress_display(self) -> str:
        if not self.tasks:
            return ""
        lines = ["┌─ Plan ─────────────────────────────────"]
        for task in self.tasks:
            lines.append(f"│ {task.status_icon} [{task.id}] {task.description}")
        completed = sum(1 for t in self.tasks if t.status == TaskStatus.COMPLETED)
        lines.append(f"└─ Progress: {completed}/{len(self.tasks)} ──────────────")
        return "\n".join(lines)

    def _get_task(self, task_id: int) -> Task | None:
        for task in self.tasks:
            if task.id == task_id:
                return task
        return None
