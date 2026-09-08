"""``lib/video_compose.py``（"一键成片"用的 ffmpeg 拼接核心）单测。

`_resolve_fps` / `_coerce_numeric_duration` / `_build_xfade_filter_complex` 与
``agent_runtime_profile`` 下 compose_video.py 的同名函数逻辑一致（两份独立实现，
不共用代码，见模块 docstring），那边已有完整矩阵测试
（``tests/unit/test_compose_video_filter_graph.py``），这里只做代表性冒烟；重点覆盖
本模块新增的旁白替换音轨与 episode 级拼接入口逻辑。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from lib import video_compose

# ---------------------------------------------------------------------------
# 纯函数冒烟（完整矩阵见 compose_video.py 自己的测试）
# ---------------------------------------------------------------------------


class TestPureHelpersSmoke:
    def test_resolve_fps_falls_back_on_zero_over_zero(self) -> None:
        assert video_compose._resolve_fps("0/0", "24/1") == "24/1"

    def test_resolve_fps_defaults_to_30(self) -> None:
        assert video_compose._resolve_fps(None, None) == "30"

    def test_coerce_numeric_duration_rejects_na(self) -> None:
        assert video_compose._coerce_numeric_duration("N/A") is None

    def test_coerce_numeric_duration_parses_valid(self) -> None:
        assert video_compose._coerce_numeric_duration("4.5") == 4.5

    def test_build_xfade_all_cut_returns_none(self) -> None:
        assert video_compose._build_xfade_filter_complex([4.0, 4.0], ["cut"], 0.5) is None

    def test_build_xfade_fade_produces_filter(self) -> None:
        result = video_compose._build_xfade_filter_complex([4.0, 4.0], ["fade"], 0.5)
        assert result is not None
        assert "xfade=transition=fade" in result
        assert "acrossfade=d=0.5" in result


# ---------------------------------------------------------------------------
# normalize_clip：旁白替换音轨（以视频时长为主轴）
# ---------------------------------------------------------------------------


class TestNormalizeClipNarration:
    def test_narration_shorter_than_video_is_padded_and_trimmed_to_video_duration(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """旁白比视频短或长，输出时长都恒等于视频时长——用 apad+atrim 一次性覆盖两种情况。"""
        monkeypatch.setattr(
            video_compose,
            "probe_media",
            lambda _path: {"width": 1080, "height": 1920, "fps": "30", "duration": 6.0, "has_audio": True},
        )
        captured: list[list[str]] = []
        monkeypatch.setattr(video_compose, "run_ffmpeg", lambda cmd, _prefix: captured.append(cmd))

        video_compose.normalize_clip(
            tmp_path / "in.mp4",
            tmp_path / "out.mp4",
            target_width=1080,
            target_height=1920,
            target_fps="30",
            narration_audio_path=tmp_path / "narration.wav",
        )

        assert len(captured) == 1
        cmd = captured[0]
        filter_complex = cmd[cmd.index("-filter_complex") + 1]
        assert "apad" in filter_complex
        assert "atrim=duration=6.000000" in filter_complex
        # 旁白输入是第二个 -i，不是视频自己的音轨
        assert "[1:a]" in filter_complex
        assert str((tmp_path / "narration.wav").resolve()) in cmd

    def test_no_narration_uses_video_own_audio(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setattr(
            video_compose,
            "probe_media",
            lambda _path: {"width": 1080, "height": 1920, "fps": "30", "duration": 4.0, "has_audio": True},
        )
        captured: list[list[str]] = []
        monkeypatch.setattr(video_compose, "run_ffmpeg", lambda cmd, _prefix: captured.append(cmd))

        video_compose.normalize_clip(
            tmp_path / "in.mp4",
            tmp_path / "out.mp4",
            target_width=1080,
            target_height=1920,
            target_fps="30",
        )

        filter_complex = captured[0][captured[0].index("-filter_complex") + 1]
        assert "[0:a]" in filter_complex
        assert "apad" not in filter_complex

    def test_no_narration_and_no_source_audio_uses_silent_track(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setattr(
            video_compose,
            "probe_media",
            lambda _path: {"width": 1080, "height": 1920, "fps": "30", "duration": 4.0, "has_audio": False},
        )
        captured: list[list[str]] = []
        monkeypatch.setattr(video_compose, "run_ffmpeg", lambda cmd, _prefix: captured.append(cmd))

        video_compose.normalize_clip(
            tmp_path / "in.mp4",
            tmp_path / "out.mp4",
            target_width=1080,
            target_height=1920,
            target_fps="30",
        )

        assert any("anullsrc" in arg for arg in captured[0])


# ---------------------------------------------------------------------------
# normalize_clips：narration_audio_paths 长度校验
# ---------------------------------------------------------------------------


def test_normalize_clips_rejects_mismatched_narration_length(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="长度必须与"):
        video_compose.normalize_clips(
            [tmp_path / "a.mp4", tmp_path / "b.mp4"],
            tmp_path,
            narration_audio_paths=[None],
        )


# ---------------------------------------------------------------------------
# concatenate_final：单段直接 remux，不走 concat filter
# ---------------------------------------------------------------------------


def test_concatenate_final_single_clip_skips_concat_filter(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    captured: list[list[str]] = []
    monkeypatch.setattr(video_compose, "run_ffmpeg", lambda cmd, _prefix: captured.append(cmd))
    clip = tmp_path / "clip.mp4"
    clip.write_bytes(b"\x00" * 16)

    video_compose.concatenate_final([clip], tmp_path / "final.mp4")

    cmd = captured[0]
    assert cmd[cmd.index("-c") + 1] == "copy"
    assert not any("concat=" in arg for arg in cmd)


def test_concatenate_final_empty_list_raises(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="没有可用的视频片段"):
        video_compose.concatenate_final([], tmp_path / "unused.mp4")


# ---------------------------------------------------------------------------
# compose_episode：按 transitions 是否全 cut 分派
# ---------------------------------------------------------------------------


class TestComposeEpisodeDispatch:
    def test_all_cut_dispatches_to_concatenate_simple(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        calls: list[str] = []
        monkeypatch.setattr(video_compose, "concatenate_simple", lambda *a, **k: calls.append("simple"))
        monkeypatch.setattr(
            video_compose,
            "concatenate_with_transitions",
            lambda *a, **k: calls.append("transitions"),
        )

        output = tmp_path / "nested" / "final_cut.mp4"
        video_compose.compose_episode(
            [tmp_path / "a.mp4", tmp_path / "b.mp4"],
            ["cut"],
            output,
        )

        assert calls == ["simple"]
        assert output.parent.is_dir()

    def test_any_non_cut_dispatches_to_transitions(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        calls: list[str] = []
        monkeypatch.setattr(video_compose, "concatenate_simple", lambda *a, **k: calls.append("simple"))
        monkeypatch.setattr(
            video_compose,
            "concatenate_with_transitions",
            lambda *a, **k: calls.append("transitions"),
        )

        video_compose.compose_episode(
            [tmp_path / "a.mp4", tmp_path / "b.mp4"],
            ["fade"],
            tmp_path / "final.mp4",
        )

        assert calls == ["transitions"]

    def test_empty_video_paths_raises(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="没有可用的视频片段"):
            video_compose.compose_episode([], [], tmp_path / "final.mp4")
