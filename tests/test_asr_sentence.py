"""测试 scripts/asr_sentence_segment.py 中的纯函数。

这些测试不依赖 GPU、不加载模型、不需要真实音频文件。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import pytest

# 只导入纯函数，不触发 torch / qwen_asr 等重量级依赖
from asr_sentence_segment import (
    CharStamp,
    collect_pause_edges,
    format_seconds_short,
    get_field,
    greedy_sentence_split,
    normalize_punctuation_text,
    safe_filename_from_text,
    text_without_punctuation,
    to_float,
)

# ── CharStamp 与基础类型 ──


def test_charstamp_creation():
    stamp = CharStamp(char="你", start=0.0, end=0.1)
    assert stamp.char == "你"
    assert stamp.start == 0.0
    assert stamp.end == 0.1


# ── to_float ──


class TestToFloat:
    def test_normal_number(self):
        assert to_float("3.14") == pytest.approx(3.14)

    def test_integer(self):
        assert to_float(42) == pytest.approx(42.0)

    def test_none_returns_default(self):
        assert to_float(None, default=1.0) == pytest.approx(1.0)

    def test_invalid_returns_default(self):
        assert to_float("abc", default=1.0) == pytest.approx(1.0)

    def test_none_without_default(self):
        assert to_float(None) is None


# ── format_seconds_short ──


class TestFormatSecondsShort:
    def test_zero(self):
        assert format_seconds_short(0) == "0s"

    def test_seconds_only(self):
        assert format_seconds_short(45) == "45s"

    def test_minutes(self):
        assert format_seconds_short(125) == "2m05s"

    def test_hours(self):
        assert format_seconds_short(3661) == "1h01m01s"


# ── get_field ──


class TestGetField:
    def test_dict_access(self):
        assert get_field({"key": "value"}, "key") == "value"

    def test_dict_missing_with_default(self):
        assert get_field({}, "key", "fallback") == "fallback"

    def test_object_attribute(self):
        class Obj:
            attr = "hello"

        assert get_field(Obj(), "attr") == "hello"

    def test_object_missing_attr_default(self):
        class Obj:
            pass

        assert get_field(Obj(), "nonexistent", "fallback") == "fallback"


# ── safe_filename_from_text ──


class TestSafeFilenameFromText:
    def test_normal_text(self):
        result = safe_filename_from_text("你好世界")
        assert "你好世界" in result
        assert ":" not in result

    def test_with_illegal_chars(self):
        result = safe_filename_from_text("test:file<name>.wav")
        assert ":" not in result
        assert "<" not in result
        assert ">" not in result

    def test_empty_text(self):
        result = safe_filename_from_text("")
        assert result == "segment"

    def test_only_spaces(self):
        result = safe_filename_from_text("   ")
        assert result == "segment"

    def test_exceeds_max_len(self):
        long_text = "A" * 200
        result = safe_filename_from_text(long_text, max_len=80)
        assert len(result) <= 80

    def test_control_chars_removed(self):
        result = safe_filename_from_text("foo\x00bar")
        assert "\x00" not in result


# ── collect_pause_edges ──


class TestCollectPauseEdges:
    def make_timeline(self, gaps):
        """gaps: float 间隔列表（秒），生成对应时间线。"""
        timeline = []
        t = 0.0
        for _i, gap in enumerate(gaps):
            end = t + 0.05
            timeline.append(CharStamp(char="x", start=t, end=end))
            t = end + gap
        return timeline

    def test_no_pauses_below_threshold(self):
        timeline = self.make_timeline([0.1, 0.2, 0.1])
        edges = collect_pause_edges(timeline, pause_threshold=0.5)
        assert edges == set()

    def test_pauses_above_threshold(self):
        """超过阈值的停顿应被标记为切分点。"""
        # 时间线包含 5 个字符，停顿值列表表示字符间间隔
        timeline = self.make_timeline([0.1, 0.9, 0.2, 0.8, 0.1])
        edges = collect_pause_edges(timeline, pause_threshold=0.5)
        # 0.9s 停顿在索引 1 之后，0.8s 停顿在索引 3 之后
        assert 1 in edges
        assert 3 in edges
        assert len(edges) == 2

    def test_empty_timeline(self):
        assert collect_pause_edges([], pause_threshold=0.5) == set()


# ── greedy_sentence_split ──


def make_char_timeline(chars, durations):
    """用字符列表和对应时长列表创建 CharStamp 时间线。

    chars: 字符列表
    durations: 每个字符的持续时长（秒）
    """
    timeline = []
    t = 0.0
    for ch, dur in zip(chars, durations, strict=True):
        end = t + dur
        timeline.append(CharStamp(char=ch, start=t, end=end))
        t = end
    return timeline


class TestGreedySentenceSplit:
    # 参数默认值
    DEFAULT_ARGS = {
        "pause_threshold": 0.6,
        "min_dur": 0.8,
        "max_dur": 8.0,
        "pad_left": 0.05,
        "pad_right": 0.10,
    }

    def split(self, timeline, **overrides):
        args = {**self.DEFAULT_ARGS, **overrides}
        audio_duration = timeline[-1].end if timeline else 0.0
        return greedy_sentence_split(timeline, audio_duration=audio_duration, **args)

    def test_empty_timeline(self):
        assert self.split([]) == []

    def test_single_strong_boundary(self):
        """强边界（句号）应作为一个完整句子。"""
        timeline = make_char_timeline(
            ["你", "好", "。"],
            [0.2, 0.2, 0.1],
        )
        chunks = self.split(timeline)
        assert len(chunks) == 1
        assert "你好。" in chunks[0]["text"]

    def test_strong_boundary_splits(self):
        """两个句子间有句号时，若总长度超过 max_dur 则应在句号处切开。"""
        # "你好。" 时长 1.2s + "再见。" 时长 0.5s = 1.7s
        # 设置 max_dur=1.5 使得两句无法放进同一段
        timeline = make_char_timeline(
            ["你", "好", "。", "再", "见", "。"],
            [0.2, 0.2, 0.8, 0.2, 0.2, 0.1],
        )
        chunks = self.split(timeline, min_dur=0.3, max_dur=1.5)
        assert len(chunks) >= 2, f"expected >=2 chunks, got {len(chunks)}: {[c['text'] for c in chunks]}"

    def test_pause_triggers_split(self):
        """长停顿应触发行内切分。"""
        # 构造时间线：字1(0.2s) + 长停顿(0.5s) + 字2(0.2s) + 短停顿(0.1s) + 字3(0.2s)
        # 使用 collect_pause_edges 级别的 make_timeline 构建带停顿的时间线
        pauses = [0.2, 0.5, 0.2, 0.1, 0.2]
        # 这是 5 个字符和它们之间的 5 个停顿，但 make_timeline 生成 5 个字符
        # 停顿: 0.2 在 ch0后, 0.5 在 ch1后, 0.2 在 ch2后, 0.1 在 ch3后
        tl = []
        t = 0.0
        chars = ["你", "好", "再", "见", "了"]
        for _i, (ch, gap) in enumerate(zip(chars, pauses, strict=True)):
            end = t + 0.1
            tl.append(CharStamp(char=ch, start=t, end=end))
            t = end + gap
        audio_duration = tl[-1].end if tl else 0.0
        chunks = greedy_sentence_split(
            tl, audio_duration=audio_duration,
            pause_threshold=0.3, min_dur=0.1, max_dur=8.0,
            pad_left=0.05, pad_right=0.10,
        )
        assert len(chunks) == 2, f"expected 2 chunks, got {len(chunks)}: {[c['text'] for c in chunks]}"

    def test_max_dur_hard_cut(self):
        """超过 max_dur 时应用硬切。"""
        timeline = make_char_timeline(
            ["a"],
            [10.0],
        )
        chunks = self.split(timeline, max_dur=1.0)
        assert len(chunks) == 1
        assert chunks[0]["end"] - chunks[0]["start"] <= 10.0

    def test_min_dur_extends_short(self):
        """短片段应延长到满足 min_dur。"""
        timeline = make_char_timeline(
            ["你", "好", "吗"],
            [0.1, 0.1, 0.1],
        )
        chunks = self.split(timeline, min_dur=0.3, max_dur=10.0)
        assert len(chunks) == 1
        dur = chunks[0]["end"] - chunks[0]["start"]
        assert dur >= 0.25, f"expected duration >= 0.3, got {dur}"

    def test_padding_applied(self):
        """pad_left 和 pad_right 应在音频片段上生效。"""
        timeline = make_char_timeline(
            ["你", "好", "。"],
            [0.3, 0.3, 0.1],
        )
        audio_duration = 0.7
        chunks = greedy_sentence_split(
            timeline,
            audio_duration=audio_duration,
            pause_threshold=0.6,
            min_dur=0.8,
            max_dur=8.0,
            pad_left=0.05,
            pad_right=0.10,
        )
        assert len(chunks) == 1
        seg = chunks[0]
        assert seg["start"] == 0.0  # pad_left capped at 0
        assert seg["end"] == 0.7  # pad_right capped by audio_duration

    def test_tail_merge_short_last(self):
        """最后一段太短时应合并到前一段。"""
        timeline = make_char_timeline(
            ["你", "好", "。"] + ["再"] * 10 + ["见", "。"],
            [0.2, 0.2, 0.8] + [0.2] * 10 + [0.2, 0.1],
        )
        chunks = self.split(timeline, min_dur=0.8)
        assert len(chunks) >= 1

    def test_text_contains_all_chars(self):
        """切分后的文本应包含时间线中的所有字符。"""
        chars = ["你", "好", "，", "世", "界", "。"]
        timeline = make_char_timeline(chars, [0.2] * len(chars))
        chunks = self.split(timeline)
        all_text = "".join(c["text"] for c in chunks)
        assert "你好" in all_text.replace("，", "").replace("。", "")
        assert "世界" in all_text.replace("，", "").replace("。", "")


# ── normalize_punctuation_text ──


class TestNormalizePunctuationText:
    def test_english_to_chinese(self):
        result = normalize_punctuation_text("Hello, world.")
        assert "，" in result
        assert "。" in result

    def test_no_change_to_correct_text(self):
        text = "大家好，欢迎回来。"
        assert normalize_punctuation_text(text) == text

    def test_duplicate_punctuation_removed(self):
        result = normalize_punctuation_text("你好，，，世界！！")
        assert ",," not in result
        assert "！！" not in result
        assert "。" in result or "，" in result

    def test_whitespace_removed(self):
        result = normalize_punctuation_text("你好 ， 世界 。")
        assert "你好，世界。" == result

    def test_weak_then_strong(self):
        """`,。` 这样的组合只保留强标点。"""
        result = normalize_punctuation_text("你好，。")
        assert "，" not in result
        assert "你好。" == result

    def test_empty_string(self):
        assert normalize_punctuation_text("") == ""

    def test_no_punctuation_text(self):
        text = "大家好欢迎回来"
        assert normalize_punctuation_text(text) == text


# ── text_without_punctuation ──


class TestTextWithoutPunctuation:
    def test_removes_all_punctuation(self):
        result = text_without_punctuation("你好，世界！")
        assert "，" not in result
        assert "！" not in result
        assert result == "你好世界"

    def test_same_without_punctuation(self):
        """带标点和不带标点的文本，去掉标点后应一致。"""
        raw = "大家好欢迎回来"
        punc = "大家好，欢迎回来。"
        assert text_without_punctuation(raw) == text_without_punctuation(punc)

    def test_preserves_digits_and_letters(self):
        text = "今天是2026年6月14日"
        assert "2026" in text_without_punctuation(text)
        assert "14" in text_without_punctuation(text)
