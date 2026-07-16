"""Redis-backed demo worker with cooperative SIGTERM draining."""

from __future__ import annotations

import asyncio
import json
import os
import signal
from typing import Any

from redis.asyncio import Redis


class GracefulWorker:
    def __init__(self, redis: Redis, *, queue: str = "amazon-ai:jobs") -> None:
        self.redis = redis
        self.queue = queue
        self.stopping = asyncio.Event()
        self.current_job: asyncio.Task[None] | None = None

    def request_stop(self) -> None:
        self.stopping.set()

    async def handle(self, payload: dict[str, Any]) -> None:
        """Only dispatch approved job kinds; business modules own calculations."""
        if payload.get("kind") not in {"sync_sales", "refresh_policy_index"}:
            raise ValueError("unsupported worker job kind")
        await asyncio.sleep(0)

    async def run(self) -> None:
        while not self.stopping.is_set():
            item = await self.redis.brpop(self.queue, timeout=1)
            if item is None:
                continue
            try:
                payload = json.loads(item[1])
            except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                raise ValueError("worker received invalid JSON") from exc
            self.current_job = asyncio.create_task(self.handle(payload))
            try:
                await self.current_job
            finally:
                self.current_job = None
        if self.current_job:
            await self.current_job


async def main() -> None:
    redis = Redis.from_url(os.getenv("REDIS_URL", "redis://redis:6379/0"))
    worker = GracefulWorker(redis)
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(signum, worker.request_stop)
    try:
        await worker.run()
    finally:
        await redis.aclose()


if __name__ == "__main__":
    asyncio.run(main())
