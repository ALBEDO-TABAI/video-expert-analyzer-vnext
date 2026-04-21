#!/usr/bin/env python3
"""
Video Expert Analyzer Pipeline - Enhanced Version
支持：配置目录选择、精选片段子文件夹、详细分析报告
"""

import os
import sys
import json
import argparse
import subprocess
import tempfile
import re
import shutil
import platform
import time
from dataclasses import dataclass
from urllib.parse import unquote
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from scenedetect import AdaptiveDetector, ContentDetector, open_video
from scenedetect.scene_manager import SceneManager

try:
    import download_douyin as DouyinDownloader
except ImportError:
    # 如果直接运行脚本，添加当前目录到路径
    sys.path.insert(0, str(Path(__file__).parent))
    import download_douyin as DouyinDownloader

try:
    from detailed_report_builder import generate_detailed_analysis_outputs
except ImportError:
    sys.path.insert(0, str(Path(__file__).parent))
    from detailed_report_builder import generate_detailed_analysis_outputs

try:
    from motion_analysis import (
        build_frame_sample_paths,
        extract_scene_sample_frames,
        ffmpeg_hwaccel_args,
        probe_duration_seconds,
    )
except ImportError:
    sys.path.insert(0, str(Path(__file__).parent))
    from motion_analysis import (
        build_frame_sample_paths,
        extract_scene_sample_frames,
        ffmpeg_hwaccel_args,
        probe_duration_seconds,
    )

try:
    from storyboard_generator import scene_has_complete_analysis
except ImportError:
    sys.path.insert(0, str(Path(__file__).parent))
    from storyboard_generator import scene_has_complete_analysis

try:
    from run_state import mark_stage
except ImportError:
    sys.path.insert(0, str(Path(__file__).parent))
    from run_state import mark_stage

try:
    from logger import get_logger
except ImportError:
    sys.path.insert(0, str(Path(__file__).parent))
    from logger import get_logger

log = get_logger("pipeline")


# 配置文件路径
CONFIG_DIR = Path.home() / ".config" / "video-expert-analyzer-vnext"
CONFIG_FILE = CONFIG_DIR / "config.json"
LEGACY_AUTO_SCORING_MAX_WORKERS = 10
DEFAULT_AUTO_SCORING = {
    "models_json_path": "",
    "preferred_model": "kcode/K2.6-code-preview",
    "fallback_models": [
        "zai/GLM-5V-Turbo",
        "novacode-openai/gpt-5.4",
    ],
    "max_workers": 4,
}
DEFAULT_CONFIG = {
    "output_base_dir": str(Path.home() / "Downloads" / "video-analysis"),
    "first_run": True,
    "default_scene_threshold": 27.0,
    "auto_scoring": dict(DEFAULT_AUTO_SCORING),
}
DEFAULT_SCENE_MIN_DURATION = 0.5
SCENE_CLUSTER_MIN_SECONDS = 0.12
SCENE_CLUSTER_RATIO = 0.35
SCENE_VIDEO_CODEC = "libx264"
SCENE_VIDEO_CODEC_BY_PLATFORM = {
    "Windows": "h264_nvenc",
    "Darwin": "h264_videotoolbox",
}
SCENE_AUDIO_CODEC = "aac"
SCENE_DETECTION_THREADING_MODE = "AUTO"
SCENE_DETECTION_BACKEND_ORDER_BY_PLATFORM = {
    "Darwin": ("opencv", "pyav"),
    "Windows": ("pyav", "opencv"),
    "Linux": ("pyav", "opencv"),
}
SCENE_DETECTION_BACKEND_OVERRIDE_ENV = "VEXA_SCENE_BACKENDS"
LOCAL_VIDEO_EXTENSIONS = {
    ".mp4",
    ".mov",
    ".mkv",
    ".avi",
    ".webm",
    ".m4v",
}
URL_SCHEME_PATTERN = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*://")
_FFMPEG_ENCODER_CACHE: Optional[set[str]] = None
_UNAVAILABLE_SCENE_VIDEO_CODECS: set[str] = set()


@dataclass
class SceneSegment:
    start_time: float
    end_time: float
    start_frame: int
    end_frame: int


@dataclass
class SceneDetectionPassResult:
    segments: list[SceneSegment]
    backend: str
    elapsed_seconds: float


def _is_url_source(value: str) -> bool:
    return bool(URL_SCHEME_PATTERN.match(str(value or "").strip()))


def _is_local_video_source(value: str) -> bool:
    try:
        path = Path(value).expanduser()
    except (TypeError, ValueError):
        return False
    return path.exists() and path.is_file() and path.suffix.lower() in LOCAL_VIDEO_EXTENSIONS


def _resolve_local_video_path(value: str) -> Path:
    return Path(value).expanduser().resolve()


def _build_local_video_info(video_path: Path) -> Dict:
    title = sanitize_filename(video_path.stem, max_length=100) or video_path.stem or "local_video"
    return {
        "success": True,
        "title": title,
        "uploader": "",
        "channel": "",
        "duration": "",
        "view_count": "",
        "platform": "local",
    }


def _derive_local_video_id(video_path: Path) -> str:
    import hashlib

    stable_name = sanitize_filename(video_path.stem, max_length=80)
    if stable_name:
        return stable_name
    digest = hashlib.md5(str(video_path).encode("utf-8")).hexdigest()[:12]
    return f"local_{digest}"


def _parse_ffmpeg_encoder_names(raw_output: str) -> set[str]:
    encoders: set[str] = set()
    for line in (raw_output or "").splitlines():
        match = re.match(r"^\s*[A-Za-z\.]{6}\s+(\S+)", line)
        if match:
            encoders.add(match.group(1))
    return encoders


def _get_ffmpeg_encoder_names() -> set[str]:
    global _FFMPEG_ENCODER_CACHE
    if _FFMPEG_ENCODER_CACHE is not None:
        return set(_FFMPEG_ENCODER_CACHE)

    ffmpeg_binary = shutil.which("ffmpeg") or "ffmpeg"
    try:
        result = subprocess.run(
            [ffmpeg_binary, "-hide_banner", "-encoders"],
            capture_output=True,
            text=True,
            check=True,
        )
    except FileNotFoundError:
        print(
            "⚠️ 未找到 ffmpeg 可执行文件，硬件编码器探测跳过；"
            "请安装 ffmpeg（macOS: `brew install ffmpeg`；Windows: 从 https://www.gyan.dev/ffmpeg/builds/ 下载并加入 PATH）。"
        )
        _FFMPEG_ENCODER_CACHE = set()
    except subprocess.CalledProcessError as exc:
        stderr = (exc.stderr or exc.stdout or "").strip()
        print(f"⚠️ ffmpeg -encoders 执行失败（已安装但报错），将退回 CPU 编码：{stderr or exc}")
        _FFMPEG_ENCODER_CACHE = set()
    except OSError as exc:
        print(f"⚠️ 调用 ffmpeg 时发生 OS 错误：{exc}；硬件编码器探测跳过。")
        _FFMPEG_ENCODER_CACHE = set()
    else:
        _FFMPEG_ENCODER_CACHE = _parse_ffmpeg_encoder_names(
            f"{result.stdout or ''}\n{result.stderr or ''}"
        )
    return set(_FFMPEG_ENCODER_CACHE)


def scene_detection_backend_order(system_name: Optional[str] = None) -> tuple[str, ...]:
    override = str(os.environ.get(SCENE_DETECTION_BACKEND_OVERRIDE_ENV, "") or "").strip()
    if override:
        ordered = []
        for item in override.split(","):
            backend = item.strip().lower()
            if backend in {"pyav", "opencv"} and backend not in ordered:
                ordered.append(backend)
        if ordered:
            return tuple(ordered)

    system_name = system_name or platform.system()
    return SCENE_DETECTION_BACKEND_ORDER_BY_PLATFORM.get(system_name, ("pyav", "opencv"))


def _select_scene_video_codec(system_name: Optional[str] = None) -> tuple[str, str]:
    system_name = system_name or platform.system()
    preferred_codec = SCENE_VIDEO_CODEC_BY_PLATFORM.get(system_name)
    encoders = _get_ffmpeg_encoder_names()

    if preferred_codec and preferred_codec not in _UNAVAILABLE_SCENE_VIDEO_CODECS and preferred_codec in encoders:
        return preferred_codec, f"{system_name} hardware encoder"
    if preferred_codec and preferred_codec in _UNAVAILABLE_SCENE_VIDEO_CODECS:
        return SCENE_VIDEO_CODEC, f"{preferred_codec} unavailable at runtime, fallback to CPU"
    if preferred_codec:
        return SCENE_VIDEO_CODEC, f"{preferred_codec} not exposed by ffmpeg, fallback to CPU"
    return SCENE_VIDEO_CODEC, f"{system_name or 'Unknown'} has no preferred hardware encoder, fallback to CPU"


def _scene_codec_args(video_codec: str) -> list[str]:
    if video_codec == "h264_nvenc":
        return ["-c:v", video_codec, "-preset", "p4"]
    return ["-c:v", video_codec]


def _timecode_to_seconds(timecode) -> float:
    if hasattr(timecode, "get_seconds"):
        return float(timecode.get_seconds())
    return float(timecode)


def _parse_ffprobe_fps(raw_fps: str) -> float:
    value = str(raw_fps or "").strip()
    if not value:
        return 30.0
    if "/" in value:
        numerator, denominator = value.split("/", 1)
        try:
            numerator_value = float(numerator)
            denominator_value = float(denominator)
            if denominator_value:
                return numerator_value / denominator_value
        except ValueError:
            return 30.0
    try:
        return float(value)
    except ValueError:
        return 30.0


def _get_video_metadata(video_path: Path) -> tuple[float, float, int, bool]:
    ffprobe_binary = shutil.which("ffprobe") or "ffprobe"
    cmd = [
        ffprobe_binary,
        "-v",
        "error",
        "-show_entries",
        "format=duration:stream=codec_type,avg_frame_rate,nb_frames",
        "-of",
        "json",
        str(video_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    payload = json.loads(result.stdout or "{}")
    streams = payload.get("streams", [])
    format_info = payload.get("format", {})

    duration = float(format_info.get("duration") or 0.0)
    video_stream = next((stream for stream in streams if stream.get("codec_type") == "video"), {})
    fps_value = max(1.0, _parse_ffprobe_fps(video_stream.get("avg_frame_rate", "30/1")))

    try:
        total_frames = int(video_stream.get("nb_frames") or 0)
    except (TypeError, ValueError):
        total_frames = 0
    if total_frames <= 0:
        total_frames = max(1, int(round(duration * fps_value)))

    has_audio = any(stream.get("codec_type") == "audio" for stream in streams)
    return duration, fps_value, total_frames, has_audio


def _scene_segments_to_frame_boundaries(scene_segments: list[SceneSegment], total_frames: int) -> list[int]:
    boundaries = [0]
    for segment in scene_segments[1:]:
        boundaries.append(segment.start_frame)
    boundaries.append(total_frames)
    return boundaries


def _cluster_boundaries(boundaries: list[int], tolerance: int) -> list[int]:
    if not boundaries:
        return []

    boundaries = sorted(boundaries)
    clustered = [boundaries[0]]
    for boundary in boundaries[1:]:
        if boundary - clustered[-1] <= tolerance:
            clustered[-1] = int(round((clustered[-1] + boundary) / 2))
        else:
            clustered.append(boundary)
    return clustered


def _frame_boundaries_to_scene_segments(boundaries: list[int], fps_value: float) -> list[SceneSegment]:
    return [
        SceneSegment(
            start_time=boundaries[index] / fps_value,
            end_time=boundaries[index + 1] / fps_value,
            start_frame=boundaries[index],
            end_frame=boundaries[index + 1],
        )
        for index in range(len(boundaries) - 1)
        if boundaries[index + 1] > boundaries[index]
    ]


def _scene_list_to_segments(scene_list) -> list[SceneSegment]:
    return [
        SceneSegment(
            start_time=_timecode_to_seconds(start),
            end_time=_timecode_to_seconds(end),
            start_frame=int(start.get_frames()),
            end_frame=int(end.get_frames()),
        )
        for start, end in scene_list
    ]


def _detect_scene_pass(video_path: Path, detector_factory) -> SceneDetectionPassResult:
    backend_attempts: list[tuple[str, dict]] = []
    for backend_name in scene_detection_backend_order():
        backend_kwargs = {"threading_mode": SCENE_DETECTION_THREADING_MODE} if backend_name == "pyav" else {}
        backend_attempts.append((backend_name, backend_kwargs))

    errors: list[str] = []
    for backend_name, backend_kwargs in backend_attempts:
        started_at = time.perf_counter()
        video_stream = None
        try:
            video_stream = open_video(str(video_path), backend=backend_name, **backend_kwargs)
            scene_manager = SceneManager()
            scene_manager.add_detector(detector_factory())
            scene_manager.detect_scenes(video=video_stream, show_progress=False)
            actual_backend = getattr(video_stream, "BACKEND_NAME", backend_name)
            return SceneDetectionPassResult(
                segments=_scene_list_to_segments(scene_manager.get_scene_list()),
                backend=actual_backend,
                elapsed_seconds=time.perf_counter() - started_at,
            )
        except Exception as exc:
            errors.append(f"{backend_name}: {exc}")
        finally:
            if video_stream is not None:
                del video_stream

    raise RuntimeError(
        "scene detection backend failed to open video: " + " | ".join(errors)
    )


def _detect_scene_ranges_with_details(
    video_path: Path,
    threshold: float,
    min_scene_duration: float = DEFAULT_SCENE_MIN_DURATION,
) -> tuple[list[SceneSegment], bool, Dict]:
    duration, fps_value, total_frames, has_audio = _get_video_metadata(video_path)
    min_scene_len_frames = max(1, int(round(fps_value * min_scene_duration)))

    content_result = _detect_scene_pass(
        video_path,
        lambda: ContentDetector(
            threshold=threshold,
            min_scene_len=min_scene_len_frames,
        ),
    )
    adaptive_result = _detect_scene_pass(
        video_path,
        lambda: AdaptiveDetector(
            adaptive_threshold=max(1.0, threshold / 6.0),
            min_content_val=max(8.0, threshold * 0.6),
            min_scene_len=min_scene_len_frames,
        ),
    )

    content_segments = content_result.segments
    adaptive_segments = adaptive_result.segments

    if not content_segments and not adaptive_segments:
        merged_segments = [
            SceneSegment(
                start_time=0.0,
                end_time=duration,
                start_frame=0,
                end_frame=total_frames,
            )
        ]
    else:
        tolerance_frames = max(
            1,
            int(round(fps_value * max(SCENE_CLUSTER_MIN_SECONDS, min_scene_duration * SCENE_CLUSTER_RATIO))),
        )
        boundaries = _scene_segments_to_frame_boundaries(content_segments, total_frames)
        boundaries.extend(_scene_segments_to_frame_boundaries(adaptive_segments, total_frames))
        boundaries = _cluster_boundaries(boundaries, tolerance=tolerance_frames)

        if boundaries[0] != 0:
            boundaries.insert(0, 0)
        if boundaries[-1] != total_frames:
            boundaries.append(total_frames)

        merged_segments = _frame_boundaries_to_scene_segments(boundaries, fps_value)

    details = {
        "duration_seconds": duration,
        "fps": fps_value,
        "total_frames": total_frames,
        "has_audio": has_audio,
        "passes": [
            {
                "name": "content",
                "backend": content_result.backend,
                "elapsed_seconds": content_result.elapsed_seconds,
                "raw_scene_count": len(content_segments),
            },
            {
                "name": "adaptive",
                "backend": adaptive_result.backend,
                "elapsed_seconds": adaptive_result.elapsed_seconds,
                "raw_scene_count": len(adaptive_segments),
            },
        ],
        "merged_scene_count": len(merged_segments),
    }
    return merged_segments, has_audio, details


def _detect_scene_ranges(
    video_path: Path,
    threshold: float,
    min_scene_duration: float = DEFAULT_SCENE_MIN_DURATION,
) -> tuple[list[SceneSegment], bool]:
    scene_segments, has_audio, _details = _detect_scene_ranges_with_details(
        video_path,
        threshold=threshold,
        min_scene_duration=min_scene_duration,
    )
    return scene_segments, has_audio


def _run_ffmpeg_trim(
    video_path: Path,
    start: float,
    end: float,
    output_path: Path,
    start_frame: int | None = None,
    end_frame: int | None = None,
    has_audio: bool = True,
):
    ffmpeg_binary = shutil.which("ffmpeg") or "ffmpeg"
    selected_codec, selected_reason = _select_scene_video_codec()

    def build_command(video_codec: str) -> list[str]:
        if start_frame is not None and end_frame is not None:
            cmd = [
                ffmpeg_binary,
                "-y",
                "-i",
                str(video_path),
                "-vf",
                f"trim=start_frame={start_frame}:end_frame={end_frame},setpts=PTS-STARTPTS",
            ]
            if has_audio:
                cmd.extend(
                    [
                        "-af",
                        f"atrim=start={start:.6f}:end={end:.6f},asetpts=PTS-STARTPTS",
                        "-c:a",
                        SCENE_AUDIO_CODEC,
                    ]
                )
            else:
                cmd.append("-an")
            cmd.extend(_scene_codec_args(video_codec))
            cmd.append(str(output_path))
            return cmd

        duration = max(0.01, end - start)
        cmd = [
            ffmpeg_binary,
            "-y",
            "-ss",
            f"{start:.3f}",
            "-i",
            str(video_path),
            "-t",
            f"{duration:.3f}",
        ]
        cmd.extend(_scene_codec_args(video_codec))
        if has_audio:
            cmd.extend(["-c:a", SCENE_AUDIO_CODEC])
        else:
            cmd.append("-an")
        cmd.append(str(output_path))
        return cmd

    attempts: list[tuple[str, str]] = [(selected_codec, selected_reason)]
    if selected_codec != SCENE_VIDEO_CODEC:
        attempts.append((SCENE_VIDEO_CODEC, f"{selected_codec} failed at runtime, fallback to CPU"))

    last_error = ""
    for attempt_index, (video_codec, codec_reason) in enumerate(attempts):
        try:
            result = subprocess.run(build_command(video_codec), capture_output=True, text=True)
        except FileNotFoundError as exc:
            raise RuntimeError(
                f"未找到 ffmpeg 可执行文件（{ffmpeg_binary}）；"
                "请安装 ffmpeg 并确保它在 PATH 中（macOS: `brew install ffmpeg`；"
                "Windows: 从 https://www.gyan.dev/ffmpeg/builds/ 下载并加入 PATH）。"
            ) from exc
        if result.returncode == 0:
            return {
                "video_codec": video_codec,
                "codec_reason": codec_reason,
                "fallback_used": attempt_index > 0,
            }

        last_error = (result.stderr or result.stdout or "").strip() or "ffmpeg trim failed"
        if output_path.exists():
            output_path.unlink()
        if video_codec != SCENE_VIDEO_CODEC:
            _UNAVAILABLE_SCENE_VIDEO_CODECS.add(video_codec)

    raise RuntimeError(last_error)


def _normalize_config(raw_config: object) -> tuple[Dict, bool]:
    config = dict(DEFAULT_CONFIG)
    updated = False

    if not isinstance(raw_config, dict):
        return config, True

    output_base_dir = str(raw_config.get("output_base_dir", "") or "").strip()
    if output_base_dir:
        config["output_base_dir"] = output_base_dir
    else:
        updated = True

    config["first_run"] = bool(raw_config.get("first_run", DEFAULT_CONFIG["first_run"]))

    try:
        config["default_scene_threshold"] = float(
            raw_config.get("default_scene_threshold", DEFAULT_CONFIG["default_scene_threshold"])
        )
    except (TypeError, ValueError):
        config["default_scene_threshold"] = DEFAULT_CONFIG["default_scene_threshold"]
        updated = True

    raw_auto_scoring = raw_config.get("auto_scoring")
    auto_scoring = dict(DEFAULT_AUTO_SCORING)
    if isinstance(raw_auto_scoring, dict):
        models_json_path = str(raw_auto_scoring.get("models_json_path", "") or "").strip()
        auto_scoring["models_json_path"] = models_json_path

        preferred_model = str(raw_auto_scoring.get("preferred_model", "") or "").strip()
        if preferred_model:
            auto_scoring["preferred_model"] = preferred_model
        else:
            updated = True

        fallback_models = raw_auto_scoring.get("fallback_models", DEFAULT_AUTO_SCORING["fallback_models"])
        if isinstance(fallback_models, list):
            normalized_fallbacks = [str(item).strip() for item in fallback_models if str(item).strip()]
        else:
            normalized_fallbacks = []
        if normalized_fallbacks:
            auto_scoring["fallback_models"] = normalized_fallbacks
        else:
            updated = True

        try:
            max_workers = max(1, int(raw_auto_scoring.get("max_workers", DEFAULT_AUTO_SCORING["max_workers"])))
        except (TypeError, ValueError):
            max_workers = DEFAULT_AUTO_SCORING["max_workers"]
            updated = True
        else:
            # Earlier releases persisted 10 as the implicit default. Migrate that
            # legacy baseline down to the safer default unless the user chooses
            # another explicit value.
            if max_workers == LEGACY_AUTO_SCORING_MAX_WORKERS:
                max_workers = DEFAULT_AUTO_SCORING["max_workers"]
                updated = True
        auto_scoring["max_workers"] = max_workers

        for key, value in raw_auto_scoring.items():
            if key not in auto_scoring:
                auto_scoring[key] = value
    else:
        updated = True
    config["auto_scoring"] = auto_scoring

    for key, value in raw_config.items():
        if key not in config:
            config[key] = value

    if any(key not in raw_config for key in DEFAULT_CONFIG):
        updated = True
    return config, updated


def load_config() -> Dict:
    """加载用户配置，如果不存在则创建默认配置"""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                raw_config = json.load(f)
        except (OSError, json.JSONDecodeError):
            raw_config = None

        config, updated = _normalize_config(raw_config)
        if updated:
            save_config(config)
        return config

    save_config(DEFAULT_CONFIG)
    return dict(DEFAULT_CONFIG)


def save_config(config: Dict):
    """保存用户配置"""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(config, f, indent=2, ensure_ascii=False)


def load_analysis_state(state_path: Path) -> Dict:
    if state_path.exists():
        return json.loads(state_path.read_text(encoding="utf-8"))
    return {"status": "initialized", "steps": {}}


def save_analysis_state(state_path: Path, state: Dict):
    state_path.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")


def build_yt_dlp_command(*args: str) -> List[str]:
    """
    构造 yt-dlp 命令。
    Windows 上经常出现 yt-dlp 已通过 pip 安装、但命令未进入 PATH 的情况，
    这时自动回退到当前 Python 解释器里的 yt_dlp 模块。
    """
    runtime_args: List[str] = []
    if shutil.which("node"):
        runtime_args = ["--js-runtimes", "node"]

    if shutil.which("yt-dlp"):
        return ["yt-dlp", *runtime_args, *args]
    return [sys.executable, "-m", "yt_dlp", *runtime_args, *args]


def get_video_info(url: str) -> Dict:
    """
    使用 yt-dlp 获取视频信息（标题、作者等）
    抖音链接使用专用方法获取
    """
    # 抖音链接使用专用方法
    if DouyinDownloader.is_douyin_url(url):
        return get_douyin_video_info(url)
    
    # 其他平台使用yt-dlp
    try:
        cmd = build_yt_dlp_command(
            "--print", "%(title)s",
            "--print", "%(uploader)s",
            "--print", "%(channel)s",
            "--print", "%(duration)s",
            "--print", "%(view_count)s",
            "--no-download",
            url
        )
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        
        if result.returncode == 0:
            lines = result.stdout.strip().split('\n')
            return {
                "title": lines[0] if len(lines) > 0 else "",
                "uploader": lines[1] if len(lines) > 1 else "",
                "channel": lines[2] if len(lines) > 2 else "",
                "duration": lines[3] if len(lines) > 3 else "",
                "view_count": lines[4] if len(lines) > 4 else "",
                "success": True
            }
    except Exception as e:
        print(f"   ⚠️  获取视频信息失败: {e}")
    
    return {"success": False, "title": "", "uploader": ""}


def get_douyin_video_info(url: str) -> Dict:
    """
    获取抖音视频信息
    """
    try:
        # 获取重定向后的URL
        full_url, user_agent, html = DouyinDownloader.get_redirect_url(url)
        if not full_url or not html:
            return {"success": False, "title": "", "uploader": ""}

        # 提取RENDER_DATA
        render_data = DouyinDownloader.extract_render_data(html)
        if not render_data:
            return {"success": False, "title": "", "uploader": ""}

        # download_douyin.py 已经返回 Python dict；兼容旧版字符串输出。
        if isinstance(render_data, dict):
            data = render_data
        else:
            decoded = unquote(render_data) if '%' in render_data else render_data
            data = json.loads(decoded)
        
        # 尝试提取标题和作者
        title = ""
        uploader = ""
        
        # 常见路径
        possible_title_paths = [
            ['loaderData', 'video_(id)/page', 'videoInfoRes', 'item_list', 0, 'desc'],
            ['loaderData', 'video_(id)/page', 'aweme_detail', 'desc'],
            ['app', 'videoDetail', 'desc'],
            ['app', 'videoInfoRes', 'item_list', 0, 'desc'],
        ]
        
        possible_author_paths = [
            ['loaderData', 'video_(id)/page', 'videoInfoRes', 'item_list', 0, 'author', 'nickname'],
            ['loaderData', 'video_(id)/page', 'aweme_detail', 'author', 'nickname'],
            ['app', 'videoDetail', 'author', 'nickname'],
            ['app', 'videoInfoRes', 'item_list', 0, 'author', 'nickname'],
        ]
        
        def get_nested(obj, path):
            current = obj
            for key in path:
                if isinstance(current, dict) and key in current:
                    current = current[key]
                elif isinstance(current, list) and isinstance(key, int) and key < len(current):
                    current = current[key]
                else:
                    return None
            return current
        
        for path in possible_title_paths:
            title = get_nested(data, path)
            if title:
                break
        
        for path in possible_author_paths:
            uploader = get_nested(data, path)
            if uploader:
                break
        
        # 如果找不到标题，使用URL作为标题
        if not title:
            title = f"抖音视频_{url.split('/')[-1][:20]}"
        
        return {
            "success": True,
            "title": title or "抖音视频",
            "uploader": uploader or "未知作者",
            "channel": uploader or "",
            "duration": "",
            "view_count": "",
            "platform": "douyin"
        }
        
    except Exception as e:
        print(f"   ⚠️  获取抖音视频信息失败: {e}")
        return {"success": False, "title": "", "uploader": ""}


def sanitize_filename(name: str, max_length: int = 50) -> str:
    """
    清理文件名，移除非法字符并限制长度
    """
    # 移除非法字符
    name = re.sub(r'[\\/*?:"<>|]', '', name)
    # 移除多余空格
    name = re.sub(r'\s+', ' ', name).strip()
    
    # 如果超长，截取前max_length个字符
    if len(name) > max_length:
        name = name[:max_length].strip()
    
    return name


def generate_folder_name(video_info: Dict, video_id: str, max_length: int = 60) -> str:
    """
    生成视频文件夹名称
    格式: [作者] - [标题] 或 [标题]
    如果超长则提取关键字
    """
    title = video_info.get("title", "")
    uploader = video_info.get("uploader", "") or video_info.get("channel", "")
    
    if not title:
        return video_id
    
    # 清理标题
    title = sanitize_filename(title, max_length=100)
    uploader = sanitize_filename(uploader, max_length=30)
    
    # 生成文件夹名
    if uploader:
        folder_name = f"[{uploader}] {title}"
    else:
        folder_name = title
    
    # 如果超长，使用作者+简写标题
    if len(folder_name) > max_length:
        # 提取标题前30个字符
        short_title = title[:30].strip()
        if uploader:
            folder_name = f"[{uploader}] {short_title}"
        else:
            folder_name = short_title
    
    # 最终清理
    folder_name = folder_name.strip()
    if not folder_name:
        folder_name = video_id
    
    return folder_name


def setup_output_directory() -> str:
    """交互式设置输出目录"""
    config = load_config()
    
    print("=" * 60)
    print("📁 输出目录配置")
    print("=" * 60)
    
    if config.get("first_run", True):
        print("\n🎉 欢迎使用 Video Expert Analyzer!")
        print("请设置视频分析和输出的默认目录\n")
    else:
        print(f"\n当前默认输出目录: {config['output_base_dir']}")
    
    print("\n选项:")
    print("  1. 使用当前目录")
    print("  2. 使用默认目录 (~/Downloads/video-analysis)")
    print("  3. 自定义目录")
    
    if not config.get("first_run", True):
        print("  4. 修改当前默认目录")
    
    try:
        choice = input("\n请选择 [1-4]: ").strip()
    except (EOFError, KeyboardInterrupt):
        return config['output_base_dir']
    
    if choice == "1":
        output_dir = os.getcwd()
    elif choice == "2":
        output_dir = str(Path.home() / "Downloads" / "video-analysis")
        config['output_base_dir'] = output_dir
        save_config(config)
    elif choice == "3":
        try:
            custom_dir = input("请输入自定义目录路径: ").strip()
            output_dir = custom_dir
            config['output_base_dir'] = output_dir
            config['first_run'] = False
            save_config(config)
        except (EOFError, KeyboardInterrupt):
            output_dir = config['output_base_dir']
    elif choice == "4" and not config.get("first_run", True):
        try:
            new_dir = input("请输入新的默认目录路径: ").strip()
            config['output_base_dir'] = new_dir
            save_config(config)
            output_dir = new_dir
        except (EOFError, KeyboardInterrupt):
            output_dir = config['output_base_dir']
    else:
        output_dir = config['output_base_dir']
    
    if config.get("first_run", True):
        config['first_run'] = False
        save_config(config)
    
    print(f"\n✅ 输出目录: {output_dir}")
    return output_dir


def get_output_directory() -> str:
    """获取当前配置的输出目录（非交互式）"""
    config = load_config()
    return config['output_base_dir']


class VideoAnalysisPipeline:
    """增强版视频分析管道"""

    def __init__(self, url: str, output_dir: str,
                 scene_threshold: float = 27.0,
                 extract_scenes: bool = True,
                 auto_select_best: bool = True,
                 best_threshold: float = 7.5,
                 openclaw_mode: bool = False):
        self.url = url
        self.output_dir = Path(output_dir).resolve()
        self.scene_threshold = scene_threshold
        self.extract_scenes = extract_scenes
        self.auto_select_best = auto_select_best
        self.best_threshold = best_threshold
        self.openclaw_mode = openclaw_mode

        self.output_dir.mkdir(parents=True, exist_ok=True)

        self.source_kind = "url"
        self.source_path: Path | None = None
        if _is_local_video_source(url):
            self.source_kind = "local"
            self.source_path = _resolve_local_video_path(url)
        elif not _is_url_source(url) and Path(url).expanduser().suffix.lower() in LOCAL_VIDEO_EXTENSIONS:
            raise FileNotFoundError(f"本地视频不存在: {Path(url).expanduser()}")

        print("\n📋 正在准备视频源...")
        if self.source_kind == "local":
            assert self.source_path is not None
            self.video_id = _derive_local_video_id(self.source_path)
            self.video_info = _build_local_video_info(self.source_path)
            print("   来源: 本地视频文件")
            print(f"   路径: {self.source_path}")
        else:
            self.video_id = self._extract_video_id(url)
            self.video_info = get_video_info(url)
            print("   来源: 网络视频链接")

        if self.video_info.get("success"):
            print(f"   标题: {self.video_info.get('title', 'N/A')[:60]}...")
            print(f"   作者: {self.video_info.get('uploader', 'N/A')}")

            # 生成以标题命名的文件夹名
            self.folder_name = generate_folder_name(self.video_info, self.video_id)
            print(f"   文件夹: {self.folder_name}")
        else:
            print("   ⚠️  无法获取视频信息，使用视频 ID 作为文件夹名")
            self.folder_name = self.video_id
            self.video_info = {"title": self.video_id, "uploader": ""}

        # 创建视频专属子目录（使用标题命名）
        self.video_output_dir = self.output_dir / self.folder_name
        self.video_output_dir.mkdir(parents=True, exist_ok=True)

        # Define output paths
        if self.source_kind == "local":
            assert self.source_path is not None
            self.video_path = self.source_path
        else:
            self.video_path = self.video_output_dir / f"{self.video_id}.mp4"
        self.audio_path = self.video_output_dir / f"{self.video_id}.m4a"
        self.srt_path = self.video_output_dir / f"{self.video_id}.srt"
        self.transcript_path = self.video_output_dir / f"{self.video_id}_transcript.txt"
        self.scenes_dir = self.video_output_dir / "scenes"
        self.best_shots_dir = self.scenes_dir / "best_shots"
        self.frames_dir = self.video_output_dir / "frames"
        self.scores_path = self.video_output_dir / "scene_scores.json"
        self.state_path = self.video_output_dir / "analysis_state.json"
        self.run_state_path = self.video_output_dir / "run_state.json"
        self.report_path = self.video_output_dir / f"{self.video_id}_analysis_report.md"
        self.detailed_report_path = self.video_output_dir / f"{self.video_id}_detailed_analysis.md"
        self.analysis_state = load_analysis_state(self.state_path)

        # Results tracking
        self.results = {
            "video_id": self.video_id,
            "video_title": self.video_info.get("title", ""),
            "video_uploader": self.video_info.get("uploader", ""),
            "folder_name": self.folder_name,
            "url": url,
            "source_kind": self.source_kind,
            "source_path": str(self.video_path),
            "timestamp": datetime.now().isoformat(),
            "status": "initialized",
            "steps_completed": [],
            "scene_analysis": [],
            "overall_assessment": {}
        }

    def _mark_step_complete(self, step_name: str, **extra):
        self.analysis_state.setdefault("steps", {})[step_name] = {
            "status": "completed",
            "updated_at": datetime.now().isoformat(),
            **extra,
        }
        save_analysis_state(self.state_path, self.analysis_state)

    def _mark_run_stage(self, stage: str, *, status: str, completed: bool = False, **extra):
        mark_stage(
            self.run_state_path,
            stage=stage,
            status=status,
            completed=completed,
            scores_path=str(self.scores_path),
            video_dir=str(self.video_output_dir),
            **extra,
        )

    def _extract_audio_from_video(self) -> bool:
        try:
            cmd = ["ffmpeg", "-i", str(self.video_path), "-vn", "-c:a", "copy", str(self.audio_path), "-y"]
            subprocess.run(cmd, check=True, capture_output=True)
            return self.audio_path.exists()
        except subprocess.CalledProcessError:
            return False

    def _step_prepare_next_batch(self, scene_info: Dict) -> Dict | None:
        print("\n📦 Step 10: Preparing first batch packet...")
        if not self.scores_path.exists():
            print("   ⚠️  scene_scores.json 不存在，跳过批次准备")
            return None

        try:
            from ai_analyzer import auto_score_scenes
        except ImportError:
            sys.path.insert(0, str(Path(__file__).parent))
            from ai_analyzer import auto_score_scenes

        data = auto_score_scenes(
            self.scores_path,
            self.video_output_dir,
            mode="score_batches",
            batch_size=0,
            payload_style="compact",
            openclaw_mode=self.openclaw_mode,
        )

        run_state = json.loads(self.run_state_path.read_text(encoding="utf-8")) if self.run_state_path.exists() else {}
        next_batch = run_state.get("next_batch")
        if next_batch:
            print(f"   ✅ 已准备下一批: {next_batch.get('batch_id', '')}")
        else:
            print("   ✅ 当前无需新批次，可以直接 finalize")

        self.results["next_batch"] = next_batch
        self.results["steps_completed"].append("prepare_next_batch")
        self._mark_step_complete("prepare_next_batch", next_batch=next_batch or {})
        return next_batch

    def _extract_video_id(self, url: str) -> str:
        """Extract video ID from URL"""
        if "bilibili.com" in url:
            if "/video/" in url:
                parts = url.split("/video/")[1].split("/")[0].split("?")[0]
                return parts
        if "youtube.com" in url or "youtu.be" in url:
            if "v=" in url:
                return url.split("v=")[1].split("&")[0]
            elif "youtu.be/" in url:
                return url.split("youtu.be/")[1].split("?")[0]
        if "douyin.com" in url or "iesdouyin.com" in url:
            # 抖音视频ID提取
            if "modal_id=" in url:
                return url.split("modal_id=")[1].split("&")[0]
            if "/video/" in url:
                return url.split("/video/")[1].split("/")[0].split("?")[0]
            # 短链接使用URL的hash作为ID
            import hashlib
            return f"douyin_{hashlib.md5(url.encode()).hexdigest()[:12]}"
        return f"video_{int(datetime.now().timestamp())}"

    def run(self) -> Dict:
        """Execute the complete pipeline"""
        print("=" * 60)
        print("🎬 VIDEO EXPERT ANALYZER PIPELINE")
        print("=" * 60)
        print(f"📺 视频标题: {self.video_info.get('title', 'N/A')[:50]}...")
        print(f"👤 视频作者: {self.video_info.get('uploader', 'N/A')}")
        print(f"🧭 Source Type: {self.source_kind}")
        if self.source_kind == "local":
            print(f"📂 Source Path: {self.video_path}")
        else:
            print(f"🔗 Video URL: {self.url}")
        print(f"📁 Output Dir: {self.video_output_dir}")
        print(f"🆔 Video ID: {self.video_id}")
        print("=" * 60)

        try:
            self._mark_run_stage("prepare", status="running", completed=False)
            self._step_download_video()
            self._step_download_audio()
            scene_info = self._step_scene_detection()
            transcript_info = self._step_transcription()
            self._step_extract_frames(scene_info)
            self._step_prepare_scoring(scene_info)
            transcript_info = self._step_refine_music_subtitles(transcript_info)
            self._step_ai_scene_analysis(scene_info)
            if self.auto_select_best:
                self._step_auto_select_best_shots(scene_info)
            self._step_generate_detailed_report(scene_info, transcript_info)
            next_batch = self._step_prepare_next_batch(scene_info)

            self.results["status"] = "materials_prepared"
            self._mark_step_complete("materials_prepared", scene_count=scene_info.get("scene_count", 0))
            print("\n" + "=" * 60)
            print("✅ 素材准备完成")
            print("=" * 60)
            print(f"\n📁 所有文件保存在: {self.video_output_dir}")
            print(f"🧾 评分模板: {self.scores_path}")
            print(f"📄 草稿报告: {self.detailed_report_path}")
            if next_batch:
                print(f"🧩 当前批次: {next_batch.get('batch_id', '')}")
                print(f"📄 批次简报: {next_batch.get('brief', '')}")
                print(f"📥 批次输入: {next_batch.get('input', '')}")
                print(f"📤 批次输出: {next_batch.get('output', '')}")
                print("🤖 下一步: 立即开始分析当前批次（当前 agent 直接看图分析，不需要等用户指令）")
            else:
                print("🤖 当前已无待处理批次，可直接 finalize")
            return self.results

        except Exception as e:
            self.results["status"] = "failed"
            self.results["error"] = str(e)
            self._mark_run_stage("prepare", status="blocked", completed=False, last_error=str(e))
            print(f"\n❌ PIPELINE FAILED: {e}")
            raise

    def _step_download_video(self):
        print("\n📥 Step 1: Preparing video source...")
        if self.source_kind == "local":
            file_size = self.video_path.stat().st_size / (1024 * 1024)
            print("   📁 本地文件已就绪，跳过下载")
            print(f"   ✅ Video ready: {self.video_path} ({file_size:.2f} MB)")
            self.results["video_path"] = str(self.video_path)
            self.results["video_size_mb"] = round(file_size, 2)
            self.results["steps_completed"].append("download_video")
            self._mark_step_complete(
                "download_video",
                video_path=str(self.video_path),
                source_kind=self.source_kind,
                reused_local_file=True,
            )
            return

        if self.video_path.exists():
            print(f"   ⚠️  Video already exists: {self.video_path}")
            self.results["video_path"] = str(self.video_path)
            self.results["steps_completed"].append("download_video")
            self._mark_step_complete("download_video", video_path=str(self.video_path), source_kind=self.source_kind)
            return

        # 检查是否为抖音链接，使用专用下载器
        if DouyinDownloader.is_douyin_url(self.url):
            print("   🔍 检测到抖音视频链接")
            success = DouyinDownloader.download_douyin_video(self.url, str(self.video_path))
            if not success:
                raise RuntimeError("抖音视频下载失败")
        else:
            # 使用yt-dlp下载其他平台视频
            cmd = build_yt_dlp_command(
                "-f", "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
                "-o", str(self.video_path),
                self.url,
            )
            try:
                subprocess.run(cmd, check=True, capture_output=True, text=True)
            except FileNotFoundError as exc:
                raise RuntimeError(
                    "未找到 yt-dlp 可执行文件，且 `python -m yt_dlp` 也不可用；"
                    "请运行 `pip install yt-dlp` 或确保 yt-dlp 在 PATH 中。"
                ) from exc
            except subprocess.CalledProcessError as exc:
                stderr = (exc.stderr or exc.stdout or "").strip()
                raise RuntimeError(f"yt-dlp 下载失败: {stderr or exc}") from exc
        
        if not self.video_path.exists():
            raise RuntimeError("Video download failed - file not found")
        file_size = self.video_path.stat().st_size / (1024 * 1024)
        print(f"   ✅ Video downloaded: {file_size:.2f} MB")
        self.results["video_path"] = str(self.video_path)
        self.results["video_size_mb"] = round(file_size, 2)
        self.results["steps_completed"].append("download_video")
        self._mark_step_complete("download_video", video_path=str(self.video_path), source_kind=self.source_kind)

    def _step_download_audio(self):
        print("\n🎵 Step 2: Preparing audio...")
        if self.audio_path.exists():
            print(f"   ⚠️  Audio already exists: {self.audio_path}")
            self.results["steps_completed"].append("download_audio")
            self.results["audio_path"] = str(self.audio_path)
            self._mark_step_complete("download_audio", audio_path=str(self.audio_path), source_kind=self.source_kind)
            return

        if self.source_kind == "local":
            print("   📁 本地视频，直接从视频提取音频...")
            if self.video_path.exists() and self._extract_audio_from_video():
                file_size = self.audio_path.stat().st_size / 1024
                print(f"   ✅ Audio extracted from video: {file_size:.2f} KB")
                self.results["audio_path"] = str(self.audio_path)
                self.results["steps_completed"].append("download_audio")
                self._mark_step_complete("download_audio", audio_path=str(self.audio_path), source_kind=self.source_kind)
                return

            if self.video_path.exists():
                print("   ⚠️  Audio extraction failed, will use video directly for transcription")
                self.results["steps_completed"].append("download_audio")
                self._mark_step_complete("download_audio", audio_path="", source_kind=self.source_kind)
                return

            raise RuntimeError("Audio extraction failed - file not found")

        # 抖音链接直接从视频提取音频（yt-dlp无法下载抖音音频）
        if DouyinDownloader.is_douyin_url(self.url):
            print("   📱 抖音视频，直接从视频提取音频...")
            if self.video_path.exists() and self._extract_audio_from_video():
                file_size = self.audio_path.stat().st_size / 1024
                print(f"   ✅ Audio extracted from video: {file_size:.2f} KB")
                self.results["audio_path"] = str(self.audio_path)
                self.results["steps_completed"].append("download_audio")
                self._mark_step_complete("download_audio", audio_path=str(self.audio_path), source_kind=self.source_kind)
                return

            # 如果提取失败但视频存在，继续使用视频进行转录
            if self.video_path.exists():
                print("   ⚠️  Will use video directly for transcription")
                self.results["steps_completed"].append("download_audio")
                self._mark_step_complete("download_audio", audio_path=str(self.audio_path) if self.audio_path.exists() else "", source_kind=self.source_kind)
                return

            raise RuntimeError("Audio extraction failed - file not found")

        # 其他平台：首先尝试从 URL 下载音频
        try:
            cmd = build_yt_dlp_command(
                "-f", "bestaudio[ext=m4a]/bestaudio",
                "--extract-audio",
                "--audio-format", "m4a",
                "-o", str(self.audio_path),
                self.url,
            )
            subprocess.run(cmd, check=True, capture_output=True)
            if self.audio_path.exists():
                file_size = self.audio_path.stat().st_size / 1024
                print(f"   ✅ Audio downloaded: {file_size:.2f} KB")
                self.results["audio_path"] = str(self.audio_path)
                self.results["steps_completed"].append("download_audio")
                self._mark_step_complete("download_audio", audio_path=str(self.audio_path), source_kind=self.source_kind)
                return
        except subprocess.CalledProcessError:
            print("   ⚠️  Audio download failed, extracting from video...")

        # 如果下载失败，从已下载的视频中提取音频
        if self.video_path.exists() and self._extract_audio_from_video():
            file_size = self.audio_path.stat().st_size / 1024
            print(f"   ✅ Audio extracted from video: {file_size:.2f} KB")
            self.results["audio_path"] = str(self.audio_path)
            self.results["steps_completed"].append("download_audio")
            self._mark_step_complete("download_audio", audio_path=str(self.audio_path), source_kind=self.source_kind)
            return

        # 如果都失败了，但视频存在，继续处理（使用视频进行转录）
        if self.video_path.exists():
            print("   ⚠️  Will use video directly for transcription")
            self.results["steps_completed"].append("download_audio")
            self._mark_step_complete("download_audio", audio_path="", source_kind=self.source_kind)
            return
            
        raise RuntimeError("Audio download/extraction failed - file not found")

    def _step_scene_detection(self) -> Dict:
        print("\n🎞️  Step 3: Detecting scenes...")
        self.scenes_dir.mkdir(exist_ok=True)
        step_started_at = time.perf_counter()
        print(f"   🧭 视频来源: {'本地文件' if self.source_kind == 'local' else '网络链接'}")
        print("   🔎 第一轮: ContentDetector")
        print("   🔎 第二轮: AdaptiveDetector")
        scene_segments, has_audio, detection_details = _detect_scene_ranges_with_details(
            self.video_path,
            threshold=self.scene_threshold,
            min_scene_duration=DEFAULT_SCENE_MIN_DURATION,
        )
        detection_elapsed = sum(item["elapsed_seconds"] for item in detection_details["passes"])
        for pass_details in detection_details["passes"]:
            print(
                "   ✅ {name} 完成: backend={backend}, raw_scenes={raw_scene_count}, elapsed={elapsed_seconds:.2f}s".format(
                    **pass_details
                )
            )
        print(f"   🔗 双轮合并后场景数: {len(scene_segments)}")

        scene_files: list[Path] = []
        skipped_short_segments = 0
        clip_elapsed = 0.0
        scene_codecs_used: set[str] = set()
        codec_fallback_used = False
        if self.extract_scenes:
            for stale_file in self.scenes_dir.glob("*.mp4"):
                stale_file.unlink()

            segments_to_render = [
                segment
                for segment in scene_segments
                if segment.end_time - segment.start_time >= DEFAULT_SCENE_MIN_DURATION
            ]
            skipped_short_segments = len(scene_segments) - len(segments_to_render)
            preferred_codec, preferred_reason = _select_scene_video_codec()
            print(f"   ✂️  切片编码器: {preferred_codec} ({preferred_reason})")
            print(f"   🧩 切片生成: {len(segments_to_render)} 个有效片段待输出")
            clip_started_at = time.perf_counter()

            for index, segment in enumerate(segments_to_render, start=1):
                output_path = self.scenes_dir / f"{self.video_path.stem}-Scene-{index:03d}.mp4"
                trim_result = _run_ffmpeg_trim(
                    self.video_path,
                    segment.start_time,
                    segment.end_time,
                    output_path,
                    start_frame=segment.start_frame,
                    end_frame=segment.end_frame,
                    has_audio=has_audio,
                )
                scene_codecs_used.add(trim_result["video_codec"])
                codec_fallback_used = codec_fallback_used or trim_result["fallback_used"]
                scene_files.append(output_path)
                if index == 1 or index == len(segments_to_render) or index % 10 == 0:
                    print(f"   ⏳ 切片进度: {index}/{len(segments_to_render)}")

            if not scene_files:
                fallback_path = self.scenes_dir / f"{self.video_path.stem}-Scene-001.mp4"
                duration, fps_value, total_frames, fallback_has_audio = _get_video_metadata(self.video_path)
                trim_result = _run_ffmpeg_trim(
                    self.video_path,
                    0.0,
                    duration,
                    fallback_path,
                    start_frame=0,
                    end_frame=total_frames,
                    has_audio=fallback_has_audio,
                )
                scene_codecs_used.add(trim_result["video_codec"])
                codec_fallback_used = codec_fallback_used or trim_result["fallback_used"]
                scene_files = [fallback_path]
            clip_elapsed = time.perf_counter() - clip_started_at

        scene_count = len(scene_files) if self.extract_scenes else len(scene_segments)
        total_elapsed = time.perf_counter() - step_started_at
        print(f"   ✅ Detected {scene_count} scenes")
        print(f"   ⏱️  检测耗时: {detection_elapsed:.2f}s")
        if self.extract_scenes:
            print(f"   ⏱️  切片耗时: {clip_elapsed:.2f}s")
            print(f"   🎬 切片编码实际使用: {', '.join(sorted(scene_codecs_used)) if scene_codecs_used else SCENE_VIDEO_CODEC}")
            if skipped_short_segments:
                print(f"   ℹ️  跳过过短片段: {skipped_short_segments}")
        print(f"   ⏱️  场景阶段总耗时: {total_elapsed:.2f}s")
        scene_info = {
            "scene_count": scene_count,
            "scenes_dir": str(self.scenes_dir) if self.extract_scenes else None,
            "threshold": self.scene_threshold,
            "min_scene_duration": DEFAULT_SCENE_MIN_DURATION,
            "source_kind": self.source_kind,
            "detection_duration_seconds": round(detection_elapsed, 3),
            "clip_generation_duration_seconds": round(clip_elapsed, 3),
            "total_duration_seconds": round(total_elapsed, 3),
            "detection_passes": detection_details["passes"],
            "merged_scene_count": detection_details["merged_scene_count"],
            "scene_video_codecs_used": sorted(scene_codecs_used),
            "scene_video_codec_fallback_used": codec_fallback_used,
            "has_audio": has_audio,
        }
        self.results["scene_detection"] = scene_info
        self.results["steps_completed"].append("scene_detection")
        self._mark_step_complete("scene_detection", **scene_info)
        return scene_info

    def _step_transcription(self) -> Dict:
        print("\n🎤 Step 4: 智能字幕提取 (B站API → 内嵌 → RapidOCR → FunASR)...")
        if self.srt_path.exists():
            print(f"   ⚠️  Transcription already exists: {self.srt_path}")
            self.results["steps_completed"].append("transcription")
            return {"status": "skipped"}
        
        # 使用智能字幕提取（四级降级）
        try:
            from extract_subtitle_funasr import smart_subtitle_extraction
        except ImportError:
            # 如果导入失败，尝试从同目录加载
            script_dir = Path(__file__).parent
            sys.path.insert(0, str(script_dir))
            from extract_subtitle_funasr import smart_subtitle_extraction
        
        # 确定视频源
        video_source = str(self.video_path) if self.video_path.exists() else None
        if not video_source:
            log.error("视频文件不存在，无法转录")
            return {"status": "failed"}
        
        success, mode = smart_subtitle_extraction(
            video_path=video_source,
            output_srt=str(self.srt_path),
            video_url=self.url,
            title=self.video_info.get("title", ""),
        )
        
        if success:
            # 读取 SRT 生成 transcript 文本
            full_text = ""
            segment_count = 0
            try:
                with open(self.srt_path, 'r', encoding='utf-8') as f:
                    lines = f.readlines()
                texts = []
                for line in lines:
                    line = line.strip()
                    if line and not line.isdigit() and '-->' not in line:
                        texts.append(line)
                        segment_count += 1
                full_text = " ".join(texts)
            except Exception:
                pass
            
            # 写 transcript 文件
            if full_text:
                self._write_transcript_from_text(full_text, self.transcript_path)
            
            print(f"   ✅ 字幕提取完成 (模式: {mode})")
            transcript_info = {
                "language": "zh",
                "mode": mode,
                "segment_count": segment_count,
                "srt_path": str(self.srt_path),
                "transcript_path": str(self.transcript_path),
                "full_text": full_text
            }
            self.results["transcription"] = transcript_info
            self.results["steps_completed"].append("transcription")
            self._mark_step_complete("transcription", mode=mode, srt_path=str(self.srt_path))
            return transcript_info
        else:
            log.error("字幕提取失败: 所有方式均未成功")
            self.results["transcription"] = {"status": "failed", "warning": "全部转录方式均失败，后续分析将缺少字幕上下文，报告质量可能受影响"}
            self.results["warnings"] = self.results.get("warnings", [])
            self.results["warnings"].append("transcription_failed: 全部转录方式（B站API/内嵌字幕/OCR/FunASR）均失败，场景分析将缺少字幕参考")
            self.results["steps_completed"].append("transcription")
            self._mark_step_complete("transcription", mode="all_failed")
            return {"status": "failed", "warning": "全部转录方式均失败"}
    
    def _write_transcript_from_text(self, text: str, output_path: Path):
        """将纯文本写入 transcript 文件"""
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(f"=== Video Transcript ===\n\n")
            f.write(f"=== Full Text ===\n\n{text}\n")

    @staticmethod
    def _funasr_to_segments(funasr_result) -> List[Dict]:
        """
        将 FunASR 返回结果转换为 Whisper 兼容的 segments 格式
        每个 segment: {"start": float_seconds, "end": float_seconds, "text": str}
        """
        segments = []
        for res in funasr_result:
            text = res.get('text', '').strip()
            sentence_info = res.get('sentence_info', [])
            timestamps = res.get('timestamp', [])
            
            if sentence_info:
                # 方案A: 使用句级时间戳（最佳）
                for sent in sentence_info:
                    sent_text = sent.get('text', '').strip()
                    if sent_text:
                        segments.append({
                            "start": sent.get('start', 0) / 1000.0,
                            "end": sent.get('end', 0) / 1000.0,
                            "text": sent_text
                        })
            elif timestamps and text:
                # 方案B: 按标点切分 + 字级时间戳映射
                sentence_endings = set('。！？!?；;…')
                clause_breaks = set('，,、')
                current_chars = []
                current_start_idx = 0
                ts_len = len(timestamps)
                text_len = len(text)
                
                for char_idx, char in enumerate(text):
                    current_chars.append(char)
                    ts_idx = min(int(char_idx / text_len * ts_len), ts_len - 1) if ts_len > 0 else 0
                    is_end = char in sentence_endings
                    is_clause = char in clause_breaks and len(current_chars) > 25
                    is_last = char_idx == text_len - 1
                    
                    if is_end or is_clause or is_last:
                        sent_text = ''.join(current_chars).strip()
                        if sent_text:
                            start_ts_idx = min(int(current_start_idx / text_len * ts_len), ts_len - 1) if ts_len > 0 else 0
                            start_ms = timestamps[start_ts_idx][0] if ts_len > 0 else 0
                            end_ms = timestamps[ts_idx][1] if ts_len > 0 else 0
                            segments.append({
                                "start": start_ms / 1000.0,
                                "end": end_ms / 1000.0,
                                "text": sent_text
                            })
                        current_chars = []
                        current_start_idx = char_idx + 1
            elif text:
                # 方案C: 无时间戳，仅文本
                segments.append({
                    "start": 0.0,
                    "end": 0.0,
                    "text": text
                })
        return segments

    def _write_srt(self, segments: List[Dict], output_path: Path):
        with open(output_path, "w", encoding="utf-8") as f:
            for i, segment in enumerate(segments, 1):
                start = self._format_timestamp(segment["start"])
                end = self._format_timestamp(segment["end"])
                text = segment["text"].strip()
                f.write(f"{i}\\n{start} --> {end}\\n{text}\\n\\n")

    def _write_transcript(self, segments: List[Dict], output_path: Path):
        with open(output_path, "w", encoding="utf-8") as f:
            f.write("=== Video Transcript ===\\n\\n")
            f.write("=== Full Text ===\\n\\n")
            full_text = " ".join([seg["text"].strip() for seg in segments])
            f.write(full_text + "\\n\\n")
            f.write("=== Timestamped Text ===\\n\\n")
            for seg in segments:
                start = self._format_timestamp(seg["start"])
                end = self._format_timestamp(seg["end"])
                f.write(f"[{start} --> {end}]\\n")
                f.write(f"{seg['text'].strip()}\\n\\n")

    def _format_timestamp(self, seconds: float) -> str:
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        millis = int((seconds % 1) * 1000)
        return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"

    def _ensure_primary_frame(self, scene_file: Path, scene_stem: str) -> Path:
        sample_paths = build_frame_sample_paths(self.frames_dir, scene_stem)
        primary_path = sample_paths["primary"]
        if primary_path.exists():
            return primary_path

        duration_seconds = probe_duration_seconds(scene_file)
        timestamp = max(duration_seconds * 0.5, 0.0) if duration_seconds > 0 else 0.0
        base_cmd = [
            "ffmpeg",
            "-ss",
            f"{timestamp:.3f}",
            "-i",
            str(scene_file),
            "-frames:v",
            "1",
            "-q:v",
            "2",
            str(primary_path),
            "-y",
        ]
        attempts = []
        hwaccel_args = ffmpeg_hwaccel_args()
        if hwaccel_args:
            attempts.append(["ffmpeg", *hwaccel_args, *base_cmd[1:]])
        attempts.append(base_cmd)

        for cmd in attempts:
            try:
                subprocess.run(cmd, check=True, capture_output=True)
                return primary_path
            except (OSError, subprocess.CalledProcessError):
                continue
        else:
            extract_scene_sample_frames(scene_file, self.frames_dir, scene_stem)
        return primary_path

    def _step_extract_frames(self, scene_info: Dict):
        print("\\n🖼️  Step 5: Extracting frames from scenes...")
        if not self.extract_scenes or scene_info["scene_count"] == 0:
            print("   ⚠️  Scene extraction disabled or no scenes found")
            return
        self.frames_dir.mkdir(exist_ok=True)
        scene_files = sorted(self.scenes_dir.glob("*.mp4"))
        extracted_scenes = 0
        for scene_file in scene_files:
            scene_name = scene_file.stem
            safe_scene_name = sanitize_filename(scene_name)
            primary_path = build_frame_sample_paths(self.frames_dir, safe_scene_name)["primary"]
            if primary_path.exists():
                continue
            self._ensure_primary_frame(scene_file, safe_scene_name)
            extracted_scenes += 1
        frame_count = len(scene_files)
        sample_frame_count = len(list(self.frames_dir.glob("*.jpg")))
        print(f"   ✅ 已为 {frame_count} 个场景准备主截图")
        print("   ⏭️  首中尾三帧改为在当前批次生成 contact sheet 时按需补齐")
        print(f"   🧮 本轮新增处理场景: {extracted_scenes}，当前总帧文件数: {sample_frame_count}")
        self.results["frames_dir"] = str(self.frames_dir)
        self.results["frame_count"] = frame_count
        self.results["frame_sample_count"] = sample_frame_count
        self.results["steps_completed"].append("extract_frames")
        self._mark_step_complete("extract_frames", frame_count=sample_frame_count)

    def _step_prepare_scoring(self, scene_info: Dict):
        print("\\n📊 Step 6: Preparing scene scoring structure...")
        if not self.extract_scenes or scene_info["scene_count"] == 0:
            print("   ⚠️  No scenes to score")
            return
        scene_files = sorted(self.scenes_dir.glob("*.mp4"))
        scoring_data = {
            "video_id": self.video_id,
            "url": self.url,
            "title": self.video_info.get("title", ""),
            "video_title": self.video_info.get("title", ""),
            "total_scenes": len(scene_files),
            "analysis_framework": {
                "philosophy": "Walter Murch's Six Rules: Emotion > Story > Rhythm > Eye-trace > 2D Plane > 3D Space",
                "scoring_criteria": {
                    "aesthetic_beauty": {"name": "美感 (Aesthetic Beauty)", "weight": "20%", "description": "构图(三分法)、光影质感、色彩和谐度", "scale": "1-10"},
                    "credibility": {"name": "可信度 (Credibility)", "weight": "20%", "description": "表演自然度、物理逻辑真实感、无出戏感", "scale": "1-10"},
                    "impact": {"name": "冲击力 (Impact)", "weight": "20%", "description": "视觉显著性、动态张力、第一眼冲击力", "scale": "1-10"},
                    "memorability": {"name": "记忆度 (Memorability)", "weight": "20%", "description": "独特视觉符号(Von Restorff效应)、金句、趣味性", "scale": "1-10"},
                    "fun_interest": {"name": "趣味度 (Fun/Interest)", "weight": "20%", "description": "参与感、娱乐价值、社交货币潜力", "scale": "1-10"}
                },
                "type_classification": {
                    "TYPE-A": "Hook/Kinetic - 视觉钩子/高能 (高饱和、奇观、快节奏)",
                    "TYPE-B": "Narrative/Emotion - 叙事/情感 (人物对话、细微表情)",
                    "TYPE-C": "Aesthetic/Vibe - 氛围/空镜 (风景、慢动作、极简)",
                    "TYPE-D": "Commercial/Info - 商业/展示 (产品特写、口播)"
                },
                "selection_rules": {
                    "MUST_KEEP": "加权总分 > 8.5 或 任意单项 = 10 (极致长板)",
                    "USABLE": "7.0 <= 加权总分 < 8.5 (过渡素材)",
                    "DISCARD": "加权总分 < 7.0 或存在致命瑕疵"
                }
            },
            "scenes": [],
            "instructions": "基于 Walter Murch 法则，对每个场景进行评分。考虑场景类型权重: Hook型侧重IMPACT, 叙事型侧重CREDIBILITY, 氛围型侧重AESTHETICS, 商业型侧重CREDIBILITY+MEMORABILITY"
        }
        for i, scene_file in enumerate(scene_files, 1):
            scene_stem = sanitize_filename(scene_file.stem)
            sample_path_map = build_frame_sample_paths(self.frames_dir, scene_stem)
            primary_path = sample_path_map["primary"]
            if not primary_path.exists():
                primary_path = self._ensure_primary_frame(scene_file, scene_stem)
            sample_paths = {key: str(path) for key, path in sample_path_map.items()}
            camera_movement_value = "TODO: 运镜（如静止镜头/推进/摇镜）"
            # These TODO markers are intentional completeness guards. Finalize stops
            # when any scene still carries placeholder analysis instead of real output.
            scene_data = {
                "scene_number": i,
                "filename": scene_file.name,
                "file_path": str(scene_file),
                "frame_path": str(primary_path),
                "frame_samples": sample_paths,
                "start_time_seconds": None,
                "end_time_seconds": None,
                "duration_seconds": None,
                "timestamp_range": "",
                "type_classification": "TODO: 选择 TYPE-A/B/C/D",
                "description": "TODO: 一句话描述画面内容",
                "visual_summary": "TODO: 视觉内容摘要",
                "motion_analysis": {},
                "storyboard": {
                    "visual_description": "TODO: 一句话描述画面内容",
                    "voiceover": "",
                    "shot_size": "TODO: 景别（如远景/中景/特写）",
                    "lighting": "TODO: 灯光（如自然光/侧逆光/硬光）",
                    "camera_movement": camera_movement_value,
                    "visual_style": "TODO: 画风（如暖色纪实/黑白艺术感）",
                    "technique": "TODO: 手法（如特写突出表情/留白营造氛围）",
                    "camera_movement_hint": "",
                    "camera_movement_rationale": "",
                    "screenshot_path": str(primary_path),
                    "timestamp": "",
                },
                "scores": {"aesthetic_beauty": 0, "credibility": 0, "impact": 0, "memorability": 0, "fun_interest": 0},
                "weighted_score": 0.0,
                "selection": "TODO: [MUST KEEP] / [USABLE] / [DISCARD]",
                "selection_reasoning": "TODO: 引用相关理论解释选择原因",
                "edit_suggestion": "TODO: 剪辑建议（保留几秒、是否需要静音等）",
                "notes": "TODO: 其他观察笔记"
            }
            scoring_data["scenes"].append(scene_data)
        with open(self.scores_path, "w", encoding="utf-8") as f:
            json.dump(scoring_data, f, indent=2, ensure_ascii=False)
        print(f"   ✅ Scoring template created: {self.scores_path}")
        print(f"   📝 需要对 {len(scene_files)} 个场景进行评分")
        self.results["scoring_template"] = str(self.scores_path)
        self.results["steps_completed"].append("prepare_scoring")
        self._mark_step_complete("prepare_scoring", scores_path=str(self.scores_path))

    def _step_refine_music_subtitles(self, transcript_info: Dict) -> Dict:
        print("\\n🎼 Step 6.5: Refining music subtitles with scene-frame OCR...")
        if not self.scores_path.exists():
            print("   ⚠️  scene_scores.json 不存在，跳过 OCR 矫正")
            self.results["steps_completed"].append("refine_music_subtitles")
            return transcript_info

        try:
            from lyric_ocr_refiner import refine_music_subtitles
        except ImportError:
            script_dir = Path(__file__).parent
            sys.path.insert(0, str(script_dir))
            from lyric_ocr_refiner import refine_music_subtitles

        result = refine_music_subtitles(
            scores_path=self.scores_path,
            video_dir=self.video_output_dir,
            title=self.video_info.get("title", ""),
            url=self.url,
            source_mode=transcript_info.get("mode", "") if isinstance(transcript_info, dict) else "",
        )

        if result.get("status") == "corrected":
            print(f"   ✅ OCR 矫正字幕已生成: {result.get('subtitle_path')}")
            if isinstance(transcript_info, dict):
                transcript_info["corrected_srt_path"] = result.get("subtitle_path", "")
                transcript_info["corrected_transcript_path"] = result.get("transcript_path", "")
                transcript_info["ocr_refined"] = True
        else:
            print(f"   ⚠️  OCR 矫正未启用: {result.get('reason', 'no_result')}")
            if isinstance(transcript_info, dict):
                transcript_info["ocr_refined"] = False

        self.results["subtitle_refinement"] = result
        self.results["steps_completed"].append("refine_music_subtitles")
        self._mark_step_complete("refine_music_subtitles", status=result.get("status", "unknown"))
        return transcript_info

    def _step_ai_scene_analysis(self, scene_info: Dict):
        print("\\n🤖 Step 7: Analyzing scenes with AI framework...")
        if not self.extract_scenes or scene_info["scene_count"] == 0:
            print("   ⚠️  No scenes to analyze")
            return
        scene_files = sorted(self.scenes_dir.glob("*.mp4"))
        for i, scene_file in enumerate(scene_files, 1):
            frame_path = self.frames_dir / f"{scene_file.stem}.jpg"
            analysis = {"scene_number": i, "filename": scene_file.name, "frame_path": str(frame_path) if frame_path.exists() else None, "ai_analysis_ready": True, "notes": "请查看帧图片后进行专业分析"}
            self.results["scene_analysis"].append(analysis)
        print(f"   ✅ 已为 {len(scene_files)} 个场景准备 AI 分析框架")
        self.results["steps_completed"].append("ai_scene_analysis")
        self._mark_step_complete("ai_scene_analysis", scene_count=len(scene_files))

    def _step_auto_select_best_shots(self, scene_info: Dict):
        print(f"\\n⭐ Step 8: Auto-selecting best shots (threshold: {self.best_threshold})...")
        self.best_shots_dir.mkdir(exist_ok=True)
        print(f"   ✅ 精选片段目录已创建: {self.best_shots_dir}")
        print(f"   📝 完成评分后运行: python3 scripts/scoring_helper_enhanced.py {self.scores_path} best")
        self.results["best_shots_dir"] = str(self.best_shots_dir)
        self.results["steps_completed"].append("auto_select_best_shots")
        self._mark_step_complete("auto_select_best_shots", best_shots_dir=str(self.best_shots_dir))

    def _check_scene_completeness(self, scores_data: Dict, scene_info: Dict) -> Tuple[bool, List[int]]:
        """检查所有场景是否都有评分数据"""
        total_scenes = scene_info.get("scene_count", 0)
        scenes_with_scores = scores_data.get("scenes", [])

        scored_scene_numbers = set()
        for scene in scenes_with_scores:
            if "scene_number" in scene and scene_has_complete_analysis(scene):
                scored_scene_numbers.add(scene["scene_number"])

        expected_scene_numbers = set(range(1, total_scenes + 1))
        missing_scenes = sorted(expected_scene_numbers - scored_scene_numbers)

        return len(missing_scenes) == 0, missing_scenes

    def _step_generate_detailed_report(self, scene_info: Dict, transcript_info: Dict):
        print("\\n📄 Step 9: Generating detailed analysis report...")
        if not self.scores_path.exists():
            print("   ⚠️  scene_scores.json 不存在，跳过详细报告初始化")
            return

        with open(self.scores_path, "r", encoding="utf-8") as f:
            scores_data = json.load(f)

        # 场景完整性检查
        is_complete, missing_scenes = self._check_scene_completeness(scores_data, scene_info)
        if not is_complete:
            print(f"   ⚠️  当前仅完成素材准备，仍有 {len(missing_scenes)} 个场景待宿主模型分析")
            print(f"   🧭 待分析场景编号: {missing_scenes[:10]}{'...' if len(missing_scenes) > 10 else ''}")
            outputs = generate_detailed_analysis_outputs(scores_data, self.video_output_dir, strict=False)
            self.detailed_report_path = outputs["detailed_report_path"]
            print(f"   ✅ 草稿报告已更新: {self.detailed_report_path}")
            print(f"   🗂️  Scene report drafts: {outputs['scene_reports_dir']}")
            self.results["detailed_report_path"] = str(self.detailed_report_path)
            self.results["steps_completed"].append("generate_detailed_report")
            self._mark_step_complete("generate_detailed_report", report_path=str(self.detailed_report_path), draft_only=True)
            return

        print(f"   ✅ 场景完整性检查通过: 所有 {scene_info.get('scene_count', 0)} 个场景都有评分数据")

        scores_data.setdefault("video_id", self.video_id)
        scores_data.setdefault("url", self.url)
        scores_data.setdefault("video_title", self.video_info.get("title", self.video_id))

        outputs = generate_detailed_analysis_outputs(scores_data, self.video_output_dir, strict=False)
        self.detailed_report_path = outputs["detailed_report_path"]
        print(f"   ✅ Detailed report initialized: {self.detailed_report_path}")
        print(f"   🗂️  Scene report drafts: {outputs['scene_reports_dir']}")
        self.results["detailed_report_path"] = str(self.detailed_report_path)
        self.results["steps_completed"].append("generate_detailed_report")
        self._mark_step_complete("generate_detailed_report", report_path=str(self.detailed_report_path))


def main():
    parser = argparse.ArgumentParser(
        description="Video Expert Analyzer - Enhanced Pipeline with Configurable Output",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # 首次运行，设置输出目录
  python3 pipeline_enhanced.py --setup

  # 分析视频
  python3 pipeline_enhanced.py https://www.bilibili.com/video/BV1xxxxx

  # 使用自定义输出目录
  python3 pipeline_enhanced.py URL -o /path/to/output

   # 使用自定义场景检测阈值
   python3 pipeline_enhanced.py URL --scene-threshold 20
        """
    )
    parser.add_argument("url", nargs="?", help="Video URL 或本地视频文件路径")
    parser.add_argument("-o", "--output", help="Output directory (default: from config)")
    parser.add_argument("--setup", action="store_true", help="Setup output directory configuration")
    parser.add_argument("--scene-threshold", type=float, default=27.0, help="Scene detection threshold (default: 27.0)")
    parser.add_argument("--no-extract-scenes", action="store_true", help="Skip extracting individual scene clips")
    parser.add_argument("--best-threshold", type=float, default=7.5, help="Threshold for best shots selection (default: 7.5)")
    parser.add_argument("--json-output", help="Save results as JSON to this file")
    args = parser.parse_args()
    if args.setup:
        setup_output_directory()
        return 0
    if args.output:
        output_dir = args.output
    else:
        output_dir = get_output_directory()
        print(f"📁 使用配置中的输出目录: {output_dir}")
    if not args.url:
        print("❌ Error: 请提供视频 URL 或本地视频文件路径，或使用 --setup 配置输出目录")
        parser.print_help()
        return 1
    try:
        pipeline = VideoAnalysisPipeline(
            url=args.url,
            output_dir=output_dir,
            scene_threshold=args.scene_threshold,
            extract_scenes=not args.no_extract_scenes,
            best_threshold=args.best_threshold
        )
        results = pipeline.run()
        if args.json_output:
            with open(args.json_output, "w", encoding="utf-8") as f:
                json.dump(results, f, indent=2, ensure_ascii=False)
            print(f"\\n📊 Results saved to: {args.json_output}")
        return 0
    except Exception as e:
        print(f"\\n❌ Error: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
