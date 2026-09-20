from certificate_automation.ui.worker import GenerationWorker, OperationWorker


def test_operation_worker_emits_failure():
    error = RuntimeError("operation failed")
    worker = OperationWorker(lambda: (_ for _ in ()).throw(error))
    failures = []
    worker.failed.connect(failures.append)

    worker.run()

    assert failures == [error]


def test_generation_worker_emits_failure():
    error = RuntimeError("generation failed")

    class BrokenGenerator:
        def generate(self, request, progress, cancellation):
            raise error

    worker = GenerationWorker(BrokenGenerator(), object(), object())
    failures = []
    worker.failed.connect(failures.append)

    worker.run()

    assert failures == [error]
