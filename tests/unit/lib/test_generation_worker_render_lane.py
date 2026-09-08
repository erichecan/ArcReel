"""``render`` lane（一键成片等不调用 AI 供应商的本地任务）容量与 provider 投影单测。

不经完整 worker/DB 循环，直接验证：
- ``_extract_provider`` 对 ``media_type="render"`` 立即返回哨兵 provider "render"，
  不触发任何 project/config 加载（与既有 "text" 哨兵同一套路）。
- ``CapacityTable`` 对未知 provider + ``media_type="render"`` 回落到 ``_defaults["render"]``。
"""

from __future__ import annotations

from lib.generation_worker import CapacityTable, _extract_provider


async def test_render_media_type_returns_sentinel_without_project_lookup() -> None:
    # project_name 指向不存在的项目：若代码误走了通用兜底分支（会尝试 load_project），
    # 这里就会抛 FileNotFoundError 而不是直接命中哨兵分支。
    provider_id = await _extract_provider(
        {"task_type": "reference_video_compose", "media_type": "render", "project_name": "does-not-exist"}
    )
    assert provider_id == "render"


def test_unknown_provider_falls_back_to_render_default() -> None:
    table = CapacityTable(_limits={}, _defaults={"image": 5, "video": 3, "audio": 10, "text": 1, "render": 1})
    assert table.get("render", "render") == 1
    assert table.get("some-unregistered-provider", "render") == 1


def test_from_env_defaults_include_render() -> None:
    table = CapacityTable.from_env()
    assert table.get("render-sentinel-not-a-real-provider", "render") == 1
