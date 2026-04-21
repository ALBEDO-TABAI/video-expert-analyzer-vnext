#!/usr/bin/env python3
"""
Video Expert Analyzer v2.2.1 环境检测和依赖安装脚本
检测所有必要和可选依赖
"""

import subprocess
import sys
import shutil


def _parse_ffmpeg_encoder_names(raw_output: str) -> set[str]:
    encoders = set()
    for line in (raw_output or "").splitlines():
        parts = line.split()
        if len(parts) >= 2 and len(parts[0]) == 6:
            encoders.add(parts[1])
    return encoders


def _parse_ffmpeg_hwaccels(raw_output: str) -> set[str]:
    hwaccels = set()
    for line in (raw_output or "").splitlines():
        value = line.strip()
        if not value or value.endswith(":") or " " in value:
            continue
        hwaccels.add(value)
    return hwaccels


def check_command(cmd: str, version_arg: str = "--version") -> tuple:
    """检查命令行工具是否可用"""
    try:
        result = subprocess.run(
            [cmd, version_arg],
            capture_output=True,
            text=True,
            timeout=10
        )
        version = result.stdout.strip() or result.stderr.strip()
        return True, version.split('\n')[0]
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False, ""

def check_python_package(package: str) -> bool:
    """检查 Python 包是否已安装"""
    try:
        __import__(package)
        return True
    except ImportError:
        return False

def main():
    print("=" * 55)
    print("🔍 Video Expert Analyzer v2.2.1 环境检测")
    print("=" * 55)
    print()
    
    all_ok = True
    missing_cmds = []
    missing_pips = []
    
    # ── 1. 系统工具 ──
    print("1️⃣  系统工具")
    
    # 检查 FFmpeg
    ok, version = check_command("ffmpeg", "-version")
    if ok:
        print(f"   ✅ ffmpeg: {version[:60]}")
        try:
            encoder_result = subprocess.run(
                ["ffmpeg", "-hide_banner", "-encoders"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            encoders = _parse_ffmpeg_encoder_names(f"{encoder_result.stdout}\n{encoder_result.stderr}")
            hwaccel_result = subprocess.run(
                ["ffmpeg", "-hide_banner", "-hwaccels"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            hwaccels = _parse_ffmpeg_hwaccels(f"{hwaccel_result.stdout}\n{hwaccel_result.stderr}")
            import platform

            preferred_encoder = {
                "Windows": "h264_nvenc",
                "Darwin": "h264_videotoolbox",
            }.get(platform.system())
            preferred_hwaccel = {
                "Windows": ("d3d11va", "dxva2"),
                "Darwin": ("videotoolbox",),
            }.get(platform.system(), ())
            if preferred_encoder and preferred_encoder in encoders:
                print(f"   ✅ 场景切片硬件编码可用: {preferred_encoder}")
            elif preferred_encoder:
                print(f"   ⚠️  场景切片硬件编码未就绪，将回退 CPU: {preferred_encoder}")
            if preferred_hwaccel:
                matched_hwaccel = next((name for name in preferred_hwaccel if name in hwaccels), "")
                if matched_hwaccel:
                    print(f"   ✅ 抽帧/拆片可尝试硬件解码: {matched_hwaccel}")
                else:
                    print(f"   ⚠️  未检测到优先硬件解码能力，将使用软件解码")
        except Exception:
            print("   ⚠️  无法检测硬件编解码能力，运行时会自动回退")
    else:
        print(f"   ❌ ffmpeg 未安装 → brew install ffmpeg / 下载 FFmpeg")
        all_ok = False
    
    # 检查 yt-dlp (支持多种调用方式)
    ok, version = False, ""
    
    # 方法1: 直接命令
    try:
        result = subprocess.run(["yt-dlp", "--version"], capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            ok, version = True, result.stdout.strip()
    except:
        pass
    
    # 方法2: 通过 py -m 调用
    if not ok:
        try:
            result = subprocess.run([sys.executable, "-m", "yt_dlp", "--version"], capture_output=True, text=True, timeout=10)
            if result.returncode == 0:
                ok, version = True, result.stdout.strip()
        except:
            pass
    
    if ok:
        print(f"   ✅ yt-dlp: {version}")
    else:
        print(f"   ❌ yt-dlp 未安装 → pip3 install yt-dlp")
        all_ok = False
    
    # ── 2. 核心 Python 依赖（必需） ──
    print("\n2️⃣  核心 Python 依赖（必需）")
    
    core_packages = {
        "scenedetect": "scenedetect[opencv]",
        "requests": "requests",
        "torch": "torch",
    }
    
    for import_name, pip_name in core_packages.items():
        if check_python_package(import_name):
            print(f"   ✅ {pip_name}")
        else:
            print(f"   ❌ {pip_name} 未安装")
            missing_pips.append(pip_name)
            all_ok = False
    
    # ── 3. 语音转录依赖（智能选择） ──
    print("\n3️⃣  语音转录 (智能选择)")

    import platform
    system = platform.system()
    print(f"   系统: {system}")

    if system == "Darwin":  # macOS
        print("   推荐: MLX Whisper (Apple Silicon 优化)")
        if check_python_package("mlx_whisper"):
            print("   ✅ mlx-whisper")
        else:
            print("   ⚠️  mlx-whisper 未安装 (推荐)")
            print("      安装: pip install mlx-whisper")
    else:  # Windows, Linux
        print("   推荐: FunASR (通用高性能)")

    # 检查 FunASR (所有系统都可用作备选)
    funasr_packages = {
        "funasr": "funasr",
        "modelscope": "modelscope",
    }

    for import_name, pip_name in funasr_packages.items():
        if check_python_package(import_name):
            print(f"   ✅ {pip_name}")
        else:
            print(f"   ❌ {pip_name} 未安装")
            missing_pips.append(pip_name)
            all_ok = False

    # 检查 torch
    if check_python_package("torch"):
        print("   ✅ torch")
    else:
        print("   ❌ torch 未安装")
        missing_pips.append("torch")
        all_ok = False

    # ── 4. 可选依赖 ──
    print("\n4️⃣  可选依赖")

    optional = {
        "openai": ("openai", "旧版 API 兼容（已弃用）"),
        "rapidocr_onnxruntime": ("rapidocr-onnxruntime", "画面文字 OCR 检测"),
    }

    for import_name, (pip_name, desc) in optional.items():
        if check_python_package(import_name):
            print(f"   ✅ {pip_name} ({desc})")
        else:
            print(f"   ⚠️  {pip_name} 未安装 ({desc}) → pip3 install {pip_name}")

    # ── 5. GPU 加速 ──
    print("\n5️⃣  GPU 加速")
    try:
        import torch
        if torch.cuda.is_available():
            print(f"   ✅ CUDA: {torch.cuda.get_device_name(0)}")
        elif hasattr(torch.backends, 'mps') and torch.backends.mps.is_available():
            print(f"   ✅ Apple MPS (Metal) 可用")
        else:
            print("   ⚠️  无 GPU 加速，将使用 CPU（转录可能较慢）")
    except ImportError:
        print("   ⚠️  PyTorch 未安装，无法检测 GPU")
    
    # ── 结果汇总 ──
    print()
    print("=" * 55)
    
    if all_ok:
        print("✅ 所有核心依赖已满足！可以开始使用 Video Expert Analyzer。")
        print()
        print("快速开始：")
        print("  python3 scripts/pipeline_enhanced.py --setup")
        print("  python3 scripts/pipeline_enhanced.py <视频URL>")
    else:
        print("❌ 存在缺失依赖，请执行以下命令安装：")
        print()
        if missing_pips:
            print(f"  pip3 install {' '.join(missing_pips)}")
        for cmd in missing_cmds:
            print(f"  {cmd}")
        print()
        print("或一键安装所有依赖：")
        print("  pip3 install -r requirements.txt")
    
    print("=" * 55)
    return 0 if all_ok else 1

if __name__ == "__main__":
    sys.exit(main())
