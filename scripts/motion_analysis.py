#!/usr/bin/env python3
from __future__ import annotations

import math
import platform
import shutil
import subprocess
from pathlib import Path
from typing import Dict, Optional


SAMPLE_POSITIONS = {
    "start": 0.10,
    "mid": 0.50,
    "end": 0.90,
}

MOTION_ANALYSIS_VERSION = "anchor-v2"
_FFMPEG_HWACCEL_CACHE: Optional[set[str]] = None


def _parse_ffmpeg_hwaccels(raw_output: str) -> set[str]:
    hwaccels = set()
    for line in (raw_output or "").splitlines():
        value = line.strip()
        if not value or value.endswith(":") or " " in value:
            continue
        hwaccels.add(value)
    return hwaccels


def _get_ffmpeg_hwaccels() -> set[str]:
    global _FFMPEG_HWACCEL_CACHE
    if _FFMPEG_HWACCEL_CACHE is not None:
        return set(_FFMPEG_HWACCEL_CACHE)

    ffmpeg_binary = shutil.which("ffmpeg") or "ffmpeg"
    try:
        result = subprocess.run(
            [ffmpeg_binary, "-hide_banner", "-hwaccels"],
            capture_output=True,
            text=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        _FFMPEG_HWACCEL_CACHE = set()
    else:
        _FFMPEG_HWACCEL_CACHE = _parse_ffmpeg_hwaccels(
            f"{result.stdout or ''}\n{result.stderr or ''}"
        )
    return set(_FFMPEG_HWACCEL_CACHE)


def ffmpeg_hwaccel_args(system_name: Optional[str] = None) -> list[str]:
    system_name = system_name or platform.system()
    candidates = {
        "Darwin": ("videotoolbox",),
        "Windows": ("d3d11va", "dxva2"),
    }.get(system_name, ())
    available = _get_ffmpeg_hwaccels()
    for candidate in candidates:
        if candidate in available:
            return ["-hwaccel", candidate]
    return []


def probe_duration_seconds(media_path: Path) -> float:
    if not media_path.exists():
        return 0.0
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(media_path),
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        return max(float(result.stdout.strip()), 0.0)
    except (OSError, subprocess.CalledProcessError, ValueError):
        return 0.0


def build_frame_sample_paths(frames_dir: Path, scene_stem: str) -> Dict[str, Path]:
    return {
        "primary": frames_dir / f"{scene_stem}.jpg",
        "start": frames_dir / f"{scene_stem}__start.jpg",
        "mid": frames_dir / f"{scene_stem}__mid.jpg",
        "end": frames_dir / f"{scene_stem}__end.jpg",
    }


def extract_scene_sample_frames(scene_path: Path, frames_dir: Path, scene_stem: str) -> Dict[str, object]:
    frames_dir.mkdir(exist_ok=True)
    sample_paths = build_frame_sample_paths(frames_dir, scene_stem)
    duration_seconds = probe_duration_seconds(scene_path)
    hwaccel_args = ffmpeg_hwaccel_args()

    for name, ratio in SAMPLE_POSITIONS.items():
        target_path = sample_paths[name]
        if target_path.exists():
            continue
        timestamp = max(duration_seconds * ratio, 0.0) if duration_seconds > 0 else 0.0
        attempts = []
        base_cmd = [
            "ffmpeg",
            "-ss",
            f"{timestamp:.3f}",
            "-i",
            str(scene_path),
            "-frames:v",
            "1",
            "-q:v",
            "2",
            str(target_path),
            "-y",
        ]
        if hwaccel_args:
            attempts.append(["ffmpeg", *hwaccel_args, *base_cmd[1:]])
        attempts.append(base_cmd)

        for cmd in attempts:
            try:
                subprocess.run(cmd, check=True, capture_output=True)
                break
            except (OSError, subprocess.CalledProcessError):
                continue
        else:
            fallback_source = next((path for path in sample_paths.values() if path.exists()), None)
            if fallback_source is None:
                raise RuntimeError(f"无法为 {scene_path} 提取样本帧")
            shutil.copy2(fallback_source, target_path)

    if sample_paths["mid"].exists():
        sample_paths["primary"].write_bytes(sample_paths["mid"].read_bytes())
    else:
        fallback_source = next((path for path in sample_paths.values() if path.exists()), None)
        if fallback_source is not None:
            shutil.copy2(fallback_source, sample_paths["primary"])
    return {
        "duration_seconds": duration_seconds,
        "sample_paths": {key: str(path) for key, path in sample_paths.items()},
    }


def _load_gray_image(path: Path):
    import cv2

    image = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
    if image is None:
        return None
    return cv2.resize(image, (320, 180))


def _estimate_transform(image_a, image_b):
    import cv2
    import numpy as np

    source = image_a.astype("float32") / 255.0
    target = image_b.astype("float32") / 255.0
    warp = np.eye(2, 3, dtype="float32")
    criteria = (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 50, 1e-6)
    try:
        correlation, warp = cv2.findTransformECC(
            source,
            target,
            warp,
            cv2.MOTION_AFFINE,
            criteria,
        )
    except cv2.error:
        return None

    a, b, dx = warp[0]
    c, d, dy = warp[1]
    scale_x = math.sqrt(a * a + c * c)
    scale_y = math.sqrt(b * b + d * d)
    return {
        "scale": float((scale_x + scale_y) / 2.0),
        "dx": float(dx),
        "dy": float(dy),
        "correlation": float(correlation),
    }


def _build_affine_metrics(start_points, end_points, width: int, height: int) -> Optional[Dict[str, object]]:
    import cv2
    import numpy as np

    if len(start_points) < 12 or len(end_points) < 12:
        return None

    matrix, inlier_mask = cv2.estimateAffinePartial2D(
        start_points,
        end_points,
        method=cv2.RANSAC,
        ransacReprojThreshold=3.0,
        maxIters=4000,
        confidence=0.995,
    )
    if matrix is None or inlier_mask is None:
        return None

    inliers = inlier_mask.ravel().astype(bool)
    if inliers.sum() < 10:
        return None

    start_inliers = start_points[inliers]
    end_inliers = end_points[inliers]
    displacement = end_inliers - start_inliers

    a, b, _ = matrix[0]
    c, d, _ = matrix[1]
    scale = float((math.sqrt(a * a + c * c) + math.sqrt(b * b + d * d)) / 2.0)

    center = np.array([width / 2.0, height / 2.0], dtype="float32")
    start_radius = np.linalg.norm(start_inliers - center, axis=1)
    end_radius = np.linalg.norm(end_inliers - center, axis=1)
    valid_radius = start_radius > max(width, height) * 0.05

    radial_ratio = 1.0
    radial_change = 0.0
    radial_consistency = 0.0
    if valid_radius.any():
        radial_ratio_values = end_radius[valid_radius] / start_radius[valid_radius]
        radial_ratio = float(np.median(radial_ratio_values))
        radial_change_values = radial_ratio_values - 1.0
        radial_change = float(np.median(radial_change_values))
        dominant_sign = 1 if radial_change >= 0 else -1
        if abs(radial_change) < 0.01:
            radial_consistency = 1.0
        else:
            radial_consistency = float(
                np.mean(np.sign(radial_change_values) == dominant_sign)
            )

    anchor_dx = float(np.median(displacement[:, 0]))
    anchor_dy = float(np.median(displacement[:, 1]))
    anchor_dx_ratio = anchor_dx / float(width)
    anchor_dy_ratio = anchor_dy / float(height)
    camera_dx_ratio = -anchor_dx_ratio
    camera_dy_ratio = -anchor_dy_ratio

    x_sign = 1 if anchor_dx >= 0 else -1
    y_sign = 1 if anchor_dy >= 0 else -1
    x_consistency = float(np.mean(np.sign(displacement[:, 0]) == x_sign)) if abs(anchor_dx_ratio) >= 0.01 else 1.0
    y_consistency = float(np.mean(np.sign(displacement[:, 1]) == y_sign)) if abs(anchor_dy_ratio) >= 0.01 else 1.0

    return {
        "scale": scale,
        "radial_ratio": radial_ratio,
        "radial_change": radial_change,
        "radial_consistency": radial_consistency,
        "anchor_dx": anchor_dx,
        "anchor_dy": anchor_dy,
        "anchor_dx_ratio": camera_dx_ratio,
        "anchor_dy_ratio": camera_dy_ratio,
        "x_consistency": x_consistency,
        "y_consistency": y_consistency,
        "inlier_count": int(inliers.sum()),
        "track_count": int(len(start_points)),
    }


def _track_anchor_points(image_a, image_b):
    import cv2
    import numpy as np

    feature_points = cv2.goodFeaturesToTrack(
        image_a,
        maxCorners=360,
        qualityLevel=0.01,
        minDistance=8,
        blockSize=7,
    )
    if feature_points is None or len(feature_points) < 20:
        return None

    next_points, status, _ = cv2.calcOpticalFlowPyrLK(
        image_a,
        image_b,
        feature_points,
        None,
        winSize=(21, 21),
        maxLevel=3,
        criteria=(cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 30, 0.01),
    )
    if next_points is None or status is None:
        return None

    back_points, back_status, _ = cv2.calcOpticalFlowPyrLK(
        image_b,
        image_a,
        next_points,
        None,
        winSize=(21, 21),
        maxLevel=3,
        criteria=(cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 30, 0.01),
    )
    if back_points is None or back_status is None:
        return None

    start = feature_points.reshape(-1, 2)
    tracked = next_points.reshape(-1, 2)
    backtracked = back_points.reshape(-1, 2)
    valid = (
        status.reshape(-1).astype(bool)
        & back_status.reshape(-1).astype(bool)
        & (np.linalg.norm(start - backtracked, axis=1) < 2.5)
    )

    if valid.sum() < 12:
        return None
    return start[valid], tracked[valid]


def _collect_anchor_metrics(start_image, mid_image, end_image):
    height, width = start_image.shape[:2]
    first_leg = _track_anchor_points(start_image, mid_image)
    second_leg = _track_anchor_points(mid_image, end_image)
    full_leg = _track_anchor_points(start_image, end_image)
    if not first_leg or not second_leg or not full_leg:
        return None

    first_metrics = _build_affine_metrics(first_leg[0], first_leg[1], width, height)
    second_metrics = _build_affine_metrics(second_leg[0], second_leg[1], width, height)
    full_metrics = _build_affine_metrics(full_leg[0], full_leg[1], width, height)
    if not first_metrics or not second_metrics or not full_metrics:
        return None

    scale_delta = full_metrics["scale"] - 1.0
    first_scale_delta = first_metrics["scale"] - 1.0
    second_scale_delta = second_metrics["scale"] - 1.0
    scale_consistency = 1.0
    if max(abs(first_scale_delta), abs(second_scale_delta), abs(scale_delta)) >= 0.02:
        dominant = 1 if scale_delta >= 0 else -1
        leg_signs = []
        for value in (first_scale_delta, second_scale_delta):
            if abs(value) >= 0.015:
                leg_signs.append(1 if value >= 0 else -1)
        if leg_signs:
            scale_consistency = sum(sign == dominant for sign in leg_signs) / len(leg_signs)

    return {
        "width": width,
        "height": height,
        "scale": full_metrics["scale"],
        "scale_delta": scale_delta,
        "camera_dx_ratio": full_metrics["anchor_dx_ratio"],
        "camera_dy_ratio": full_metrics["anchor_dy_ratio"],
        "radial_ratio": full_metrics["radial_ratio"],
        "radial_change": full_metrics["radial_change"],
        "radial_consistency": full_metrics["radial_consistency"],
        "x_consistency": full_metrics["x_consistency"],
        "y_consistency": full_metrics["y_consistency"],
        "scale_consistency": scale_consistency,
        "inlier_count": full_metrics["inlier_count"],
        "track_count": full_metrics["track_count"],
        "anchor_dx": full_metrics["anchor_dx"],
        "anchor_dy": full_metrics["anchor_dy"],
    }


def _motion_confidence(metrics: Dict[str, float]) -> str:
    quality = min(metrics["inlier_count"] / 80.0, 1.0)
    consistency = min(
        1.0,
        (
            metrics["radial_consistency"]
            + metrics["x_consistency"]
            + metrics["y_consistency"]
            + metrics["scale_consistency"]
        )
        / 4.0,
    )
    score = quality * 0.55 + consistency * 0.45
    if score >= 0.78:
        return "high"
    if score >= 0.52:
        return "medium"
    return "low"


def _classify_motion(metrics: Dict[str, float], duration_seconds: float) -> Dict[str, object]:
    scale_delta = metrics["scale_delta"]
    camera_dx_ratio = metrics["camera_dx_ratio"]
    camera_dy_ratio = metrics["camera_dy_ratio"]
    radial_change = metrics["radial_change"]

    direction = ""
    label = "轻微移动镜头"

    zoom_strength = abs(scale_delta)
    translation_strength = max(abs(camera_dx_ratio), abs(camera_dy_ratio))
    per_second_zoom = zoom_strength / max(duration_seconds, 0.001)

    if zoom_strength <= 0.02 and translation_strength <= 0.015:
        label = "静止镜头"
        direction = "static"
    elif (
        zoom_strength >= 0.05
        and (
            metrics["track_count"] == 0
            or metrics["scale_consistency"] >= 0.5
            or metrics["radial_consistency"] >= 0.62
        )
    ):
        is_fast = per_second_zoom >= 0.06 or zoom_strength >= 0.14
        if scale_delta >= 0:
            label = "快速推进" if is_fast else "稳定前推"
        else:
            label = "快速拉远" if is_fast else "稳定拉远"
        direction = "scale"
    elif abs(camera_dx_ratio) >= 0.03 and abs(camera_dx_ratio) > abs(camera_dy_ratio) * 1.25 and metrics["x_consistency"] >= 0.6:
        label = "向右摇镜" if camera_dx_ratio > 0 else "向左摇镜"
        direction = "x"
    elif abs(camera_dy_ratio) >= 0.03 and abs(camera_dy_ratio) > abs(camera_dx_ratio) * 1.25 and metrics["y_consistency"] >= 0.6:
        label = "向下俯仰" if camera_dy_ratio > 0 else "向上俯仰"
        direction = "y"
    elif (
        abs(radial_change) >= 0.06
        and translation_strength <= 0.03
        and metrics["radial_consistency"] >= 0.6
    ):
        if radial_change >= 0:
            label = "稳定前推"
        else:
            label = "稳定拉远"
        direction = "scale"

    confidence = _motion_confidence(metrics)
    rationale = (
        f"基于 {metrics['inlier_count']}/{metrics['track_count']} 个场景锚点跟踪，"
        f"镜头对应的水平位移约 {camera_dx_ratio * 100:.1f}% ，"
        f"垂直位移约 {camera_dy_ratio * 100:.1f}% ，"
        f"锚点离中心的整体变化约 {radial_change * 100:.1f}% 。"
    )
    return {
        "label": label,
        "confidence": confidence,
        "direction": direction,
        "rationale": rationale,
        "version": MOTION_ANALYSIS_VERSION,
    }


def analyze_camera_motion(sample_paths: Dict[str, str], duration_seconds: float = 0.0) -> Dict[str, object]:
    try:
        start_image = _load_gray_image(Path(sample_paths["start"]))
        mid_image = _load_gray_image(Path(sample_paths["mid"]))
        end_image = _load_gray_image(Path(sample_paths["end"]))
    except ImportError:
        return {
            "label": "镜头变化待人工确认",
            "confidence": "low",
            "rationale": "当前环境缺少图像比对依赖，未能完成自动运镜判断。",
            "version": MOTION_ANALYSIS_VERSION,
        }

    if start_image is None or mid_image is None or end_image is None:
        return {
            "label": "镜头变化待人工确认",
            "confidence": "low",
            "rationale": "首中尾帧不完整，未能完成自动运镜判断。",
            "version": MOTION_ANALYSIS_VERSION,
        }

    metrics = _collect_anchor_metrics(start_image, mid_image, end_image)
    if metrics:
        result = _classify_motion(metrics, duration_seconds)
        result["metrics"] = {
            "scale": round(metrics["scale"], 4),
            "scale_delta": round(metrics["scale_delta"], 4),
            "camera_dx_ratio": round(metrics["camera_dx_ratio"], 4),
            "camera_dy_ratio": round(metrics["camera_dy_ratio"], 4),
            "radial_change": round(metrics["radial_change"], 4),
            "inlier_count": metrics["inlier_count"],
            "track_count": metrics["track_count"],
            "radial_consistency": round(metrics["radial_consistency"], 4),
            "x_consistency": round(metrics["x_consistency"], 4),
            "y_consistency": round(metrics["y_consistency"], 4),
        }
        return result

    first_leg = _estimate_transform(start_image, mid_image)
    second_leg = _estimate_transform(mid_image, end_image)
    if not first_leg or not second_leg:
        return {
            "label": "镜头变化待人工确认",
            "confidence": "low",
            "rationale": "锚点跟踪和画面对齐都失败，未能完成自动运镜判断。",
            "version": MOTION_ANALYSIS_VERSION,
        }

    fallback_metrics = {
        "scale_delta": ((first_leg["scale"] + second_leg["scale"]) / 2.0) - 1.0,
        "camera_dx_ratio": -((first_leg["dx"] + second_leg["dx"]) / 2.0) / 320.0,
        "camera_dy_ratio": -((first_leg["dy"] + second_leg["dy"]) / 2.0) / 180.0,
        "radial_change": ((first_leg["scale"] + second_leg["scale"]) / 2.0) - 1.0,
        "scale": (first_leg["scale"] + second_leg["scale"]) / 2.0,
        "radial_consistency": 0.45,
        "x_consistency": 0.45,
        "y_consistency": 0.45,
        "scale_consistency": 0.45,
        "inlier_count": 0,
        "track_count": 0,
    }
    result = _classify_motion(fallback_metrics, duration_seconds)
    result["confidence"] = "low"
    result["rationale"] = (
        f"未能稳定跟踪场景锚点，退回到整体画幅变化估计："
        f"水平位移约 {fallback_metrics['camera_dx_ratio'] * 100:.1f}% ，"
        f"垂直位移约 {fallback_metrics['camera_dy_ratio'] * 100:.1f}% ，"
        f"缩放变化约 {fallback_metrics['scale_delta'] * 100:.1f}% 。"
    )
    result["metrics"] = {
        "scale": round(fallback_metrics["scale"], 4),
        "scale_delta": round(fallback_metrics["scale_delta"], 4),
        "camera_dx_ratio": round(fallback_metrics["camera_dx_ratio"], 4),
        "camera_dy_ratio": round(fallback_metrics["camera_dy_ratio"], 4),
        "radial_change": round(fallback_metrics["radial_change"], 4),
        "inlier_count": 0,
        "track_count": 0,
    }
    return result
