from __future__ import annotations

import asyncio

from amazon_ai_platform.worker import GracefulWorker


class FakeRedis:
    def __init__(self) -> None:
        self.calls = 0

    async def brpop(self, queue, timeout):
        self.calls += 1
        return b"queue", b'{"kind":"sync_sales"}'


def test_worker_finishes_current_job_before_graceful_exit() -> None:
    handled: list[str] = []

    class Worker(GracefulWorker):
        async def handle(self, payload):
            handled.append(payload["kind"])
            await asyncio.sleep(0)
            self.request_stop()

    worker = Worker(FakeRedis())
    asyncio.run(worker.run())
    assert handled == ["sync_sales"]
    assert worker.current_job is None
