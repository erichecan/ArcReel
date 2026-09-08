"""参考生视频「一键成片」的 ffmpeg 拼接核心。

与 ``agent_runtime_profile/.claude/skills/compose-video/scripts/compose_video.py``
（Agent 沙箱内运行、面向 ``scenes[]`` 剧本的独立脚本）是两份独立实现，不共用代码：
后者的测试断言脚本源码内「唯一一处 ``subprocess.run``」与模块级 ``run_ffmpeg`` 的
monkeypatch seam，这两条约束要求该脚本的 ffmpeg 调用链物理留在其自身文件内，无法
抽成可 import 的公共层；同时它要兼容任意用户环境（PATH 缺失时探测各平台常见安装位）。

这里服务的是运行在项目 Docker 镜像内的后端任务：镜像已通过 ``apt-get install
ffmpeg`` 保证 ffmpeg/ffprobe 在 PATH（见仓库根 ``Dockerfile``），不需要那套跨平台
探测，直接 ``shutil.which`` 即可，失败就是真的缺失。
"""

from __future__ import annotations

import json
import math
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import TypedDict

_FFMPEG_TOOLS_HINT = "需要 ffmpeg 和 ffprobe 同时可用（PATH 中）"
_FFMPEG_TOOL_NAMES = ("ffmpeg", "ffprobe")


def ffmpeg_available() -> bool:
    """ffmpeg 与 ffprobe 是否都能在 PATH 上找到。"""
    return all(shutil.which(tool) is not None for tool in _FFMPEG_TOOL_NAMES)


def run_capture(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    """脚本内唯一的子进程入口：首位工具名解析为绝对路径，强制 UTF-8 解码。

    `text=True` 会按系统 locale 解码（中文 Windows 为 GBK），含非 GBK 字符的路径或
    媒体元数据会让 stderr 解码抛 UnicodeDecodeError，故显式指定 UTF-8（见
    `.claude/rules/windows-compat.md`）。
    """
    if not cmd:
        raise ValueError("命令不能为空")
    tool = cmd[0]
    if tool in _FFMPEG_TOOL_NAMES:
        resolved = shutil.which(tool)
        if resolved is None:
            raise RuntimeError(f"未找到可执行的 {tool}。{_FFMPEG_TOOLS_HINT}")
        cmd = [resolved, *cmd[1:]]
    return subprocess.run(cmd, capture_output=True, encoding="utf-8", errors="replace")


def run_ffmpeg(cmd: list[str], error_prefix: str) -> None:
    """执行 ffmpeg / ffprobe 命令并在失败时抛出完整错误。"""
    result = run_capture(cmd)
    if result.returncode != 0:
        raise RuntimeError(f"{error_prefix}: {result.stderr}")


def _resolve_fps(avg_frame_rate: object, r_frame_rate: object) -> str:
    """从 ffprobe 字段解析 fps。

    `avg_frame_rate="0/0"` 是常见的伪真值（部分 GIF→MP4 转换 / 屏幕录制软件输出），
    若用 `or` 链 fallback，下游 ffmpeg 滤镜会被喂入 `"0/0"` 直接失败。
    这里显式黑名单 `{"0/0","0",""}`，优先 avg，再 r，最后回退 `"30"`。
    """
    for value in (avg_frame_rate, r_frame_rate):
        if value is None:
            continue
        candidate = str(value).strip()
        if candidate in {"0/0", "0", ""}:
            continue
        return candidate
    return "30"


def _coerce_numeric_duration(raw: object) -> float | None:
    """把 ffprobe 的 duration 字段安全转成 float，无效值返回 None。"""
    if raw is None:
        return None
    candidate = str(raw).strip()
    if not candidate or candidate.upper() == "N/A":
        return None
    try:
        value = float(candidate)
    except ValueError:
        return None
    if not math.isfinite(value) or value <= 0:
        return None
    return value


def get_video_duration(video_path: Path) -> float:
    """获取视频时长（秒）。"""
    result = run_capture(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(video_path),
        ]
    )
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe 执行失败: {result.stderr}")
    try:
        return float(result.stdout.strip())
    except ValueError as exc:
        raise RuntimeError(f"无法解析视频时长: {video_path}") from exc


class MediaInfo(TypedDict):
    width: int
    height: int
    fps: str
    duration: float
    has_audio: bool


def probe_media(video_path: Path) -> MediaInfo:
    """读取片段的基础媒体信息，用于统一中间片规格。"""
    result = run_capture(
        [
            "ffprobe",
            "-v",
            "error",
            "-print_format",
            "json",
            "-show_streams",
            "-show_format",
            str(video_path),
        ]
    )
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe 执行失败: {result.stderr}")

    try:
        payload = json.loads(result.stdout)
    except ValueError as exc:
        raise RuntimeError(f"无法解析 ffprobe 输出: {video_path}") from exc

    streams = payload.get("streams", [])
    video_stream = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio_stream = next((s for s in streams if s.get("codec_type") == "audio"), None)
    if not video_stream:
        raise RuntimeError(f"缺少视频流: {video_path}")

    fps = _resolve_fps(video_stream.get("avg_frame_rate"), video_stream.get("r_frame_rate"))

    duration = _coerce_numeric_duration(video_stream.get("duration"))
    if duration is None:
        duration = _coerce_numeric_duration(payload.get("format", {}).get("duration"))
    if duration is None:
        raise RuntimeError(f"无法从 ffprobe 输出中获取时长: {video_path}")

    width = int(video_stream.get("width") or 0)
    height = int(video_stream.get("height") or 0)
    if width <= 0 or height <= 0:
        raise RuntimeError(f"无法解析视频分辨率: {video_path}")

    return {
        "width": width,
        "height": height,
        "fps": fps,
        "duration": duration,
        "has_audio": audio_stream is not None,
    }


def normalize_clip(
    video_path: Path,
    output_path: Path,
    *,
    target_width: int,
    target_height: int,
    target_fps: str,
    narration_audio_path: Path | None = None,
) -> None:
    """把单个片段重编码为统一中间片，再供最终拼接使用。

    `narration_audio_path` 提供时，该片段的音轨整段替换为旁白（不与原始视频自带
    音轨混音）：以视频时长为主轴，旁白短则静音补齐（`apad`）、长则截断
    （`atrim`），不允许旁白反过来拉长这个片段的时长——否则相邻片段的转场/拼接
    时间轴会跟着漂移。
    """
    media = probe_media(video_path)
    video_filter = (
        f"scale={target_width}:{target_height}:force_original_aspect_ratio=decrease,"
        f"pad={target_width}:{target_height}:(ow-iw)/2:(oh-ih)/2:black,"
        f"setsar=1,fps={target_fps},format=yuv420p,setpts=PTS-STARTPTS"
    )
    video_duration = float(media["duration"])

    if narration_audio_path is not None:
        filter_complex = (
            f"[0:v]{video_filter}[vout];"
            f"[1:a]aresample=48000,aformat=channel_layouts=stereo,apad,"
            f"atrim=duration={video_duration:.6f},asetpts=PTS-STARTPTS[aout]"
        )
        inputs = ["-i", str(video_path.resolve()), "-i", str(narration_audio_path.resolve())]
    elif media["has_audio"]:
        filter_complex = (
            f"[0:v]{video_filter}[vout];[0:a]aresample=48000,aformat=channel_layouts=stereo,asetpts=PTS-STARTPTS[aout]"
        )
        inputs = ["-i", str(video_path.resolve())]
    else:
        filter_complex = (
            f"[0:v]{video_filter}[vout];[1:a]atrim=duration={video_duration:.6f},asetpts=PTS-STARTPTS[aout]"
        )
        inputs = ["-i", str(video_path.resolve()), "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo"]

    cmd = [
        "ffmpeg",
        "-y",
        *inputs,
        "-filter_complex",
        filter_complex,
        "-map",
        "[vout]",
        "-map",
        "[aout]",
        "-c:v",
        "libx264",
        "-preset",
        "medium",
        "-crf",
        "18",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-ar",
        "48000",
        "-ac",
        "2",
        str(output_path),
    ]
    run_ffmpeg(cmd, "ffmpeg 规范化片段失败")


def normalize_clips(
    video_paths: list[Path],
    temp_dir: Path,
    *,
    narration_audio_paths: list[Path | None] | None = None,
) -> list[Path]:
    """将全部片段统一成可安全拼接的中间片，对齐到第一个片段的尺寸/帧率。"""
    narrations = narration_audio_paths if narration_audio_paths is not None else [None] * len(video_paths)
    if len(narrations) != len(video_paths):
        raise ValueError("narration_audio_paths 长度必须与 video_paths 一致")

    first = probe_media(video_paths[0])
    target_width = int(first["width"])
    target_height = int(first["height"])
    target_fps = str(first["fps"])

    normalized_paths: list[Path] = []
    for index, (path, narration) in enumerate(zip(video_paths, narrations, strict=True)):
        normalized_path = temp_dir / f"normalized_{index:03d}.mp4"
        normalize_clip(
            path,
            normalized_path,
            target_width=target_width,
            target_height=target_height,
            target_fps=target_fps,
            narration_audio_path=narration,
        )
        normalized_paths.append(normalized_path)
    return normalized_paths


def concatenate_final(video_paths: list[Path], output_path: Path) -> None:
    """对统一规格的中间片做最终拼接，并确保音视频轨都从 0 开始。"""
    if not video_paths:
        raise ValueError("没有可用的视频片段")

    if len(video_paths) == 1:
        run_ffmpeg(
            [
                "ffmpeg",
                "-y",
                "-i",
                str(video_paths[0].resolve()),
                "-c",
                "copy",
                "-movflags",
                "+faststart",
                str(output_path),
            ],
            "ffmpeg 单段最终输出失败",
        )
        return

    inputs: list[str] = []
    filter_inputs: list[str] = []
    for index, path in enumerate(video_paths):
        inputs.extend(["-i", str(path.resolve())])
        filter_inputs.append(f"[{index}:v][{index}:a]")

    filter_complex = "".join(filter_inputs) + f"concat=n={len(video_paths)}:v=1:a=1[vout][aout]"
    run_ffmpeg(
        [
            "ffmpeg",
            "-y",
            *inputs,
            "-filter_complex",
            filter_complex,
            "-map",
            "[vout]",
            "-map",
            "[aout]",
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-crf",
            "18",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-movflags",
            "+faststart",
            str(output_path),
        ],
        "ffmpeg 拼接失败",
    )


def concatenate_simple(
    video_paths: list[Path],
    output_path: Path,
    *,
    narration_audio_paths: list[Path | None] | None = None,
) -> None:
    """无转场拼接：先规范化为统一中间片，再做最终拼接。"""
    with tempfile.TemporaryDirectory(prefix="reference-video-compose-") as temp_dir:
        normalized_paths = normalize_clips(video_paths, Path(temp_dir), narration_audio_paths=narration_audio_paths)
        concatenate_final(normalized_paths, output_path)


_XFADE_TYPE_MAP: dict[str, str] = {
    "fade": "fade",
    "dissolve": "dissolve",
}


def _build_xfade_filter_complex(
    durations: list[float],
    transitions: list[str],
    transition_duration: float,
) -> str | None:
    """按 cut 边界把片段切成 group，组内 xfade + acrossfade，组间 concat 串联。

    - 单段或全 cut 序列：返回 None，由调用方走 concatenate_final 的纯 concat 路径
    - 短片段（duration <= transition_duration）所触边界自动降级为 cut，避免 xfade
      offset 为负
    """
    n = len(durations)
    if n < 2:
        return None

    boundary_xfade: list[str | None] = []
    for i in range(n - 1):
        transition = transitions[i] if i < len(transitions) else "cut"
        if transition == "cut":
            boundary_xfade.append(None)
            continue
        xfade = _XFADE_TYPE_MAP.get(transition, "fade")
        if durations[i] <= transition_duration or durations[i + 1] <= transition_duration:
            boundary_xfade.append(None)
            continue
        boundary_xfade.append(xfade)

    for i in range(1, n - 1):
        if (
            boundary_xfade[i - 1] is not None
            and boundary_xfade[i] is not None
            and durations[i] < 2 * transition_duration
        ):
            boundary_xfade[i - 1] = None

    if all(b is None for b in boundary_xfade):
        return None

    groups: list[list[int]] = []
    current: list[int] = [0]
    for i, b in enumerate(boundary_xfade):
        if b is None:
            groups.append(current)
            current = [i + 1]
        else:
            current.append(i + 1)
    groups.append(current)

    filter_parts: list[str] = []
    group_outputs: list[tuple[str, str]] = []

    for gi, group in enumerate(groups):
        if len(group) == 1:
            idx = group[0]
            group_outputs.append((f"[{idx}:v]", f"[{idx}:a]"))
            continue

        group_durations = [durations[j] for j in group]

        prev_v = f"[{group[0]}:v]"
        for k in range(1, len(group)):
            xfade_type = boundary_xfade[group[k] - 1]
            assert xfade_type is not None
            offset = sum(group_durations[:k]) - k * transition_duration
            out_v = f"[g{gi}v]" if k == len(group) - 1 else f"[g{gi}v{k}]"
            filter_parts.append(
                f"{prev_v}[{group[k]}:v]xfade=transition={xfade_type}:"
                f"duration={transition_duration}:offset={offset:.3f}{out_v}"
            )
            prev_v = out_v

        prev_a = f"[{group[0]}:a]"
        for k in range(1, len(group)):
            out_a = f"[g{gi}a]" if k == len(group) - 1 else f"[g{gi}a{k}]"
            filter_parts.append(f"{prev_a}[{group[k]}:a]acrossfade=d={transition_duration}:c1=tri:c2=tri{out_a}")
            prev_a = out_a

        group_outputs.append((f"[g{gi}v]", f"[g{gi}a]"))

    if len(group_outputs) == 1:
        v_label, a_label = group_outputs[0]
        filter_parts.append(f"{v_label}null[vout]")
        filter_parts.append(f"{a_label}anull[aout]")
    else:
        concat_inputs = "".join(f"{v}{a}" for v, a in group_outputs)
        filter_parts.append(f"{concat_inputs}concat=n={len(group_outputs)}:v=1:a=1[vout][aout]")

    return ";".join(filter_parts)


def concatenate_with_transitions(
    video_paths: list[Path],
    transitions: list[str],
    output_path: Path,
    transition_duration: float = 0.5,
    *,
    narration_audio_paths: list[Path | None] | None = None,
) -> None:
    """用 xfade 滤镜实现片段间转场，cut 边界用 concat 串联以避免滤镜链断裂。"""
    with tempfile.TemporaryDirectory(prefix="reference-video-compose-") as temp_dir:
        normalized_paths = normalize_clips(video_paths, Path(temp_dir), narration_audio_paths=narration_audio_paths)
        if len(normalized_paths) < 2:
            concatenate_final(normalized_paths, output_path)
            return

        durations = [float(probe_media(p)["duration"]) for p in normalized_paths]
        filter_complex = _build_xfade_filter_complex(durations, transitions, transition_duration)

        if filter_complex is None:
            concatenate_final(normalized_paths, output_path)
            return

        inputs: list[str] = []
        for path in normalized_paths:
            inputs.extend(["-i", str(path.resolve())])

        cmd = [
            "ffmpeg",
            "-y",
            *inputs,
            "-filter_complex",
            filter_complex,
            "-map",
            "[vout]",
            "-map",
            "[aout]",
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-crf",
            "18",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-movflags",
            "+faststart",
            str(output_path),
        ]

        result = run_capture(cmd)
        if result.returncode != 0:
            # 转场滤镜失败时降级为纯拼接，而不是让整个"一键成片"失败——转场是锦上添花，
            # 拼接顺序正确才是这个功能的核心承诺。
            concatenate_final(normalized_paths, output_path)


def compose_episode(
    video_paths: list[Path],
    transitions: list[str],
    output_path: Path,
    *,
    narration_audio_paths: list[Path | None] | None = None,
) -> None:
    """按顺序把一集参考生视频的所有 unit 成片 + 各自旁白拼接成一条 mp4。

    `transitions` 全是 `cut` 时走纯拼接；否则走 xfade 转场路径（内部按每个边界的
    片段时长自动降级过短的转场为 cut）。
    """
    if not video_paths:
        raise ValueError("没有可用的视频片段")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if any(t != "cut" for t in transitions):
        concatenate_with_transitions(video_paths, transitions, output_path, narration_audio_paths=narration_audio_paths)
    else:
        concatenate_simple(video_paths, output_path, narration_audio_paths=narration_audio_paths)
