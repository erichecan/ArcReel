"""``server/services/reference_video_compose.py`` 的准入判定单测。"""

from __future__ import annotations

from server.services.reference_video_compose import missing_video_clip_unit_ids


def _unit(unit_id: str, video_clip: str | None) -> dict:
    return {
        "unit_id": unit_id,
        "generated_assets": ({"video_clip": video_clip} if video_clip else {}),
    }


def test_all_units_ready_returns_empty_list() -> None:
    units = [_unit("E1U1", "reference_videos/E1U1.mp4"), _unit("E1U2", "reference_videos/E1U2.mp4")]
    assert missing_video_clip_unit_ids(units) == []


def test_missing_units_are_collected_all_or_nothing() -> None:
    units = [
        _unit("E1U1", "reference_videos/E1U1.mp4"),
        _unit("E1U2", None),
        _unit("E1U3", None),
    ]
    assert missing_video_clip_unit_ids(units) == ["E1U2", "E1U3"]


def test_empty_units_list_returns_empty_list() -> None:
    assert missing_video_clip_unit_ids([]) == []
