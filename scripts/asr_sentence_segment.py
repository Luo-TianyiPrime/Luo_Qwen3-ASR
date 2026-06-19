#!/usr/bin/env python
"""
离线音频 -> Qwen3-ASR 转写+对齐 -> 句子级切分 -> 每句导出 wav/txt/index.jsonl
"""

from __future__ import annotations

import argparse
import gc
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import traceback
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import soundfile as sf
from shared import project_root, read_split_defaults

logger = logging.getLogger("qwen3_asr")
if not logger.handlers:
    logger.addHandler(logging.StreamHandler(sys.stdout))
logger.setLevel(logging.INFO)
logger.propagate = False


# 下面这几个默认值是“保守安全档”，优先保证 12GB 级别显卡不会被一次任务压到整机卡死。
# - CHUNK_SECONDS：每次只把一小段音频送进模型。块越短，峰值显存越低，但总块数会变多。
# - MAX_NEW_TOKENS：限制每块最多生成多少 token。token 可以粗略理解为模型内部的“文字小片段”，
#   上限越高，模型越不容易截断长句，但 KV 缓存越大、越吃显存，也更容易在异常音频上长时间生成。
# - MIN_CUDA_FREE_GB：启动 GPU 推理前要求至少有多少空闲显存；不够就直接报错，避免 Windows 桌面一起卡死。
DEFAULT_CHUNK_SECONDS = 60.0
DEFAULT_MAX_NEW_TOKENS = 1024
DEFAULT_MIN_CUDA_FREE_GB = 9.5


class GpuSafetyPrecheckError(RuntimeError):
    """GPU 空闲显存低于安全线时抛出，用来阻止任务继续把桌面拖卡。"""


# 贪心分句使用的边界集合。
STRONG_BOUNDARIES = {"。", "！", "？", "?", "!", "."}
SOFT_BOUNDARIES = {"，", ",", "；", ";"}
COMMON_PUNCTS = STRONG_BOUNDARIES | SOFT_BOUNDARIES | {
    "：",
    ":",
    "、",
    "“",
    "”",
    '"',
    "‘",
    "’",
    "'",
    "（",
    "）",
    "(",
    ")",
    "【",
    "】",
    "[",
    "]",
    "<",
    ">",
    "—",
    "-",
}

# 标点清理映射表：
# - 左边是常见的半角英文标点，右边是中文语音转写里更自然的全角标点。
# - 这里只做“标点符号形态”的规范化，不改任何汉字、英文或数字。
# - 这样可以避免出现中英文标点混排导致的 `，,`、`?.` 这类看起来很怪的结果。
PUNCT_NORMALIZE_MAP = {
    ",": "，",
    ";": "；",
    "?": "？",
    "!": "！",
    ".": "。",
    ":": "：",
    "(": "（",
    ")": "）",
}

@dataclass
class CharStamp:
    char: str
    start: float
    end: float


def to_float(value: Any, default: float | None = None) -> float | None:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def log(msg: str) -> None:
    """项目统一的日志输出入口。"""
    logger.info(msg)


def format_seconds_short(seconds: float) -> str:
    s = max(0, int(round(seconds)))
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    if h > 0:
        return f"{h}h{m:02d}m{sec:02d}s"
    if m > 0:
        return f"{m}m{sec:02d}s"
    return f"{sec}s"


def get_field(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def safe_filename_from_text(text: str, max_len: int = 80) -> str:
    """将识别文本转换为适合 Windows 的文件名主体。"""
    raw = (text or "").strip()
    if not raw:
        return "segment"

    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', " ", raw)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .")

    if not cleaned:
        cleaned = "segment"

    if len(cleaned) > max_len:
        cleaned = cleaned[:max_len].rstrip(" .")
        if not cleaned:
            cleaned = "segment"
    return cleaned


def segment_basename(idx: int, text: str, max_preview_len: int = 48) -> str:
    """生成稳定、可排序、可追踪的分段文件名主体。"""
    preview = safe_filename_from_text(text, max_len=max_preview_len)
    return f"seg_{idx:04d}__{preview}"


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def default_out_dir() -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return project_root() / "outputs" / f"run_{stamp}"


def normalize_language(language: str) -> str | None:
    if language is None:
        return None
    v = language.strip().lower()
    if v in {"", "none", "auto", "null"}:
        return None
    return language


def qwen3_tts_language_label(language: str) -> str:
    normalized = normalize_language(language)
    if normalized is None:
        return "Auto"
    return str(normalized).strip() or "Auto"


def validate_wav_output(wav_path: Path, purpose: str) -> None:
    if not wav_path.exists():
        raise RuntimeError(f"{purpose}输出无效，可能是 ffmpeg 或磁盘写入异常：未生成输出文件 {wav_path}")

    file_size = wav_path.stat().st_size
    if file_size <= 44:
        raise RuntimeError(
            f"{purpose}输出无效，可能是 ffmpeg 或磁盘写入异常：输出文件过小 {wav_path}（{file_size} 字节）"
        )

    try:
        info = sf.info(str(wav_path))
    except Exception as exc:
        raise RuntimeError(
            f"{purpose}输出无效，可能是 ffmpeg 或磁盘写入异常：输出文件无法被音频库读取 {wav_path}"
        ) from exc

    if info.frames <= 0 or info.samplerate <= 0 or info.channels <= 0:
        raise RuntimeError(
            f"{purpose}输出无效，可能是 ffmpeg 或磁盘写入异常：没有有效音频数据 {wav_path}"
        )


def ffmpeg_convert_to_wav16k_mono(src_audio: Path, dst_wav: Path) -> None:
    if not src_audio.exists():
        raise FileNotFoundError(f"输入音频不存在: {src_audio}")

    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(src_audio),
        "-vn",
        "-sn",
        "-dn",
        "-ac",
        "1",
        "-ar",
        "16000",
        str(dst_wav),
    ]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=True,
        )
        _ = proc.stdout
    except FileNotFoundError as exc:
        raise RuntimeError("未找到 ffmpeg，请先安装并确保 ffmpeg 在 PATH 中。") from exc
    except subprocess.CalledProcessError as exc:
        msg = (exc.stderr or "").strip()
        raise RuntimeError(f"ffmpeg 转码失败: {msg[-500:]}") from exc
    validate_wav_output(dst_wav, "转码")


def get_wav_duration_seconds(wav_path: Path) -> float:
    info = sf.info(str(wav_path))
    if info.samplerate <= 0:
        return 0.0
    return float(info.frames) / float(info.samplerate)


def probe_audio_stream_info(src_audio: Path) -> tuple[int, int]:
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "a:0",
        "-show_entries",
        "stream=sample_rate,channels",
        "-of",
        "json",
        str(src_audio),
    ]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=True,
        )
    except FileNotFoundError as exc:
        raise RuntimeError("未找到 ffprobe，请先安装 ffmpeg 并确保 ffprobe 在 PATH 中。") from exc
    except subprocess.CalledProcessError as exc:
        msg = (exc.stderr or "").strip()
        raise RuntimeError(f"ffprobe 读取音频信息失败: {msg[-500:]}") from exc

    try:
        data = json.loads(proc.stdout or "{}")
        streams = data.get("streams") or []
        if not streams:
            raise ValueError("no audio streams")
        st = streams[0]
        sr = int(st.get("sample_rate"))
        ch = int(st.get("channels"))
        if sr <= 0 or ch <= 0:
            raise ValueError("invalid sample rate/channels")
        return sr, ch
    except Exception as exc:
        raise RuntimeError("无法解析输入音频的采样率/声道信息。") from exc


def ffmpeg_export_segment_from_source(
    src_audio: Path,
    dst_wav: Path,
    start: float,
    end: float,
    sample_rate: int,
    channels: int,
) -> None:
    if end <= start:
        raise ValueError("segment end time must be greater than start time")

    cmd = [
        "ffmpeg",
        "-y",
        "-ss",
        f"{start:.3f}",
        "-to",
        f"{end:.3f}",
        "-i",
        str(src_audio),
        "-vn",
        "-sn",
        "-dn",
        "-map",
        "0:a:0",
        "-ac",
        str(channels),
        "-ar",
        str(sample_rate),
        "-c:a",
        "pcm_s16le",
        str(dst_wav),
    ]
    try:
        subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=True,
        )
    except FileNotFoundError as exc:
        raise RuntimeError("未找到 ffmpeg，请先安装并确保 ffmpeg 在 PATH 中。") from exc
    except subprocess.CalledProcessError as exc:
        msg = (exc.stderr or "").strip()
        raise RuntimeError(f"导出切片失败: {msg[-500:]}") from exc
    validate_wav_output(dst_wav, "切片")


def quiet_transformers_logging() -> None:
    # 减少长任务中的重复生成日志。
    os.environ.setdefault("TRANSFORMERS_VERBOSITY", "error")
    try:
        from transformers.utils import logging as hf_logging

        hf_logging.set_verbosity_error()
    except ImportError:
        pass


def pick_device_and_dtype(force_cpu: bool = False) -> tuple[str, Any]:
    import torch

    if not force_cpu and torch.cuda.is_available():
        device = "cuda:0"
        if hasattr(torch.cuda, "is_bf16_supported") and torch.cuda.is_bf16_supported():
            dtype = torch.bfloat16
        else:
            dtype = torch.float16
        return device, dtype
    return "cpu", torch.float32


def format_gib(num_bytes: int | float) -> str:
    """把字节数格式化成人更容易看懂的 GiB。"""
    return f"{float(num_bytes) / (1024.0**3):.2f} GiB"


def get_cuda_memory_info() -> tuple[int, int] | None:
    """返回当前 CUDA 设备的空闲显存和总显存，单位是字节；没有 CUDA 时返回 None。"""
    try:
        proc = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=memory.free,memory.total",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=5,
            check=True,
        )
        first_line = (proc.stdout or "").strip().splitlines()[0]
        free_mib, total_mib = [int(part.strip()) for part in first_line.split(",")[:2]]
        return free_mib * 1024 * 1024, total_mib * 1024 * 1024
    except Exception:
        pass

    try:
        import torch

        if not torch.cuda.is_available():
            return None
        device_index = torch.cuda.current_device()
        free_bytes, total_bytes = torch.cuda.mem_get_info(device_index)
        return int(free_bytes), int(total_bytes)
    except Exception:
        return None


def ensure_enough_cuda_memory(min_free_gb: float, force_cpu: bool = False) -> None:
    """在加载大模型前做一次显存预检，避免显存不足时把 Windows 桌面一起拖卡。"""
    if force_cpu or min_free_gb <= 0:
        return

    info = get_cuda_memory_info()
    if info is None:
        return

    free_bytes, total_bytes = info
    min_free_bytes = int(float(min_free_gb) * (1024**3))
    log(f"CUDA 显存预检: 空闲 {format_gib(free_bytes)} / 总计 {format_gib(total_bytes)}")
    if free_bytes >= min_free_bytes:
        return

    raise GpuSafetyPrecheckError(
        "显存不足：当前 CUDA 空闲显存只有 "
        f"{format_gib(free_bytes)}，低于本项目的安全线 {float(min_free_gb):.1f} GiB。\n"
        "原因解释：Qwen3-ASR 主模型、ForcedAligner 对齐模型、音频特征和生成 KV 缓存会一起占显存；"
        "在 Windows 上显存被挤满时，桌面渲染也会受影响，所以会表现为整机卡死。\n"
        "你现在可以这样做：关闭 ComfyUI、浏览器、游戏、视频播放器等占显存程序后重试；"
        "或者把 MinCudaFreeGB 调低/设为 0 关闭预检；如果只是想验证流程，可以启用 ForceCpu。"
    )


def load_qwen_asr_model(
    asr_ckpt: str,
    aligner_ckpt: str,
    max_new_tokens: int,
    batch_size: int,
    force_cpu: bool = False,
) -> Any:
    from qwen_asr import Qwen3ASRModel

    device, dtype = pick_device_and_dtype(force_cpu=force_cpu)
    requested_batch_size = max(1, int(batch_size or 1))
    common_kwargs = {
        "dtype": dtype,
        "device_map": device,
        "low_cpu_mem_usage": True,
        "forced_aligner": aligner_ckpt,
        "forced_aligner_kwargs": {
            "dtype": dtype,
            "device_map": device,
            "low_cpu_mem_usage": True,
        },
    }

    try:
        model = Qwen3ASRModel.from_pretrained(
            asr_ckpt,
            max_inference_batch_size=requested_batch_size,
            max_new_tokens=max_new_tokens,
            **common_kwargs,
        )
    except TypeError:
        # 兼容不同 qwen-asr 版本的参数签名。
        try:
            model = Qwen3ASRModel.from_pretrained(
                asr_ckpt,
                max_inference_batch_size=requested_batch_size,
                **common_kwargs,
            )
        except TypeError:
            model = Qwen3ASRModel.from_pretrained(
                asr_ckpt,
                **common_kwargs,
            )

    return model


def is_memory_pressure_error(exc: BaseException) -> bool:
    message = str(exc)
    lowered = message.lower()
    return (
        "cuda out of memory" in lowered
        or "out of memory" in lowered
        or "显存不足" in message
        or "cannot allocate memory" in lowered
    )


def clear_cuda_cache() -> None:
    gc.collect()
    try:
        import torch

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            if hasattr(torch.cuda, "ipc_collect"):
                try:
                    torch.cuda.ipc_collect()
                except (RuntimeError, AttributeError):
                    pass
    except ImportError:
        pass


def clear_exception_frames(exc: BaseException) -> None:
    """清理异常回溯里保留的局部变量，帮助 CUDA 张量和模型引用尽快释放。"""
    try:
        traceback.clear_frames(exc.__traceback__)
    except Exception:
        pass


def timestamp_items(value: Any) -> list[Any]:
    """兼容 qwen-asr 返回的 ForcedAlignResult 或普通 list/dict 时间戳结构。"""
    if value is None:
        return []
    if isinstance(value, dict):
        return [value]
    if hasattr(value, "items") and not isinstance(value, dict):
        try:
            return list(value.items)
        except TypeError:
            pass
    try:
        return list(value)
    except TypeError:
        return []


def split_wav_for_asr(wav_path: Path, chunk_seconds: float) -> list[tuple[Any, int, float, float]]:
    """把 16k 单声道 wav 切成较小推理块，返回 (音频数组, 采样率, 起点秒, 时长秒)。"""
    import numpy as np

    safe_chunk_seconds = max(5.0, float(chunk_seconds or DEFAULT_CHUNK_SECONDS))
    audio, sample_rate = sf.read(str(wav_path), dtype="float32", always_2d=False)
    audio_array = np.asarray(audio, dtype=np.float32)
    if audio_array.ndim == 2:
        audio_array = np.mean(audio_array, axis=-1).astype(np.float32)

    if audio_array.size == 0:
        return []

    try:
        from qwen_asr.inference.utils import split_audio_into_chunks

        parts = split_audio_into_chunks(
            wav=audio_array,
            sr=int(sample_rate),
            max_chunk_sec=safe_chunk_seconds,
        )
    except Exception:
        # qwen-asr 自带的切分会尽量找低能量边界；如果它不可用，就退回固定长度切块。
        chunk_len = max(1, int(round(safe_chunk_seconds * int(sample_rate))))
        parts = []
        start = 0
        while start < int(audio_array.shape[0]):
            end = min(int(audio_array.shape[0]), start + chunk_len)
            parts.append((audio_array[start:end], start / float(sample_rate)))
            start = end

    out: list[tuple[Any, int, float, float]] = []
    for chunk, offset_sec in parts:
        chunk_array = np.asarray(chunk, dtype=np.float32)
        duration_sec = float(chunk_array.shape[0]) / float(sample_rate) if sample_rate else 0.0
        out.append((chunk_array, int(sample_rate), float(offset_sec), duration_sec))
    return out


def merge_language_labels(labels: Sequence[str | None]) -> str | None:
    """合并分块识别到的语言标签，连续重复的标签只保留一次。"""
    merged: list[str] = []
    previous = ""
    for item in labels:
        label = str(item or "").strip()
        if not label or label == previous:
            continue
        merged.append(label)
        previous = label
    return ",".join(merged) if merged else None


def transcribe_with_timestamps(
    model: Any,
    wav_path: Path,
    language: str | None,
    context: str = "",
    wav_duration_sec: float = 0.0,
    chunk_seconds: float = DEFAULT_CHUNK_SECONDS,
    progress_interval_sec: int = 30,
    eta_rtf: float = 2.0,
) -> tuple[str, Sequence[Any], str | None]:
    start_ts = time.time()
    done = threading.Event()
    safe_rtf = max(0.05, float(eta_rtf))
    expected_total = max(5.0, float(wav_duration_sec) / safe_rtf)
    log(
        "步骤 3/5 预计总耗时 ~"
        f"{format_seconds_short(expected_total)} "
        f"(估算速度 {safe_rtf:.2f}x 实时，仅供参考)"
    )

    def heartbeat() -> None:
        while not done.wait(progress_interval_sec):
            elapsed = float(time.time() - start_ts)
            remaining = max(0.0, expected_total - elapsed)
            progress = min(99.0, (elapsed / expected_total) * 100.0)
            log(
                "步骤 3/5 仍在运行... 已耗时 "
                f"{format_seconds_short(elapsed)} | "
                f"预计剩余 ~{format_seconds_short(remaining)} | "
                f"进度约 {progress:.0f}%"
            )

    t = threading.Thread(target=heartbeat, daemon=True)
    t.start()
    chunk_rows = split_wav_for_asr(wav_path, chunk_seconds=chunk_seconds)
    total_chunks = len(chunk_rows)
    log(f"步骤 3/5: 音频已切成 {total_chunks} 块，每块最长约 {float(chunk_seconds):.0f} 秒")
    all_text: list[str] = []
    all_timestamps: list[dict[str, Any]] = []
    detected_languages: list[str | None] = []
    try:
        for index, (chunk_wav, sample_rate, offset_sec, duration_sec) in enumerate(chunk_rows, start=1):
            chunk_progress = int(round(((index - 1) / max(1, total_chunks)) * 100.0))
            log(
                f"步骤 3/5 分块 [{index}/{total_chunks}] 开始 ASR+对齐，"
                f"音频位置 {format_seconds_short(offset_sec)}~{format_seconds_short(offset_sec + duration_sec)}，"
                f"进度约 {chunk_progress}%"
            )
            result = model.transcribe(
                audio=(chunk_wav, sample_rate),
                language=language,
                context=context or "",
                return_time_stamps=True,
            )
            first = result[0] if isinstance(result, (list, tuple)) else result
            chunk_text = str(get_field(first, "text", "") or "")
            chunk_time_stamps = get_field(first, "time_stamps", None)
            chunk_language = get_field(first, "language", None)
            detected_languages.append(str(chunk_language) if chunk_language else None)

            if not chunk_time_stamps:
                if chunk_text.strip():
                    raise RuntimeError(
                        "未拿到 time_stamps。请确认 forced aligner 模型可用，并使用 Qwen3-ForcedAligner。"
                    )
                log(f"步骤 3/5 分块 [{index}/{total_chunks}] 未识别到有效语音，已跳过")
                clear_cuda_cache()
                continue

            all_text.append(chunk_text)
            for item in timestamp_items(chunk_time_stamps):
                text_item = str(get_field(item, "text", "") or "")
                start_item = to_float(get_field(item, "start_time", get_field(item, "start", None)))
                end_item = to_float(get_field(item, "end_time", get_field(item, "end", None)))
                if not text_item or start_item is None or end_item is None:
                    continue
                all_timestamps.append(
                    {
                        "text": text_item,
                        "start_time": round(float(start_item) + offset_sec, 3),
                        "end_time": round(float(end_item) + offset_sec, 3),
                    }
                )
            done_progress = int(round((index / max(1, total_chunks)) * 100.0))
            log(f"步骤 3/5 分块 [{index}/{total_chunks}] 完成，进度约 {done_progress}%")
            clear_cuda_cache()
    finally:
        done.set()
        t.join(timeout=0.1)

    elapsed = float(time.time() - start_ts)
    speed_x = (float(wav_duration_sec) / elapsed) if elapsed > 0 else 0.0
    log(
        "步骤 3/5 完成，用时 "
        f"{format_seconds_short(elapsed)} "
        f"(约 {speed_x:.2f}x 实时)"
    )
    return "".join(all_text), all_timestamps, merge_language_labels(detected_languages)


def parse_unit_timestamps(time_stamps: Sequence[Any]) -> list[tuple[str, float, float]]:
    units: list[tuple[str, float, float]] = []
    for item in time_stamps:
        text = str(get_field(item, "text", "") or "")
        if not text:
            continue
        start = to_float(get_field(item, "start_time", get_field(item, "start", None)))
        end = to_float(get_field(item, "end_time", get_field(item, "end", None)))
        if start is None or end is None:
            continue
        if end < start:
            continue
        units.append((text, start, end))
    units.sort(key=lambda x: (x[1], x[2]))
    return units


def expand_units_to_char_timeline(units: Sequence[tuple[str, float, float]]) -> list[CharStamp]:
    timeline: list[CharStamp] = []
    for text, start, end in units:
        chars = list(text)
        if not chars:
            continue
        total = max(end - start, 1e-6)
        n = len(chars)
        # Qwen3 的 unit.text 可能包含多个字符，这里按字符均分时间。
        for i, ch in enumerate(chars):
            c_start = start + total * (i / n)
            c_end = start + total * ((i + 1) / n)
            timeline.append(CharStamp(char=ch, start=float(c_start), end=float(c_end)))
    return timeline


def extract_text_from_punc_result(obj: Any) -> str | None:
    if obj is None:
        return None
    if isinstance(obj, str):
        return obj
    if isinstance(obj, dict):
        text = obj.get("text")
        if isinstance(text, str):
            return text
        if "value" in obj and isinstance(obj["value"], str):
            return obj["value"]
        return None
    if isinstance(obj, list) and obj:
        for item in obj:
            text = extract_text_from_punc_result(item)
            if text:
                return text
    return None


def normalize_punctuation_text(text: str) -> str:
    """
    只清理“标点表现形式”，不碰正文。

    说明给新手：
    - ASR 主模型负责“听音频并识别出字”。
    - 标点模型只应该负责“在已有文字里插入逗号、句号、问号等符号”。
    - 如果标点模型把字改了，那就不再是标点恢复，而是改写正文，会破坏后续时间线对齐。

    这里做的事情很保守：
    1. 把常见英文标点换成中文标点，例如 `,` -> `，`。
    2. 删除标点前后的多余空格，避免出现 `你好 ， 世界`。
    3. 连续重复的标点只保留一个，避免出现 `，，`、`！！`。
    4. 不修改汉字、英文、数字本身。
    """
    normalized_chars: list[str] = []
    previous_punct = ""

    for raw_ch in text or "":
        if raw_ch.isspace():
            # 中文转写通常不需要空格；保留空格反而会干扰字符级时间线。
            continue

        ch = PUNCT_NORMALIZE_MAP.get(raw_ch, raw_ch)
        is_punct = ch in COMMON_PUNCTS

        if is_punct:
            if normalized_chars and normalized_chars[-1] == ch:
                # 相同标点连续出现，大概率是标点模型抖动，直接去重。
                continue
            if previous_punct and previous_punct in SOFT_BOUNDARIES and ch in STRONG_BOUNDARIES:
                # `，。`、`，？` 这类组合只保留后面的强标点。
                normalized_chars.pop()
            normalized_chars.append(ch)
            previous_punct = ch
            continue

        normalized_chars.append(ch)
        previous_punct = ""

    return "".join(normalized_chars).strip()


def text_without_punctuation(text: str) -> str:
    """
    去掉空白和标点后保留正文，用来检查标点模型有没有改字。

    举例：
    - 原文：`大家好欢迎回来`
    - 合法标点结果：`大家好，欢迎回来。`
    - 两者去掉标点后都是：`大家好欢迎回来`

    如果去掉标点后正文不一样，说明标点模型不只是加标点，而是改字/漏字/重排。
    这种结果不能用于切音频，否则文本和 wav 时间段可能对不上。
    """
    normalized = normalize_punctuation_text(text)
    return "".join(ch for ch in normalized if ch not in COMMON_PUNCTS and not ch.isspace())


def validate_punctuation_text(raw_text: str, punc_text: str) -> str:
    """
    校验标点模型输出是否安全。

    返回值是清理后的标点文本。
    如果标点模型改动了正文，直接抛错，让主流程回退到 ASR 原始文本。
    这比“勉强对齐”安全得多，因为错误对齐会导致 txt 写一段、wav 却切另一段。
    """
    cleaned = normalize_punctuation_text(punc_text)
    raw_body = text_without_punctuation(raw_text)
    punc_body = text_without_punctuation(cleaned)

    if raw_body != punc_body:
        raise ValueError(
            "标点模型输出修改了正文，已拒绝使用该标点结果，避免文本和音频错位。"
            f" 原正文长度={len(raw_body)}，标点后正文长度={len(punc_body)}"
        )

    return cleaned if cleaned else raw_text


def apply_punctuation(raw_text: str, punc_model_name: str) -> str:
    try:
        from funasr import AutoModel
    except ModuleNotFoundError as exc:
        raise RuntimeError("缺少 funasr。请先运行 .\\bootstrap.ps1 -InstallFunASR，安装完成后再启用标点恢复。") from exc

    try:
        # disable_update=True 只关闭 FunASR 的“启动时检查新版”行为，不影响标点模型本身的下载和推理。
        # 这样做可以减少每次任务启动时的联网检查时间；如果旧版 FunASR 不支持该参数，就回退到兼容写法。
        # 标点模型只处理文字，不需要占用 GPU；固定到 CPU 可以避免它继续挤占 12GB 显卡的显存。
        model = AutoModel(model=punc_model_name, disable_update=True, device="cpu")
    except TypeError:
        try:
            model = AutoModel(model=punc_model_name, device="cpu")
        except TypeError:
            model = AutoModel(model=punc_model_name)
    output = model.generate(input=raw_text)
    text = extract_text_from_punc_result(output)
    return validate_punctuation_text(raw_text, text) if text else raw_text


def merge_punc_text_to_timeline(raw_timeline: Sequence[CharStamp], punc_text: str) -> list[CharStamp]:
    if not raw_timeline:
        return []

    merged: list[CharStamp] = []
    i = 0

    for ch in normalize_punctuation_text(punc_text):
        if ch.isspace():
            continue

        if ch in COMMON_PUNCTS:
            # 标点没有真实语音时长：如果原始时间线当前位置本身也是标点，就复用它的时间；
            # 否则把新增标点挂到前一个字的结束点。这样不会让标点凭空拉长音频片段。
            if i < len(raw_timeline) and raw_timeline[i].char in COMMON_PUNCTS:
                ref = raw_timeline[i]
                merged.append(CharStamp(ch, ref.start, ref.end))
                i += 1
            elif merged:
                t = merged[-1].end
                merged.append(CharStamp(ch, t, t))
            elif i < len(raw_timeline):
                t = raw_timeline[i].start
                merged.append(CharStamp(ch, t, t))
            else:
                merged.append(CharStamp(ch, 0.0, 0.0))
            continue

        # 标点模型通过 validate_punctuation_text() 之后，正文字符顺序必须和原始 ASR 一致。
        # 因此这里不再做“猜测式纠偏”，否则一旦模型改字，就会把错误文本硬塞到别的时间戳上。
        while i < len(raw_timeline) and (raw_timeline[i].char in COMMON_PUNCTS or raw_timeline[i].char.isspace()):
            i += 1

        if i >= len(raw_timeline) or raw_timeline[i].char != ch:
            raise ValueError(
                "标点文本无法安全合并到时间线，已拒绝使用该标点结果，避免文本和音频错位。"
            )

        ref = raw_timeline[i]
        merged.append(CharStamp(ch, ref.start, ref.end))
        i += 1

    return merged if merged else list(raw_timeline)


def collect_pause_edges(timeline: Sequence[CharStamp], pause_threshold: float) -> set[int]:
    edges: set[int] = set()
    for i in range(len(timeline) - 1):
        gap = timeline[i + 1].start - timeline[i].end
        if gap >= pause_threshold:
            edges.add(i)
    return edges


def greedy_sentence_split(
    timeline: Sequence[CharStamp],
    audio_duration: float,
    pause_threshold: float,
    min_dur: float,
    max_dur: float,
    pad_left: float,
    pad_right: float,
) -> list[dict]:
    if not timeline:
        return []

    pause_edges = collect_pause_edges(timeline, pause_threshold)
    n = len(timeline)
    i = 0
    chunks: list[dict] = []

    while i < n:
        start_t = timeline[i].start
        max_end_t = start_t + max_dur
        hard_end = i
        while hard_end + 1 < n and timeline[hard_end + 1].end <= max_end_t:
            hard_end += 1

        strong_candidates: list[int] = []
        soft_candidates: list[int] = []
        pause_candidates: list[int] = []

        for j in range(i, hard_end + 1):
            cur_dur = timeline[j].end - start_t
            if cur_dur < min_dur:
                continue
            ch = timeline[j].char
            if ch in STRONG_BOUNDARIES:
                strong_candidates.append(j)
            elif ch in SOFT_BOUNDARIES:
                soft_candidates.append(j)
            if j in pause_edges:
                pause_candidates.append(j)

        # 贪心策略：强边界 > 软边界 > 停顿边界 > 硬切。
        if strong_candidates:
            end_idx = strong_candidates[-1]
        elif soft_candidates:
            end_idx = soft_candidates[-1]
        elif pause_candidates:
            end_idx = pause_candidates[-1]
        else:
            end_idx = hard_end
            # 片段太短时继续延长，直到满足最小时长。
            while end_idx + 1 < n and (timeline[end_idx].end - start_t) < min_dur:
                end_idx += 1

        if end_idx < i:
            end_idx = i

        text = "".join(c.char for c in timeline[i : end_idx + 1]).strip()
        seg_start = max(0.0, timeline[i].start - pad_left)
        seg_end = min(audio_duration, timeline[end_idx].end + pad_right)

        if text and seg_end > seg_start:
            chunks.append(
                {
                    "char_start_idx": i,
                    "char_end_idx": end_idx,
                    "start": float(seg_start),
                    "end": float(seg_end),
                    "text": text,
                }
            )

        i = end_idx + 1

    # 收尾：如果最后一段过短，合并到前一段，减少碎片。
    if len(chunks) >= 2:
        last = chunks[-1]
        if (last["end"] - last["start"]) < max(0.3, min_dur * 0.6):
            prev = chunks[-2]
            prev["end"] = last["end"]
            prev["char_end_idx"] = last["char_end_idx"]
            prev["text"] = (prev["text"] + last["text"]).strip()
            chunks.pop()

    return chunks


def write_segments_and_index(
    source_audio: Path,
    segments: Sequence[dict],
    out_dir: Path,
) -> list[dict[str, Any]]:
    seg_dir = out_dir / "segments"
    ensure_dir(seg_dir)
    sample_rate, channels = probe_audio_stream_info(source_audio)
    log(f"导出音频规格: {sample_rate} Hz / {channels} ch（与输入保持一致）")
    used_name_count: dict[str, int] = {}
    written_segments: list[dict[str, Any]] = []

    index_path = out_dir / "index.jsonl"
    with index_path.open("w", encoding="utf-8") as f_index:
        for idx, seg in enumerate(segments, start=1):
            start = float(seg["start"])
            end = float(seg["end"])
            text = str(seg["text"]).strip()
            if not text:
                continue

            if end <= start:
                continue

            # 文件名必须有稳定序号，不能只依赖识别文本。
            # 这样资源管理器、WebUI、后续数据集脚本按名称排序时，顺序仍然等于音频时间顺序。
            base = segment_basename(idx, text)
            n = used_name_count.get(base, 0) + 1
            used_name_count[base] = n
            basename = base if n == 1 else f"{base}_{n}"

            wav_name = basename + ".wav"
            txt_name = basename + ".txt"

            wav_rel = Path("segments") / wav_name
            txt_rel = Path("segments") / txt_name
            wav_out = out_dir / wav_rel
            txt_out = out_dir / txt_rel

            ffmpeg_export_segment_from_source(
                src_audio=source_audio,
                dst_wav=wav_out,
                start=start,
                end=end,
                sample_rate=sample_rate,
                channels=channels,
            )
            txt_out.write_text(text + "\n", encoding="utf-8")
            written_text = txt_out.read_text(encoding="utf-8", errors="replace").strip()
            if written_text != text:
                raise RuntimeError(
                    f"分段文本写入校验失败：{txt_out}。"
                    "这表示 index.jsonl 里的文本和实际 txt 文件内容不一致，已停止导出。"
                )

            line = {
                "id": f"seg_{idx:04d}",
                "wav": wav_rel.as_posix(),
                "txt": txt_rel.as_posix(),
                "start": round(start, 3),
                "end": round(end, 3),
                "text": text,
            }
            f_index.write(json.dumps(line, ensure_ascii=False) + "\n")
            written_segments.append(
                {
                    **line,
                    "wav_path": wav_out,
                    "txt_path": txt_out,
                }
            )

    return written_segments


def export_qwen3_tts_manifest(
    exported_segments: Sequence[dict[str, Any]],
    out_dir: Path,
    ref_audio: str,
    language: str,
) -> Path:
    ref_audio_value = (ref_audio or "").strip()
    data_audio_dir = out_dir / "data" / "audio"
    ensure_dir(data_audio_dir)
    manifest_path = out_dir / "qwen3_tts.jsonl"
    ref_audio_rel = ""

    # 参考音频只是可选附加字段，不影响 ASR 主流程。
    # 不填写时，仍然导出可直接用于后续整理/微调的数据清单。
    if ref_audio_value:
        ref_audio_path = Path(ref_audio_value).expanduser().resolve()
        if not ref_audio_path.exists():
            raise FileNotFoundError(f"参考音频不存在: {ref_audio_path}")
        if not ref_audio_path.is_file():
            raise FileNotFoundError(f"参考音频不是文件: {ref_audio_path}")

        data_ref_dir = out_dir / "data" / "ref"
        ensure_dir(data_ref_dir)

        ref_copy_path = data_ref_dir / ref_audio_path.name
        if ref_audio_path != ref_copy_path:
            shutil.copy2(ref_audio_path, ref_copy_path)

        ref_audio_rel = (Path("data") / "ref" / ref_copy_path.name).as_posix()

    with manifest_path.open("w", encoding="utf-8") as handle:
        for idx, seg in enumerate(exported_segments, start=1):
            wav_src = Path(seg["wav_path"])
            utt_name = f"utt{idx:04d}.wav"
            wav_dst = data_audio_dir / utt_name
            shutil.copy2(wav_src, wav_dst)

            payload = {
                "audio": (Path("data") / "audio" / utt_name).as_posix(),
                "text": str(seg["text"]),
                "language": language,
            }
            if ref_audio_rel:
                payload["ref_audio"] = ref_audio_rel
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")

    return manifest_path


def parse_args() -> argparse.Namespace:
    split_defaults = read_split_defaults()
    parser = argparse.ArgumentParser(
        description="Qwen3-ASR + Qwen3-ForcedAligner sentence-level segmentation tool."
    )
    parser.add_argument("--audio", required=True, help="Input audio file path")
    parser.add_argument("--out_dir", default="", help="Output directory (auto if empty)")
    parser.add_argument(
        "--asr_ckpt",
        default="Qwen/Qwen3-ASR-1.7B",
        help="ASR model name or local path",
    )
    parser.add_argument(
        "--aligner_ckpt",
        default="Qwen/Qwen3-ForcedAligner-0.6B",
        help="Forced aligner model name or local path",
    )
    parser.add_argument(
        "--language",
        default="Chinese",
        help='Language, e.g. "Chinese"; use "None" for auto detect',
    )
    parser.add_argument(
        "--punc_model",
        default="",
        help="Optional punctuation model name",
    )
    parser.add_argument(
        "--pause_threshold",
        type=float,
        default=split_defaults["pause_threshold"],
        help="Pause split threshold (s)",
    )
    parser.add_argument("--min_dur", type=float, default=split_defaults["min_dur"], help="Minimum sentence duration (s)")
    parser.add_argument("--max_dur", type=float, default=split_defaults["max_dur"], help="Maximum sentence duration (s)")
    parser.add_argument("--pad_left", type=float, default=split_defaults["pad_left"], help="Left padding (s)")
    parser.add_argument("--pad_right", type=float, default=split_defaults["pad_right"], help="Right padding (s)")
    parser.add_argument("--max_new_tokens", type=int, default=DEFAULT_MAX_NEW_TOKENS, help="ASR max_new_tokens")
    parser.add_argument(
        "--batch_size",
        type=int,
        default=1,
        help="ASR 推理批大小。值越大通常越快，但显存占用也越高；保守值建议从 1 开始",
    )
    parser.add_argument(
        "--chunk_seconds",
        type=float,
        default=DEFAULT_CHUNK_SECONDS,
        help="ASR 安全分块时长，单位秒。值越小峰值显存越低，但分块数量会变多",
    )
    parser.add_argument(
        "--min_cuda_free_gb",
        type=float,
        default=DEFAULT_MIN_CUDA_FREE_GB,
        help="GPU 推理前要求的最低空闲显存，单位 GiB；设为 0 可关闭预检",
    )
    parser.add_argument(
        "--force_cpu",
        action="store_true",
        help="强制使用 CPU 推理。速度会慢很多，但可用于排查 GPU 显存问题",
    )
    parser.add_argument("--eta_rtf", type=float, default=2.0, help="ETA speed assumption (x realtime)")
    parser.add_argument(
        "--dataset_format",
        default="standard",
        choices=["standard", "qwen3_tts"],
        help="附加导出格式：standard 仅输出 index.jsonl；qwen3_tts 额外输出可用于 Qwen3-TTS 微调的 qwen3_tts.jsonl",
    )
    parser.add_argument(
        "--ref_audio",
        default="",
        help="可选。Qwen3-TTS 导出时写入 ref_audio 字段的参考音频路径；不填则导出不带 ref_audio 的清单",
    )
    parser.add_argument(
        "--hotword_file",
        default="",
        help="热词文件路径（每行一个词）。会转成识别上下文，帮助模型更稳定地识别专有名词",
    )
    return parser.parse_args()


def run_pipeline(args: argparse.Namespace, batch_size: int, force_cpu: bool = False) -> int:
    dataset_format = str(args.dataset_format or "standard").strip().lower()
    if batch_size < 1:
        raise ValueError("batch_size 必须是大于等于 1 的整数。")
    if int(args.max_new_tokens) < 64:
        raise ValueError("max_new_tokens 至少建议为 64；太小会导致识别文本被截断。")
    if float(args.chunk_seconds) < 5:
        raise ValueError("chunk_seconds 至少建议为 5 秒；太小会把一句话切得过碎，影响上下文。")
    if float(args.min_cuda_free_gb) < 0:
        raise ValueError("min_cuda_free_gb 不能为负数；设为 0 表示关闭显存预检。")

    audio_path = Path(args.audio).expanduser().resolve()
    out_dir = Path(args.out_dir).expanduser().resolve() if args.out_dir else default_out_dir()
    ensure_dir(out_dir)
    tmp_dir = out_dir / "_tmp"
    ensure_dir(tmp_dir)

    wav_path = tmp_dir / "input_16k_mono.wav"
    log(f"输入音频: {audio_path}")
    log(f"输出目录: {out_dir}")
    log(f"运行设备: {'CPU（已自动回退）' if force_cpu else '自动选择 CUDA / CPU'}")
    log("步骤 1/5: ffmpeg 转为 16k mono wav")
    ffmpeg_convert_to_wav16k_mono(audio_path, wav_path)
    wav_dur_sec = get_wav_duration_seconds(wav_path)
    log(f"音频时长: {wav_dur_sec / 60.0:.2f} 分钟")

    quiet_transformers_logging()
    log("步骤 2/5: 加载 Qwen3-ASR + ForcedAligner")
    log(f"ASR 批大小(batch_size): {batch_size}")
    log(f"ASR 安全分块(chunk_seconds): {float(args.chunk_seconds):.0f} 秒")
    log(f"ASR 最大生成(max_new_tokens): {int(args.max_new_tokens)}")
    ensure_enough_cuda_memory(min_free_gb=float(args.min_cuda_free_gb), force_cpu=force_cpu)
    clear_cuda_cache()
    model = None
    text = ""
    time_stamps: Sequence[Any] = []
    detected_lang: str | None = None
    try:
        model = load_qwen_asr_model(
            asr_ckpt=args.asr_ckpt,
            aligner_ckpt=args.aligner_ckpt,
            max_new_tokens=args.max_new_tokens,
            batch_size=batch_size,
            force_cpu=force_cpu,
        )

        hotword_context = ""
        hotword_file = str(args.hotword_file or "").strip()
        if hotword_file:
            hotword_path = Path(hotword_file).expanduser().resolve()
            if hotword_path.exists() and hotword_path.is_file():
                raw_lines = hotword_path.read_text(encoding="utf-8", errors="replace").strip()
                entries = [line.strip() for line in raw_lines.splitlines() if line.strip()]
                if entries:
                    hotword_context = "热词提示：" + "、".join(entries)
                    log(f"已加载 {len(entries)} 条热词作为识别上下文")
            else:
                log(f"热词文件不存在，忽略：{hotword_path}")

        log("步骤 3/5: 执行 ASR 并获取时间戳")
        text, time_stamps, detected_lang = transcribe_with_timestamps(
            model=model,
            wav_path=wav_path,
            language=normalize_language(args.language),
            context=hotword_context,
            wav_duration_sec=wav_dur_sec,
            chunk_seconds=float(args.chunk_seconds),
            progress_interval_sec=30,
            eta_rtf=float(args.eta_rtf),
        )
    finally:
        # ASR 完成后马上释放 Qwen3-ASR + ForcedAligner，避免后面的标点模型和导出步骤继续占着显存。
        if model is not None:
            del model
        clear_cuda_cache()
    log(f"识别语言: {detected_lang or 'unknown'}")

    warning_message = ""
    units = parse_unit_timestamps(time_stamps) if time_stamps else []
    if not text.strip() and not units:
        warning_message = "音频可能为静默、噪声过大，或未包含可识别语音，最终结果为空"
        log(f"警告: {warning_message}")
        char_timeline: list[CharStamp] = []
    else:
        if not units:
            raise RuntimeError("time_stamps 无可用 unit，无法切分。")

        char_timeline = expand_units_to_char_timeline(units)
        if not char_timeline:
            raise RuntimeError("字符级时间线为空，无法切分。")

    if char_timeline and args.punc_model.strip():
        log("步骤 4/5: 执行可选标点恢复")
        try:
            punc_text = apply_punctuation(text, args.punc_model.strip())
            char_timeline = merge_punc_text_to_timeline(char_timeline, punc_text)
            text = punc_text
        except Exception as exc:
            log(f"标点恢复失败，继续使用原始文本: {exc}")
    elif char_timeline:
        log("步骤 4/5: 跳过标点恢复（未设置 --punc_model）")
    else:
        log("步骤 4/5: 没有可导出的内容，跳过标点恢复")

    duration = float(wav_dur_sec)

    log("步骤 5/5: 贪心分句并导出片段")
    segments = greedy_sentence_split(
        timeline=char_timeline,
        audio_duration=duration,
        pause_threshold=float(args.pause_threshold),
        min_dur=float(args.min_dur),
        max_dur=float(args.max_dur),
        pad_left=float(args.pad_left),
        pad_right=float(args.pad_right),
    )
    if not segments and not warning_message:
        warning_message = "脚本运行成功，但没有得到可导出的语音片段。音频可能为静默、噪声过大，或未包含可识别语音。"
        log(f"警告: {warning_message}")
    exported_segments = write_segments_and_index(source_audio=audio_path, segments=segments, out_dir=out_dir)

    qwen3_tts_manifest_path: Path | None = None
    if dataset_format == "qwen3_tts":
        if str(args.ref_audio or "").strip():
            log("附加导出: 生成 Qwen3-TTS 微调清单（包含参考音频字段）")
        else:
            log("附加导出: 生成 Qwen3-TTS 微调清单（不包含参考音频字段）")
        qwen3_tts_manifest_path = export_qwen3_tts_manifest(
            exported_segments=exported_segments,
            out_dir=out_dir,
            ref_audio=args.ref_audio,
            language=qwen3_tts_language_label(args.language),
        )

    (out_dir / "full_text.txt").write_text(text.strip() + "\n", encoding="utf-8")
    (out_dir / "meta.json").write_text(
        json.dumps(
            {
                "audio": str(audio_path),
                "wav_16k_mono": str(wav_path),
                "asr_ckpt": args.asr_ckpt,
                "aligner_ckpt": args.aligner_ckpt,
                "language": args.language,
                "batch_size": batch_size,
                "requested_batch_size": int(args.batch_size),
                "chunk_seconds": float(args.chunk_seconds),
                "max_new_tokens": int(args.max_new_tokens),
                "min_cuda_free_gb": float(args.min_cuda_free_gb),
                "runtime_device": "cpu_fallback" if force_cpu else "auto",
                "detected_language": detected_lang,
                "punc_model": args.punc_model,
                "pause_threshold": args.pause_threshold,
                "min_dur": args.min_dur,
                "max_dur": args.max_dur,
                "pad_left": args.pad_left,
                "pad_right": args.pad_right,
                "eta_rtf": args.eta_rtf,
                "dataset_format": dataset_format,
                "ref_audio": args.ref_audio,
                "segments": len(segments),
                **({"warning": warning_message} if warning_message else {}),
                "qwen3_tts_manifest": (
                    qwen3_tts_manifest_path.name if qwen3_tts_manifest_path else ""
                ),
                "qwen3_tts_entries": len(exported_segments) if qwen3_tts_manifest_path else 0,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    if len(segments) == 0:
        log("完成，脚本运行成功，但没有得到可导出的语音片段（0 段）。")
    else:
        log(f"完成，导出 {len(segments)} 段。")
    log(f"索引文件: {out_dir / 'index.jsonl'}")
    if qwen3_tts_manifest_path:
        log(f"Qwen3-TTS 清单: {qwen3_tts_manifest_path}")
    return 0


def main() -> int:
    args = parse_args()
    requested_batch_size = int(args.batch_size)
    if requested_batch_size < 1:
        raise ValueError("batch_size 必须是大于等于 1 的整数。")
    if bool(args.force_cpu):
        log("已启用 ForceCpu：本次会跳过 CUDA，改用 CPU 推理。CPU 很慢，但能帮助排查显存问题。")
        return run_pipeline(args, batch_size=requested_batch_size, force_cpu=True)

    try:
        return run_pipeline(args, batch_size=requested_batch_size, force_cpu=False)
    except Exception as exc:
        if isinstance(exc, GpuSafetyPrecheckError):
            raise
        if not is_memory_pressure_error(exc):
            raise

        clear_exception_frames(exc)
        clear_cuda_cache()
        if requested_batch_size > 1:
            log("检测到显存不足，自动将 batch_size 降到 1 并重试。")
            try:
                return run_pipeline(args, batch_size=1, force_cpu=False)
            except Exception as retry_exc:
                if isinstance(retry_exc, GpuSafetyPrecheckError):
                    raise
                if not is_memory_pressure_error(retry_exc):
                    raise

                clear_exception_frames(retry_exc)
                clear_cuda_cache()

        try:
            import torch

            cuda_available = torch.cuda.is_available()
        except ImportError:
            cuda_available = False

        if cuda_available:
            log("batch_size=1 仍然显存不足，自动切换到 CPU 再试一次。")
            clear_cuda_cache()
            return run_pipeline(args, batch_size=1, force_cpu=True)

        raise


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\n[asr] 用户中断。", file=sys.stderr)
        raise SystemExit(130) from None

