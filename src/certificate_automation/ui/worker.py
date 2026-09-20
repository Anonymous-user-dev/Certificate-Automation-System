"""Qt worker bridges for slow core operations."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QObject, Signal, Slot


class OperationWorker(QObject):
    finished = Signal(object)
    failed = Signal(object)

    def __init__(self, operation: Callable[[], object]) -> None:
        super().__init__()
        self._operation = operation

    @Slot()
    def run(self) -> None:
        try:
            self.finished.emit(self._operation())
        except Exception as error:
            self.failed.emit(error)


class GenerationWorker(QObject):
    progress = Signal(object)
    finished = Signal(object)
    failed = Signal(object)

    def __init__(self, generator, request, cancellation) -> None:
        super().__init__()
        self._generator = generator
        self._request = request
        self._cancellation = cancellation

    @Slot()
    def run(self) -> None:
        try:
            result = self._generator.generate(
                self._request,
                progress=self.progress.emit,
                cancellation=self._cancellation,
            )
            self.finished.emit(result)
        except Exception as error:
            self.failed.emit(error)

