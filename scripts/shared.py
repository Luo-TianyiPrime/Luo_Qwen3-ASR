"""Qwen3-ASR 项目共享常量和工具函数。

本模块提供的所有内容均无副作用导入安全，不涉及模型加载、网络访问或文件写入。
"""

from __future__ import annotations

import json
from pathlib import Path

DEFAULT_SPLIT_DEFAULTS: dict[str, float] = {
    "pause_threshold": 0.60,
    "min_dur": 0.80,
    "max_dur": 8.00,
    "pad_left": 0.05,
    "pad_right": 0.10,
}

SHARED_DEFAULTS_PATH: Path = Path(__file__).resolve().parents[1] / "configs" / "defaults.json"


def project_root() -> Path:
    """返回项目根目录（scripts/ 的父目录）。"""
    return Path(__file__).resolve().parents[1]


def read_split_defaults() -> dict[str, float]:
    """从 configs/defaults.json 读取分句默认值，文件缺失时回退到内置默认值。

    这个函数被 PowerShell CLI、WebUI 后端、Python CLI 共同调用，
    保证三方始终使用同一套分句参数基准。
    """
    defaults = dict(DEFAULT_SPLIT_DEFAULTS)
    if not SHARED_DEFAULTS_PATH.exists():
        return defaults
    try:
        payload = json.loads(SHARED_DEFAULTS_PATH.read_text(encoding="utf-8"))
        for key, fallback in DEFAULT_SPLIT_DEFAULTS.items():
            try:
                defaults[key] = float(payload.get(key, fallback))
            except (TypeError, ValueError):
                defaults[key] = fallback
    except (json.JSONDecodeError, OSError):
        return defaults
    return defaults
