"""测试 scripts/shared.py 的配置加载和工具函数。"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from shared import DEFAULT_SPLIT_DEFAULTS, project_root, read_split_defaults


def test_default_split_defaults_structure():
    """DEFAULT_SPLIT_DEFAULTS 必须包含 5 个分句参数。"""
    assert set(DEFAULT_SPLIT_DEFAULTS.keys()) == {
        "pause_threshold",
        "min_dur",
        "max_dur",
        "pad_left",
        "pad_right",
    }


def test_project_root_returns_path():
    """project_root() 返回 Path 对象且指向项目根目录。"""
    root = project_root()
    assert isinstance(root, Path)
    assert (root / "scripts" / "shared.py").exists()


def test_read_split_defaults_no_config_file(monkeypatch):
    """当 configs/defaults.json 不存在时，返回内置默认值。"""

    monkeypatch.setattr("shared.SHARED_DEFAULTS_PATH", Path("/no/such/path/defaults.json"))
    result = read_split_defaults()
    assert result == DEFAULT_SPLIT_DEFAULTS


def test_read_split_defaults_valid_json():
    """从有效 JSON 文件读取分句默认值，应正确覆盖内置值。"""
    custom = {
        "pause_threshold": 0.40,
        "min_dur": 1.0,
        "max_dur": 10.0,
        "pad_left": 0.10,
        "pad_right": 0.20,
    }
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", encoding="utf-8", delete=False) as f:
        json.dump(custom, f)
        tmp_path = f.name

    try:
        import shared

        original = shared.SHARED_DEFAULTS_PATH
        shared.SHARED_DEFAULTS_PATH = Path(tmp_path)
        result = shared.read_split_defaults()
        shared.SHARED_DEFAULTS_PATH = original

        assert result["pause_threshold"] == 0.40
        assert result["min_dur"] == 1.0
        assert result["max_dur"] == 10.0
        assert result["pad_left"] == 0.10
        assert result["pad_right"] == 0.20
    finally:
        Path(tmp_path).unlink(missing_ok=True)


def test_read_split_defaults_partial_json():
    """JSON 只包含部分字段时，缺失字段应回退到内置默认值。"""
    partial = {"pause_threshold": 0.30, "min_dur": 0.50}
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", encoding="utf-8", delete=False) as f:
        json.dump(partial, f)
        tmp_path = f.name

    try:
        import shared

        original = shared.SHARED_DEFAULTS_PATH
        shared.SHARED_DEFAULTS_PATH = Path(tmp_path)
        result = shared.read_split_defaults()
        shared.SHARED_DEFAULTS_PATH = original

        assert result["pause_threshold"] == 0.30
        assert result["min_dur"] == 0.50
        assert result["max_dur"] == DEFAULT_SPLIT_DEFAULTS["max_dur"]
        assert result["pad_left"] == DEFAULT_SPLIT_DEFAULTS["pad_left"]
        assert result["pad_right"] == DEFAULT_SPLIT_DEFAULTS["pad_right"]
    finally:
        Path(tmp_path).unlink(missing_ok=True)


def test_read_split_defaults_invalid_json():
    """JSON 格式错误时应回退到内置默认值，不应抛异常。"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", encoding="utf-8", delete=False) as f:
        f.write("this is not valid json {{{")
        tmp_path = f.name

    try:
        import shared

        original = shared.SHARED_DEFAULTS_PATH
        shared.SHARED_DEFAULTS_PATH = Path(tmp_path)
        result = shared.read_split_defaults()
        shared.SHARED_DEFAULTS_PATH = original

        assert result == DEFAULT_SPLIT_DEFAULTS
    finally:
        Path(tmp_path).unlink(missing_ok=True)
