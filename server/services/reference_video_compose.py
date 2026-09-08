"""参考生视频「一键成片」：把一集所有 video_units 的成片 + 各自旁白拼接渲染成一条 mp4。

产物按 episode 粒度落在 ``presentations/episode_N/final_cut.mp4``（见
``lib.episode_paths.episode_final_cut_relpath``），不进 ``generated_assets``——它不属于
任何单个 unit，而是这些 unit 已生成成片的一个聚合视图。
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from lib.db.base import DEFAULT_USER_ID
from lib.episode_paths import episode_final_cut_relpath
from lib.path_safety import safe_join, try_safe_join
from lib.project_manager import get_project_manager
from lib.script_models import get_generated_assets
from lib.video_compose import compose_episode


def missing_video_clip_unit_ids(units: list[dict[str, Any]]) -> list[str]:
    """该 episode 下还没有成片的 unit_id 列表；空列表即可一键成片（全有或全无）。"""
    return [str(unit.get("unit_id")) for unit in units if not get_generated_assets(unit).get("video_clip")]


def _prepare_compose_inputs(
    project_name: str,
    episode: int,
    script_file: str,
) -> tuple[list[Path], list[Path | None], list[str], Path]:
    """加载剧本、校验全部 unit 已就绪，解析出拼接所需的绝对路径序列。

    以 ``asyncio.to_thread`` 从执行体调用（文件系统 + 剧本解析，同步阻塞）。
    """
    pm = get_project_manager()
    project_path = pm.get_project_path(project_name)
    script = pm.load_script(project_name, script_file)
    units = script.get("video_units") or []
    if not units:
        raise ValueError(f"episode {episode} 没有视频单元，无法一键成片")

    missing = missing_video_clip_unit_ids(units)
    if missing:
        raise ValueError(f"以下单元还没有生成成片，无法一键成片: {', '.join(missing)}")

    video_paths: list[Path] = []
    narration_paths: list[Path | None] = []
    transitions: list[str] = []
    for unit in units:
        assets = get_generated_assets(unit)
        video_clip = str(assets.get("video_clip") or "")
        video_path = safe_join(project_path, video_clip, must_exist=True, require_file=True)
        video_paths.append(video_path)

        narration_audio = assets.get("narration_audio")
        narration_path = (
            try_safe_join(project_path, str(narration_audio), require_file=True) if narration_audio else None
        )
        narration_paths.append(narration_path)

        transitions.append(str(unit.get("transition_to_next") or "cut"))

    output_path = project_path / episode_final_cut_relpath(episode)
    return video_paths, narration_paths, transitions, output_path


async def execute_reference_video_compose_task(
    project_name: str,
    resource_id: str,
    payload: dict[str, Any],
    *,
    user_id: str = DEFAULT_USER_ID,
    task_id: str | None = None,
) -> dict[str, Any]:
    """任务执行体：``resource_id`` 是 episode 号的字符串形式。"""
    episode = int(resource_id)
    script_file = payload.get("script_file")
    if not script_file:
        raise ValueError("reference_video_compose task 需要 payload.script_file")

    video_paths, narration_paths, transitions, output_path = await asyncio.to_thread(
        _prepare_compose_inputs, project_name, episode, str(script_file)
    )

    await asyncio.to_thread(
        compose_episode,
        video_paths,
        transitions,
        output_path,
        narration_audio_paths=narration_paths,
    )

    return {"episode": episode, "final_cut": episode_final_cut_relpath(episode)}
