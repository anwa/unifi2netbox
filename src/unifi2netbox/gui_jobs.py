"""Run one blocking function on the thread pool and report on the GUI thread.

Used for short network tasks (library index, techspecs lookups) that are not
part of a refresh or write run. Exceptions are delivered as the result, so the
slot decides how to show them.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Slot


class TaskSignals(QObject):
    finished = Signal(object)


class TaskJob(QRunnable):
    def __init__(self, function: Callable[[], object]) -> None:
        super().__init__()
        self.function = function
        self.signals = TaskSignals()

    @Slot()
    def run(self) -> None:
        try:
            result = self.function()
        except Exception as error:  # noqa: BLE001 - reported to the caller
            result = error
        self.signals.finished.emit(result)


class TaskRunner(QObject):
    """At most one task at a time; ``finished`` carries result or exception."""

    finished = Signal(object)

    def __init__(self, pool: QThreadPool, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.pool = pool
        self.job: TaskJob | None = None

    @property
    def busy(self) -> bool:
        return self.job is not None

    def start(self, function: Callable[[], object]) -> bool:
        if self.busy:
            return False
        self.job = TaskJob(function)
        self.job.signals.finished.connect(self._finished)
        self.pool.start(self.job)
        return True

    @Slot(object)
    def _finished(self, result: object) -> None:
        self.job = None
        self.finished.emit(result)
