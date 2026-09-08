"""Process-local, bounded progress state for synchronous preflight scans."""

from __future__ import annotations

from collections import OrderedDict
from enum import Enum
from threading import Lock
from time import time
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field


class ScanProgressState(str, Enum):
    RUNNING = "RUNNING"
    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"


class ScanProgressStage(str, Enum):
    RECEIVING_MEDIA = "receiving_media"
    PREPARING_MEDIA = "preparing_media"
    TECHNICAL_CHECKS = "technical_checks"
    PREPARING_AI_MEDIA = "preparing_ai_media"
    OPENING_REVIEW = "opening_review"
    CONTINUITY_REVIEW = "continuity_review"
    FACTUAL_REVIEW = "factual_review"
    PREPARING_REVIEW = "preparing_review"
    FINAL_REPORT = "final_report"
    COMPLETE = "complete"
    FAILED = "failed"


class ScanProgressTask(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: str
    label: str
    status: str = Field(pattern="^(Done|Working|Waiting|Unavailable)$")


class ScanProgress(BaseModel):
    model_config = ConfigDict(extra="forbid")

    progress_id: str
    review_mode: str = Field(pattern="^(full|local)$")
    state: ScanProgressState
    stage: ScanProgressStage
    percent: int = Field(ge=0, le=100)
    message: str
    created_at_epoch_seconds: float
    updated_at_epoch_seconds: float
    tasks: list[ScanProgressTask]


_FULL_TASKS = (
    ("technical", "Picture and sound"),
    ("opening", "Opening review"),
    ("continuity", "Edit continuity"),
    ("factual", "Content and claims"),
    ("summary", "Preparing your review"),
)
_LOCAL_TASKS = (
    ("technical", "Picture, sound, captions, and publishing details"),
    ("summary", "Preparing your review"),
)
_TASK_FOR_STAGE = {
    ScanProgressStage.RECEIVING_MEDIA: None,
    ScanProgressStage.PREPARING_MEDIA: None,
    ScanProgressStage.TECHNICAL_CHECKS: "technical",
    ScanProgressStage.PREPARING_AI_MEDIA: None,
    ScanProgressStage.OPENING_REVIEW: "opening",
    ScanProgressStage.CONTINUITY_REVIEW: "continuity",
    ScanProgressStage.FACTUAL_REVIEW: "factual",
    ScanProgressStage.PREPARING_REVIEW: "summary",
    ScanProgressStage.FINAL_REPORT: "summary",
    ScanProgressStage.COMPLETE: None,
    ScanProgressStage.FAILED: None,
}


class ScanProgressStore:
    """Keep a small number of recent scan progress records in this process."""

    def __init__(self, *, maximum_records: int = 64) -> None:
        self._maximum_records = maximum_records
        self._records: OrderedDict[str, ScanProgress] = OrderedDict()
        self._lock = Lock()

    def create(self, review_mode: str, *, progress_id: str | None = None) -> ScanProgress:
        now = time()
        progress_id = progress_id or str(uuid4())
        if not _valid_progress_id(progress_id):
            raise ValueError("progress_id must be a UUID")
        record = ScanProgress(
            progress_id=progress_id,
            review_mode=review_mode,
            state=ScanProgressState.RUNNING,
            stage=ScanProgressStage.RECEIVING_MEDIA,
            percent=1,
            message="Getting the video ready",
            created_at_epoch_seconds=now,
            updated_at_epoch_seconds=now,
            tasks=self._tasks(review_mode, ScanProgressStage.RECEIVING_MEDIA),
        )
        with self._lock:
            self._records[progress_id] = record
            while len(self._records) > self._maximum_records:
                self._records.popitem(last=False)
        return record.model_copy(deep=True)

    def ensure(self, progress_id: str, review_mode: str) -> ScanProgress | None:
        current = self.get(progress_id)
        if current is not None:
            return current
        if not _valid_progress_id(progress_id):
            return None
        return self.create(review_mode, progress_id=progress_id)

    def get(self, progress_id: str) -> ScanProgress | None:
        if not _valid_progress_id(progress_id):
            return None
        with self._lock:
            record = self._records.get(progress_id)
            return record.model_copy(deep=True) if record else None

    def update(
        self,
        progress_id: str,
        stage: ScanProgressStage,
        percent: int,
        message: str,
        *,
        state: ScanProgressState = ScanProgressState.RUNNING,
    ) -> None:
        with self._lock:
            current = self._records.get(progress_id)
            if current is None or current.state is not ScanProgressState.RUNNING:
                return
            if percent < current.percent:
                return
            if percent >= 100 and state is ScanProgressState.RUNNING:
                percent = 99
            current.stage = stage
            current.percent = percent
            current.message = message
            current.state = state
            current.updated_at_epoch_seconds = time()
            current.tasks = self._tasks(current.review_mode, stage, state)

    def finish(self, progress_id: str, *, partial: bool = False) -> None:
        if not partial:
            self.update(
                progress_id, ScanProgressStage.COMPLETE, 100, "Your review is ready",
                state=ScanProgressState.COMPLETE,
            )
            return
        with self._lock:
            current = self._records.get(progress_id)
            if current is None or current.state is not ScanProgressState.RUNNING:
                return
            current.state = ScanProgressState.PARTIAL
            current.stage = ScanProgressStage.COMPLETE
            current.percent = 100
            current.message = "Your completed review is ready"
            current.updated_at_epoch_seconds = time()
            current.tasks = [task.model_copy(update={"status": (
                "Done" if task.task_id == "technical" else "Unavailable"
            )}) for task in current.tasks]

    def fail(self, progress_id: str) -> None:
        with self._lock:
            current = self._records.get(progress_id)
            if current is None or current.state is not ScanProgressState.RUNNING:
                return
            current.state = ScanProgressState.FAILED
            current.stage = ScanProgressStage.FAILED
            current.percent = min(current.percent, 99)
            current.message = "The scan could not be completed"
            current.updated_at_epoch_seconds = time()
            current.tasks = [task.model_copy(update={"status": (
                "Unavailable" if task.status == "Working" else task.status
            )}) for task in current.tasks]

    def delete(self, progress_id: str) -> None:
        with self._lock:
            self._records.pop(progress_id, None)

    @staticmethod
    def _tasks(
        review_mode: str,
        stage: ScanProgressStage,
        state: ScanProgressState = ScanProgressState.RUNNING,
    ) -> list[ScanProgressTask]:
        definitions = _FULL_TASKS if review_mode == "full" else _LOCAL_TASKS
        current_id = _TASK_FOR_STAGE[stage]
        ids = [item[0] for item in definitions]
        current_index = ids.index(current_id) if current_id in ids else -1
        completed_without_current = 1 if stage is ScanProgressStage.PREPARING_AI_MEDIA else 0
        tasks = []
        for index, (task_id, label) in enumerate(definitions):
            if state in {ScanProgressState.COMPLETE, ScanProgressState.PARTIAL}:
                status = "Done" if state is ScanProgressState.COMPLETE or index < current_index else "Unavailable"
            elif state is ScanProgressState.FAILED:
                status = "Done" if index < current_index else "Unavailable" if index == current_index else "Waiting"
            elif current_index < 0:
                status = "Done" if index < completed_without_current else "Waiting"
            elif index < current_index:
                status = "Done"
            elif index == current_index:
                status = "Working"
            else:
                status = "Waiting"
            tasks.append(ScanProgressTask(task_id=task_id, label=label, status=status))
        return tasks


def _valid_progress_id(value: str) -> bool:
    try:
        return str(UUID(value)) == value
    except (ValueError, AttributeError):
        return False
