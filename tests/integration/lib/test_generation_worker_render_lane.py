"""``render`` lane 端到端：全局并发固定为 1，且不阻塞其它 lane（同 ``test_generation_worker_text_lane.py``）。"""

from __future__ import annotations

import asyncio
from typing import Any

from lib.generation_queue import GenerationQueue
from lib.generation_queue_client import wait_for_task
from lib.generation_worker import CapacityTable, GenerationWorker


async def test_render_lane_is_serial_and_does_not_block_video(file_db_factory) -> None:
    queue = GenerationQueue(session_factory=file_db_factory)
    project_name = "render-lane-test-missing-project"
    first_render_started = asyncio.Event()
    second_render_started = asyncio.Event()
    release_first_render = asyncio.Event()
    render_calls = 0

    async def execute(task: dict[str, Any], *, claimed_provider_id: str | None = None) -> dict[str, Any]:
        nonlocal render_calls
        del claimed_provider_id
        if task["media_type"] == "render":
            render_calls += 1
            if render_calls == 1:
                first_render_started.set()
                await release_first_render.wait()
            else:
                second_render_started.set()
        return {}

    async def provider(task: dict[str, Any]) -> str:
        return str(task["provider_id"])

    first = await queue.enqueue_task(
        project_name=project_name,
        task_type="reference_video_compose",
        media_type="render",
        resource_id="1",
        provider_id="render",
    )
    second = await queue.enqueue_task(
        project_name=project_name,
        task_type="reference_video_compose",
        media_type="render",
        resource_id="2",
        provider_id="render",
    )
    video = await queue.enqueue_task(
        project_name=project_name,
        task_type="video",
        media_type="video",
        resource_id="scene-1",
        provider_id="video",
    )
    worker = GenerationWorker(
        queue=queue,
        capacity=CapacityTable(_limits={}, _defaults={"video": 1, "render": 1}),
        provider_projection=provider,
        executor=execute,
        lanes=("video", "render"),
    )
    worker.poll_interval = 0.01
    worker.heartbeat_interval = 0.01
    await worker.start()
    try:
        await first_render_started.wait()
        video_task = await wait_for_task(video["task_id"], 0.01, queue=queue)
        queued_second = await queue.get_task(second["task_id"])

        assert video_task["status"] == "succeeded"
        assert queued_second is not None
        assert queued_second["status"] == "queued"
        assert not second_render_started.is_set()

        release_first_render.set()
        await second_render_started.wait()
        assert (await wait_for_task(first["task_id"], 0.01, queue=queue))["status"] == "succeeded"
        assert (await wait_for_task(second["task_id"], 0.01, queue=queue))["status"] == "succeeded"
    finally:
        release_first_render.set()
        await worker.stop()
