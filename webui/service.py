from __future__ import annotations

import hashlib
import json
import mimetypes
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

_scripts_dir = str(Path(__file__).resolve().parents[1] / "scripts")
if _scripts_dir not in sys.path:
    sys.path.insert(0, _scripts_dir)

from shared import read_split_defaults  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_ROOT = PROJECT_ROOT / ".cache" / "webui"
JOB_LOG_ROOT = RUNTIME_ROOT / "logs"
JOBS_DB_PATH = RUNTIME_ROOT / "jobs.json"
PREFERENCES_PATH = RUNTIME_ROOT / "preferences.json"
DEFAULT_CONFIG_PATH = RUNTIME_ROOT / "default_config.json"
WEBUI_OUTPUT_ROOT = PROJECT_ROOT / "outputs" / "webui_runs"
CONFIG_ROOT = PROJECT_ROOT / "configs" / "webui"
HOTWORD_LIBRARY_ROOT = PROJECT_ROOT / "configs" / "hotwords"
HOTWORD_RUNTIME_ROOT = RUNTIME_ROOT / "hotwords_runtime"
BUILTIN_DEFAULT_CONFIG_NAME = "current_workflow.json"
SHARED_DEFAULTS_PATH = PROJECT_ROOT / "configs" / "defaults.json"
RUN_SCRIPT_PATH = PROJECT_ROOT / "run.ps1"
BOOTSTRAP_SCRIPT_PATH = PROJECT_ROOT / "bootstrap.ps1"
SELF_CHECK_SCRIPT_PATH = PROJECT_ROOT / "scripts" / "self_check.py"
VENV_PYTHON_PATH = PROJECT_ROOT / ".venv" / "Scripts" / "python.exe"

JOB_TIMEOUT_SECONDS = int(os.getenv("WEBUI_JOB_TIMEOUT_SECONDS", str(24 * 3600)))
LOG_TAIL_READ_BYTES = 64 * 1024
PROGRESS_SAVE_INTERVAL_SECONDS = 5.0
PROGRESS_SAVE_DELTA_PERCENT = 5.0
RESULTS_CACHE_TTL_SECONDS = 5.0


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def ensure_runtime_dirs() -> None:
    for path in (
        RUNTIME_ROOT,
        JOB_LOG_ROOT,
        WEBUI_OUTPUT_ROOT,
        CONFIG_ROOT,
        HOTWORD_LIBRARY_ROOT,
        HOTWORD_RUNTIME_ROOT,
    ):
        path.mkdir(parents=True, exist_ok=True)


def read_json_file(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return default


def write_json_file(path: Path, data: Any) -> None:
    """原子写 JSON，防止中断损坏 jobs.json。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with tmp.open("w", encoding="utf-8", newline="\n") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        tmp.replace(path)
    finally:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass


def tail_lines(path: Path, max_lines: int = 200) -> list[str]:
    if not path.exists():
        return []
    size = path.stat().st_size
    start = max(0, size - LOG_TAIL_READ_BYTES)
    with path.open("rb") as f:
        f.seek(start)
        chunk = f.read()
    text = chunk.decode("utf-8", errors="replace")
    lines = text.splitlines()
    if start > 0 and lines:
        lines = lines[1:]
    return [line.rstrip("\n\r") for line in lines[-max_lines:]]


def normalize_user_path(raw_value: str) -> str:
    return (raw_value or "").strip().replace("/", "\\")


def resolve_project_path(raw_value: str) -> Path:
    value = normalize_user_path(raw_value)
    if not value:
        return PROJECT_ROOT
    p = Path(value).expanduser()
    return p.resolve() if p.is_absolute() else (PROJECT_ROOT / p).resolve()


def resolve_ckpt_value(raw_value: str) -> str:
    value = (raw_value or "").strip()
    if not value:
        return ""
    p = Path(value).expanduser()
    if p.is_absolute():
        return str(p)
    if value.startswith(".\\") or value.startswith("./") or "\\" in value or "/" in value:
        return str((PROJECT_ROOT / p).resolve())
    local = (PROJECT_ROOT / p).resolve()
    return str(local) if local.exists() else value


def safe_name(raw_value: str, max_len: int = 48) -> str:
    value = (raw_value or "").strip() or "task"
    cleaned = re.sub(r'[\\/:*?"<>|]+', "_", value)
    cleaned = re.sub(r"\s+", "_", cleaned).strip("._")
    return (cleaned or "task")[:max_len]


def normalize_config_file_name(raw_value: str) -> str:
    value = (raw_value or "").strip()
    if not value:
        raise ValueError("配置文件名不能为空")
    return safe_name(Path(value).stem or value, max_len=64) + ".json"


def normalize_hotword_file_name(raw_value: str) -> str:
    value = (raw_value or "").strip()
    if not value:
        raise ValueError("热词库文件名不能为空")
    return safe_name(Path(value).stem or value, max_len=64) + ".txt"


def parse_hotword_entries(raw_text: str | None) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in str(raw_text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = raw.strip()
        if not line or line in seen:
            continue
        seen.add(line)
        out.append(line)
    return out


def normalize_hotword_library_content(raw_text: str | None) -> str:
    return "\n".join(parse_hotword_entries(raw_text))


def _path_is_within_any_root(target: Path, roots: list[Path]) -> bool:
    resolved_target = target.resolve()
    for root in roots:
        try:
            resolved_root = root.resolve()
        except OSError:
            continue
        if resolved_target == resolved_root or resolved_root in resolved_target.parents:
            return True
    return False


def infer_title_from_audio(audio_path: str) -> str:
    p = resolve_project_path(audio_path)
    if p.exists() and p.is_dir():
        return f"批量处理 {p.name}"
    if p.exists() and p.is_file():
        return f"单文件处理 {p.stem}"
    return f"音频处理 {Path(audio_path or 'audio').stem or '未命名任务'}"


def build_auto_output_dir(job_id: str, audio_path: str) -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    source = safe_name(Path(audio_path or "audio").stem or "audio")
    return WEBUI_OUTPUT_ROOT / f"{stamp}__{source}__{job_id[:8]}"


def build_retry_output_dir(raw_output_dir: str) -> str:
    resolved = resolve_project_path(raw_output_dir).resolve()
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    base_name = resolved.name or "output"
    return str(resolved.with_name(f"{base_name}_retry_{stamp}"))


def make_result_id(run_dir: Path) -> str:
    return hashlib.sha1(str(run_dir.resolve()).encode("utf-8")).hexdigest()[:16]


def guess_media_type(path: Path) -> str:
    media_type, _ = mimetypes.guess_type(str(path))
    return media_type or "application/octet-stream"


def probe_audio_duration_seconds(audio_path: Path, timeout: int = 10) -> float | None:
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
                str(audio_path),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=True,
        )
        value = float((result.stdout or "").strip())
        return value if value > 0 else None
    except (subprocess.TimeoutExpired, subprocess.CalledProcessError, FileNotFoundError, ValueError, OSError):
        return None


def _coerce_optional_float(value: Any, field_name: str) -> float | None:
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    try:
        return float(value)
    except Exception as exc:
        raise ValueError(f"{field_name} 必须是数字") from exc


@dataclass
class JobRecord:
    id: str
    kind: str
    title: str
    status: str
    created_at: str
    config: dict[str, Any] = field(default_factory=dict)
    command: list[str] = field(default_factory=list)
    output_dir: str = ""
    log_path: str = ""
    started_at: str | None = None
    finished_at: str | None = None
    exit_code: int | None = None
    error: str = ""
    warning: str = ""
    progress_value: float = 0.0
    progress_label: str = "等待加入队列"
    summary: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> JobRecord:
        return cls(
            id=str(payload.get("id", "")),
            kind=str(payload.get("kind", "asr")),
            title=str(payload.get("title", "未命名任务")),
            status=str(payload.get("status", "queued")),
            created_at=str(payload.get("created_at", now_iso())),
            config=dict(payload.get("config", {})),
            command=list(payload.get("command", [])),
            output_dir=str(payload.get("output_dir", "")),
            log_path=str(payload.get("log_path", "")),
            started_at=payload.get("started_at"),
            finished_at=payload.get("finished_at"),
            exit_code=payload.get("exit_code"),
            error=str(payload.get("error", "")),
            warning=str(payload.get("warning", "")),
            progress_value=float(payload.get("progress_value", 0.0)),
            progress_label=str(payload.get("progress_label", "等待加入队列")),
            summary=dict(payload.get("summary", {})),
        )


class JobManager:
    ASR_FORM_GROUPS = [
        {"id": "io", "title": "输入与输出", "description": "配置音频来源、输出目录与清单导出格式"},
        {"id": "models", "title": "模型与语言", "description": "配置识别模型、对齐模型、语言策略与热词"},
        {"id": "split", "title": "分句策略", "description": "控制停顿切分、句长约束与句首句尾补偿"},
        {"id": "runtime", "title": "运行与性能", "description": "控制吞吐、ETA 估算、递归扫描与长音频预警"},
    ]
    ASR_FORM_FIELDS = [
        {
            "group": "io",
            "key": "audio",
            "label": "输入路径",
            "type": "text",
            "description": "支持单个音频文件或文件夹批处理",
            "long_help": "第一次使用建议直接把音频放进 .\\inputs，再来提交任务，最不容易出路径问题。",
        },
        {
            "group": "io",
            "key": "output_mode",
            "label": "输出模式",
            "type": "select",
            "options": [{"value": "auto", "label": "自动"}, {"value": "custom", "label": "自定义"}],
            "description": "自动模式会按时间戳生成独立 run 目录，更适合新手",
            "long_help": "新手建议先用“自动”；只有在你明确要写入固定目录时再切“自定义”。",
        },
        {
            "group": "io",
            "key": "output_dir",
            "label": "自定义输出目录",
            "type": "text",
            "description": "仅 output_mode=custom 时生效",
            "long_help": "建议先留空。只有你明确要落到固定目录时再填写，项目内路径最省心。",
        },
        {
            "group": "io",
            "key": "dataset_format",
            "label": "输出清单格式",
            "type": "select",
            "options": [{"value": "standard", "label": "通用 standard"}, {"value": "qwen3_tts", "label": "Qwen3-TTS qwen3_tts"}],
            "description": "standard 适合通用识别，qwen3_tts 适合后续 TTS 整理",
            "long_help": "如果只是想把音频转文字，选 standard 就够了；只有准备做 Qwen3-TTS 数据时才选 qwen3_tts。",
        },
        {
            "group": "io",
            "key": "ref_audio",
            "label": "参考音频（可选）",
            "type": "text",
            "description": "只有导出 Qwen3-TTS 清单时才会用到",
            "long_help": "普通识别不需要填。你如果不是在整理 TTS 数据，直接留空就行。",
        },
        {
            "group": "models",
            "key": "asr_ckpt",
            "label": "ASR 模型目录",
            "type": "text",
            "description": "填本地模型目录更稳，新手建议直接用 bootstrap 下载好的模型",
            "long_help": "首次加载模型慢是正常的；如果你还没下载模型，先运行 bootstrap.ps1 -DownloadModels。",
        },
        {
            "group": "models",
            "key": "aligner_ckpt",
            "label": "对齐模型目录",
            "type": "text",
            "description": "用于生成更精细的字级 / 词级时间戳",
            "long_help": "对齐会增加一点耗时，但对分句切点和后处理质量更有帮助。",
        },
        {
            "group": "models",
            "key": "language",
            "label": "语言策略",
            "type": "select",
            "options": [{"value": "None", "label": "自动"}, {"value": "Chinese", "label": "中文"}, {"value": "English", "label": "英文"}],
            "description": "None 表示自动检测语言，中文单语通常更稳",
            "long_help": "如果音频几乎都是单语，固定语言通常更稳更快；不确定就先选自动。",
        },
        {
            "group": "models",
            "key": "punc_model",
            "label": "标点恢复模型",
            "type": "text",
            "description": "默认启用，用于给 ASR 原始文本补逗号、句号、问号等标点",
            "long_help": "这是文本后处理模型：它不会重新识别音频，只会根据已经识别出的文字判断标点位置。留空表示关闭标点恢复；旧环境如果提示缺少 funasr，请先点“补装 FunASR”。",
        },
        {
            "group": "models",
            "key": "hotword_library",
            "label": "热词库（长期保存）",
            "type": "select",
            "options": [{"value": "", "label": "不使用"}],
            "description": "选择已保存的专有名词词表，选中后会自动加载到下方热词编辑区",
            "long_help": "长期复用的品牌词、人名、项目名词表。选中后下方临时热词区会显示库内容，可直接编辑并通过「保存到热词库」按钮写回。",
        },
        {
            "group": "models",
            "key": "hotword_text",
            "label": "热词内容编辑（当前任务使用）",
            "type": "text",
            "description": "每行一个词或短语。选中热词库后自动加载库内容，可在此直接编辑。",
            "long_help": "提交任务时这里的内容就是任务实际使用的热词。选中热词库后编辑完记得点击「保存到热词库」写回库文件。",
        },
        {
            "group": "split",
            "key": "pause_threshold",
            "label": "停顿阈值",
            "type": "number",
            "step": 0.05,
            "min": 0.01,
            "description": "单位秒。值越小越容易切成短句，值越大越倾向长句",
            "long_help": "常用 0.4~0.8；环境噪声大或语速快时，建议先从 0.6 微调。",
        },
        {
            "group": "split",
            "key": "min_dur",
            "label": "最短句时长",
            "type": "number",
            "step": 0.1,
            "min": 0,
            "description": "单位秒。限制句子最短时长，避免句子过碎",
            "long_help": "必须小于等于 max_dur；过大可能导致多句被强行合并。",
        },
        {
            "group": "split",
            "key": "max_dur",
            "label": "最长句时长",
            "type": "number",
            "step": 0.1,
            "min": 0.1,
            "description": "单位秒。限制句子最长时长，避免句子过长难校对",
            "long_help": "必须大于等于 min_dur；过小可能导致中途硬切。",
        },
        {
            "group": "split",
            "key": "pad_left",
            "label": "左补边",
            "type": "number",
            "step": 0.01,
            "min": 0,
            "description": "单位秒。句首向前扩一点，减少切掉起始辅音的风险",
            "long_help": "不能为负数；常见取值 0.03~0.08。",
        },
        {
            "group": "split",
            "key": "pad_right",
            "label": "右补边",
            "type": "number",
            "step": 0.01,
            "min": 0,
            "description": "单位秒。句尾向后扩一点，减少切掉尾音的风险",
            "long_help": "不能为负数；常见取值 0.05~0.15。",
        },
        {
            "group": "runtime",
            "key": "batch_size",
            "label": "批大小（不懂就默认 1）",
            "type": "number",
            "step": 1,
            "min": 1,
            "description": "一次并行处理的样本数。越大通常越快，但更占显存/内存",
            "long_help": "如果出现 OOM（显存不足）或卡死，优先把该值降低到 1 或 2。",
        },
        {
            "group": "runtime",
            "key": "max_new_tokens",
            "label": "最大生成 Token 数（不懂就默认 2048）",
            "type": "number",
            "step": 256,
            "min": 64,
            "description": "每次 ASR 推理的最大输出 token 数。值越大 KV 缓存占显存越多",
            "long_help": "正常语音识别输出通常在 2000 tokens 以内。如果爆显存，优先降低这个值到 1024。",
        },
        {
            "group": "runtime",
            "key": "eta_rtf",
            "label": "ETA 估算速度（只影响显示）",
            "type": "number",
            "step": 0.1,
            "min": 0.1,
            "description": "只影响“预计剩余时间”的显示，不影响识别结果",
            "long_help": "RTF=1.0 约等于实时速度；RTF 越大表示估算速度越快。",
        },
        {
            "group": "runtime",
            "key": "long_audio_warning_minutes",
            "label": "长音频预警（分钟）",
            "type": "number",
            "step": 1,
            "min": 1,
            "description": "超过这个时长时，会提醒你任务可能比较久",
            "long_help": "默认 120 分钟。这里只是提示，不会阻止任务提交。",
        },
        {
            "group": "runtime",
            "key": "scan_subfolders",
            "label": "递归扫描子目录",
            "type": "checkbox",
            "description": "当输入为目录时，是否继续扫描所有子目录中的音频",
            "long_help": "开启后任务规模可能显著扩大，建议先在小目录试跑。",
        },
    ]
    QUICK_ACTIONS = [
        {"kind": "self_check", "label": "环境自检", "description": "先看 Python、ffmpeg、模型路径是否都正常"},
        {"kind": "bootstrap", "label": "安装基础依赖", "description": "创建虚拟环境并安装 PyTorch / 核心依赖"},
        {"kind": "download_models", "label": "下载模型", "description": "把 ASR / 对齐模型下载到本地 models/ 目录"},
        {"kind": "bootstrap_funasr", "label": "补装 FunASR", "description": "默认标点恢复依赖它；旧环境缺依赖时点击这里修复"},
    ]
    GUIDE_SECTIONS = [
        {
            "title": "新手先做这几步",
            "items": [
                "先看上面的环境卡片：缺 Python、ffmpeg 或模型时，先补齐再提交任务。",
                "第一次建议直接把音频放进 .\\inputs，并保持“自动输出”不改。",
                "先用默认分句参数跑通，再按结果微调停顿阈值和句长参数。",
                "一次只改一个参数，出问题时更容易回退。",
            ],
        },
        {
            "title": "性能与稳定性",
            "items": [
                "batch_size 越大通常越快，但更容易触发显存不足；爆显存时先降到 1。",
                "任务执行默认 24 小时超时，超时后会自动终止，避免一直卡住。",
                "结果列表会缓存目录变化；点“手动刷新”时才会强制重扫磁盘。",
                "如果刚装完依赖，建议先试一个很短的音频，确认整条链路没问题。",
            ],
        },
        {
            "title": "失败后怎么看",
            "items": [
                "任务失败时先看队列里的红色提示，再看日志最后几行，通常就能定位原因。",
                "如果提示缺少 funasr，说明旧环境缺少默认标点恢复依赖，先运行 bootstrap.ps1 -InstallFunASR。",
                "如果提示显存不足，先把 batch_size 调到 1，再重试。",
                "如果提示路径不存在，先回到“输入路径”或“参考音频”检查盘符和文件名。",
            ],
        },
    ]

    def __init__(self) -> None:
        ensure_runtime_dirs()
        self._lock = threading.RLock()
        self._queue: queue.Queue[str] = queue.Queue()
        self._pending_ids: list[str] = []
        self._running_job_id: str | None = None
        self._jobs: dict[str, JobRecord] = {}
        self._process: subprocess.Popen[str] | None = None
        self._cancelled_job_ids: set[str] = set()
        self._results_cache: list[dict[str, Any]] | None = None
        self._results_cache_mtime: tuple[tuple[str, int], ...] | None = None
        self._results_cache_time = 0.0
        self._last_save_time = 0.0
        self._last_saved_progress: dict[str, float] = {}
        self._load_jobs()
        self._normalize_interrupted_jobs()
        self._worker = threading.Thread(target=self._worker_loop, name="webui-job-worker", daemon=True)
        self._worker.start()

    def _cleanup_hotword_runtime_file(self, job_id: str) -> None:
        try:
            (HOTWORD_RUNTIME_ROOT / f"{job_id}.txt").unlink(missing_ok=True)
        except OSError:
            pass

    def _terminate_process_tree(self, process: subprocess.Popen[str]) -> None:
        try:
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(process.pid)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=15,
                check=False,
            )
        except (subprocess.TimeoutExpired, OSError):
            pass
        if process.poll() is None:
            try:
                process.kill()
            except OSError:
                pass

    def _load_jobs(self) -> None:
        payload = read_json_file(JOBS_DB_PATH, [])
        self._jobs = {}
        for item in payload:
            record = JobRecord.from_dict(item)
            self._jobs[record.id] = record
            self._last_saved_progress[record.id] = float(record.progress_value)

    def _save_jobs(self) -> None:
        with self._lock:
            rows = sorted(self._jobs.values(), key=lambda x: x.created_at, reverse=True)
            payload = [self._serialize_job(x) for x in rows]
            write_json_file(JOBS_DB_PATH, payload)
            self._last_save_time = time.time()
            for item in rows:
                self._last_saved_progress[item.id] = float(item.progress_value)

    def _normalize_interrupted_jobs(self) -> None:
        changed = False
        interrupted_job_ids: list[str] = []
        with self._lock:
            self._pending_ids = []
            self._running_job_id = None
            for job in self._jobs.values():
                if job.status in {"queued", "running"}:
                    job.status = "failed"
                    job.error = "检测到上次运行中断，任务未完整结束"
                    job.finished_at = now_iso()
                    job.progress_label = "任务中断"
                    job.progress_value = min(float(job.progress_value), 98.0)
                    changed = True
                    interrupted_job_ids.append(job.id)
        if changed:
            self._save_jobs()
        for job_id in interrupted_job_ids:
            self._cleanup_hotword_runtime_file(job_id)

    def _serialize_job(self, record: JobRecord) -> dict[str, Any]:
        payload = record.to_dict()
        payload["queue_position"] = 0
        if record.status == "queued" and record.id in self._pending_ids:
            payload["queue_position"] = self._pending_ids.index(record.id) + 1
        payload["is_running"] = record.id == self._running_job_id
        payload["has_output"] = bool(record.output_dir)
        payload["log_tail"] = tail_lines(Path(record.log_path), max_lines=200) if record.log_path else []
        return payload

    def list_jobs(self) -> list[dict[str, Any]]:
        with self._lock:
            return [self._serialize_job(x) for x in sorted(self._jobs.values(), key=lambda y: y.created_at, reverse=True)]

    def get_job(self, job_id: str) -> dict[str, Any]:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                raise KeyError(job_id)
            return self._serialize_job(job)

    def _results_fingerprint(self) -> tuple[tuple[str, int], ...]:
        roots: dict[str, Path] = {str(WEBUI_OUTPUT_ROOT.resolve()): WEBUI_OUTPUT_ROOT.resolve()}
        with self._lock:
            for job in self._jobs.values():
                if job.kind == "asr" and job.output_dir:
                    p = Path(job.output_dir).resolve()
                    roots[str(p)] = p
        out: list[tuple[str, int]] = []
        for key, root in roots.items():
            try:
                mtime = root.stat().st_mtime_ns
            except FileNotFoundError:
                mtime = -1
            out.append((key, mtime))
        return tuple(sorted(out))

    def _invalidate_results_cache(self) -> None:
        self._results_cache = None
        self._results_cache_mtime = None
        self._results_cache_time = 0.0

    def get_base_defaults(self) -> dict[str, Any]:
        split = read_split_defaults()
        return {
            "audio": r".\inputs",
            "output_mode": "auto",
            "output_dir": "",
            "dataset_format": "standard",
            "ref_audio": "",
            "hotword_library": "",
            "hotword_text": "",
            "asr_ckpt": r".\models\Qwen3-ASR-1.7B",
            "aligner_ckpt": r".\models\Qwen3-ForcedAligner-0.6B",
            "language": "None",
            "punc_model": "iic/punc_ct-transformer_cn-en-common-vocab471067-large",
            "batch_size": 1,
            "max_new_tokens": 2048,
            "pause_threshold": split["pause_threshold"],
            "min_dur": split["min_dur"],
            "max_dur": split["max_dur"],
            "pad_left": split["pad_left"],
            "pad_right": split["pad_right"],
            "eta_rtf": 2.0,
            "long_audio_warning_minutes": 120,
            "scan_subfolders": False,
        }

    def normalize_form_config(self, payload: dict[str, Any] | None) -> dict[str, Any]:
        defaults = self.get_base_defaults()
        out = dict(defaults)
        if not isinstance(payload, dict):
            return out
        for key, default in defaults.items():
            if key not in payload:
                continue
            value = payload[key]
            try:
                if isinstance(default, bool):
                    out[key] = value.strip().lower() in {"1", "true", "yes", "on"} if isinstance(value, str) else bool(value)
                elif isinstance(default, int):
                    out[key] = int(value)
                elif isinstance(default, float):
                    out[key] = float(value)
                elif value is None:
                    out[key] = default
                else:
                    out[key] = value
            except (TypeError, ValueError):
                out[key] = default
        return out

    def get_config_file_path(self, name: str) -> Path:
        return (CONFIG_ROOT / normalize_config_file_name(name)).resolve()

    def get_hotword_library_path(self, name: str) -> Path:
        return (HOTWORD_LIBRARY_ROOT / normalize_hotword_file_name(name)).resolve()

    def get_default_config_name(self) -> str:
        payload = read_json_file(DEFAULT_CONFIG_PATH, {})
        raw = str(payload.get("name", BUILTIN_DEFAULT_CONFIG_NAME) or BUILTIN_DEFAULT_CONFIG_NAME)
        try:
            return normalize_config_file_name(raw)
        except ValueError:
            return BUILTIN_DEFAULT_CONFIG_NAME

    def set_default_config_file(self, name: str) -> dict[str, Any]:
        p = self.get_config_file_path(name)
        if not p.exists():
            raise FileNotFoundError(str(p))
        normalized = normalize_config_file_name(name)
        write_json_file(DEFAULT_CONFIG_PATH, {"name": normalized})
        return {"default_config_name": normalized}

    def list_config_files(self) -> list[dict[str, Any]]:
        ensure_runtime_dirs()
        default_name = self.get_default_config_name()
        rows = []
        for p in sorted(CONFIG_ROOT.glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True):
            rows.append(
                {
                    "name": p.name,
                    "stem": p.stem,
                    "path": str(p.resolve()),
                    "updated_at": datetime.fromtimestamp(p.stat().st_mtime).astimezone().isoformat(),
                    "is_default": p.name == default_name,
                }
            )
        return rows

    def load_config_file(self, name: str) -> dict[str, Any]:
        p = self.get_config_file_path(name)
        if not p.exists():
            raise FileNotFoundError(str(p))
        cfg = self.normalize_form_config(read_json_file(p, {}))
        return {"name": p.name, "stem": p.stem, "path": str(p.resolve()), "config": cfg, "is_default": p.name == self.get_default_config_name()}

    def save_config_file(self, name: str, payload: dict[str, Any], set_as_default: bool = False) -> dict[str, Any]:
        p = self.get_config_file_path(name)
        write_json_file(p, self.normalize_form_config(payload))
        if set_as_default:
            write_json_file(DEFAULT_CONFIG_PATH, {"name": p.name})
        return self.load_config_file(p.name)

    def rename_config_file(self, name: str, new_name: str) -> dict[str, Any]:
        src = self.get_config_file_path(name)
        dst = self.get_config_file_path(new_name)
        if not src.exists():
            raise FileNotFoundError(str(src))
        if dst.exists():
            raise ValueError(f"目标配置文件已存在：{dst.name}")
        src.replace(dst)
        if src.name == self.get_default_config_name():
            write_json_file(DEFAULT_CONFIG_PATH, {"name": dst.name})
        return {"config_file": self.load_config_file(dst.name), "default_config_name": self.get_default_config_name()}

    def delete_config_file(self, name: str) -> dict[str, Any]:
        p = self.get_config_file_path(name)
        if not p.exists():
            raise FileNotFoundError(str(p))
        if p.name == BUILTIN_DEFAULT_CONFIG_NAME:
            raise ValueError("内置配置不允许删除")
        p.unlink()
        if p.name == self.get_default_config_name():
            write_json_file(DEFAULT_CONFIG_PATH, {"name": BUILTIN_DEFAULT_CONFIG_NAME})
        return {"deleted": p.name, "default_config_name": self.get_default_config_name()}

    def list_hotword_libraries(self) -> list[dict[str, Any]]:
        ensure_runtime_dirs()
        rows = []
        for p in sorted(HOTWORD_LIBRARY_ROOT.glob("*.txt"), key=lambda x: x.stat().st_mtime, reverse=True):
            content = p.read_text(encoding="utf-8", errors="replace")
            rows.append({"name": p.name, "stem": p.stem, "path": str(p.resolve()), "entries": len(parse_hotword_entries(content))})
        return rows

    def load_hotword_library(self, name: str) -> dict[str, Any]:
        p = self.get_hotword_library_path(name)
        if not p.exists():
            raise FileNotFoundError(str(p))
        content = normalize_hotword_library_content(p.read_text(encoding="utf-8", errors="replace"))
        return {"name": p.name, "stem": p.stem, "path": str(p.resolve()), "content": content, "entries": len(parse_hotword_entries(content))}

    def save_hotword_library(self, name: str, content: str) -> dict[str, Any]:
        p = self.get_hotword_library_path(name)
        normalized = normalize_hotword_library_content(content)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(normalized + ("\n" if normalized else ""), encoding="utf-8")
        return self.load_hotword_library(p.name)

    def get_defaults(self) -> dict[str, Any]:
        return self.normalize_form_config({**self.get_base_defaults(), **read_json_file(CONFIG_ROOT / self.get_default_config_name(), {})})

    def get_preferences(self) -> dict[str, Any]:
        return self.normalize_form_config({**self.get_defaults(), **read_json_file(PREFERENCES_PATH, {})})

    def save_preferences(self, payload: dict[str, Any]) -> dict[str, Any]:
        cur = self.get_preferences()
        for key in self.get_defaults():
            if key in payload:
                cur[key] = payload[key]
        cur = self.normalize_form_config(cur)
        write_json_file(PREFERENCES_PATH, cur)
        return cur

    def get_environment_snapshot(self) -> dict[str, Any]:
        hotword_options = [{"value": "", "label": "不使用"}]
        for item in self.list_hotword_libraries():
            hotword_options.append({"value": item["name"], "label": f"{item['stem']}（{item['entries']} 条）"})
        fields = []
        for field_def in self.ASR_FORM_FIELDS:
            row = dict(field_def)
            if row.get("key") == "hotword_library":
                row["options"] = hotword_options
            fields.append(row)
        jobs = self.list_jobs()
        inputs_dir = PROJECT_ROOT / "inputs"
        supported_exts = {".wav", ".mp3", ".m4a", ".flac", ".aac", ".ogg", ".opus", ".wma", ".webm", ".mp4", ".mkv", ".mov"}
        input_audio_files = []
        if inputs_dir.exists():
            for p in sorted(inputs_dir.rglob("*")):
                if p.is_file() and p.suffix.lower() in supported_exts:
                    input_audio_files.append(str(p.resolve()))
        asr_default = Path(resolve_ckpt_value(self.get_base_defaults()["asr_ckpt"]))
        aligner_default = Path(resolve_ckpt_value(self.get_base_defaults()["aligner_ckpt"]))
        return {
            "project_root": str(PROJECT_ROOT.resolve()),
            "config_dir": str(CONFIG_ROOT.resolve()),
            "hotword_library_dir": str(HOTWORD_LIBRARY_ROOT.resolve()),
            "inputs_dir": str((PROJECT_ROOT / "inputs").resolve()),
            "outputs_dir": str((PROJECT_ROOT / "outputs").resolve()),
            "webui_outputs_dir": str(WEBUI_OUTPUT_ROOT.resolve()),
            "run_script": str(RUN_SCRIPT_PATH.resolve()),
            "bootstrap_script": str(BOOTSTRAP_SCRIPT_PATH.resolve()),
            "self_check_script": str(SELF_CHECK_SCRIPT_PATH.resolve()),
            "python_exe": str(VENV_PYTHON_PATH.resolve()),
            "venv_exists": VENV_PYTHON_PATH.exists(),
            "ffmpeg_path": shutil.which("ffmpeg") or "",
            "ffprobe_path": shutil.which("ffprobe") or "",
            "inputs_audio_count": len(input_audio_files),
            "inputs_audio_preview": input_audio_files[:5],
            "models": {
                "asr_default": str(asr_default.resolve()),
                "aligner_default": str(aligner_default.resolve()),
                "asr_default_exists": asr_default.exists(),
                "aligner_default_exists": aligner_default.exists(),
            },
            "job_counts": {
                "queued": sum(1 for x in jobs if x["status"] == "queued"),
                "running": sum(1 for x in jobs if x["status"] == "running"),
                "success": sum(1 for x in jobs if x["status"] == "success"),
                "failed": sum(1 for x in jobs if x["status"] == "failed"),
            },
            "guide_sections": self.GUIDE_SECTIONS,
            "quick_actions": self.QUICK_ACTIONS,
            "form_groups": self.ASR_FORM_GROUPS,
            "form_fields": fields,
        }

    def _build_asr_command(self, config: dict[str, Any], output_dir: Path) -> list[str]:
        cmd = [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(RUN_SCRIPT_PATH.resolve()),
            "-Audio",
            str(config["audio"]),
            "-OutDir",
            str(output_dir.resolve()),
            "-DatasetFormat",
            str(config.get("dataset_format", "standard")),
            "-AsrCkpt",
            resolve_ckpt_value(str(config.get("asr_ckpt", ""))),
            "-AlignerCkpt",
            resolve_ckpt_value(str(config.get("aligner_ckpt", ""))),
            "-Language",
            str(config.get("language", "None")),
            "-PuncModel",
            str(config.get("punc_model", "")),
            "-PauseThreshold",
            str(float(config.get("pause_threshold", 0.6))),
            "-MinDur",
            str(float(config.get("min_dur", 0.8))),
            "-MaxDur",
            str(float(config.get("max_dur", 8.0))),
            "-PadLeft",
            str(float(config.get("pad_left", 0.05))),
            "-PadRight",
            str(float(config.get("pad_right", 0.1))),
            "-BatchSize",
            str(int(config.get("batch_size", 1))),
            "-MaxNewTokens",
            str(int(config.get("max_new_tokens", 2048))),
            "-EtaRTF",
            str(float(config.get("eta_rtf", 2.0))),
        ]
        ref_audio = str(config.get("ref_audio", "") or "").strip()
        if ref_audio:
            cmd.extend(["-RefAudio", ref_audio])
        hotword_file = str(config.get("hotword_file", "") or "").strip()
        if hotword_file:
            cmd.extend(["-HotwordFile", hotword_file])
        else:
            hotword_library = str(config.get("hotword_library", "") or "").strip()
            if hotword_library:
                cmd.extend(["-HotwordLibrary", hotword_library])
        if bool(config.get("scan_subfolders", False)):
            cmd.append("-ScanSubfolders")
        return cmd

    def _append_log(self, handle: Any, line: str) -> None:
        handle.write(line + "\n")
        handle.flush()

    def _build_job_summary(self, job: JobRecord) -> dict[str, Any]:
        summary = dict(job.summary or {})
        if job.kind != "asr" or not job.output_dir:
            return summary
        meta_path = Path(job.output_dir) / "meta.json"
        if meta_path.exists():
            meta = read_json_file(meta_path, {})
            if isinstance(meta, dict):
                summary["meta"] = meta
                if meta.get("warning"):
                    summary["warning"] = str(meta.get("warning"))
        return summary

    def _friendly_failure_message(self, job: JobRecord, log_path: Path, exit_code: int, timed_out: bool = False) -> str:
        if timed_out:
            return f"任务运行超时（{JOB_TIMEOUT_SECONDS // 3600} 小时），已经被强制终止。请先缩小输入规模，或者先处理更短的音频。"

        tail = "\n".join(tail_lines(log_path, 120))
        lowered = tail.lower()

        rules: list[tuple[bool, str]] = [
            ("未找到虚拟环境" in tail or ".venv" in tail and "not found" in lowered, "未找到虚拟环境。你可能还没有执行初始化。请先运行 `./bootstrap.ps1`，完成后再重新提交任务。"),
            ("未找到主脚本" in tail or "asr_sentence_segment.py" in tail and "not found" in lowered, "主脚本没找到。请确认当前就是项目根目录，或者重新解压完整项目后再试。"),
            ("Audio 为空" in tail or "输入路径为空" in tail, "输入路径为空。请先保留默认的 `./inputs`，或者填写一个真实存在的音频文件 / 文件夹。"),
            ("输入路径不存在" in tail or "输入路径既不是文件也不是目录" in tail, "输入路径不对。最常见原因是盘符写错、路径复制漏了，或者文件还没放进项目里。"),
            ("目录下未找到可处理音频" in tail or "输入目录里没有找到可处理音频" in tail, "输入目录里没有可处理的音频。请把音频放进 `./inputs`，或者换成正确的音频目录。"),
            ("参考音频不存在" in tail or "RefAudio" in tail and "不存在" in tail, "参考音频路径有误。只有导出 Qwen3-TTS 清单时才需要它，不需要就留空。"),
            ("BatchSize 非法" in tail or "BatchSize 必须" in tail, "BatchSize 不能小于 1。新手建议先保持 1，跑通后再考虑调大。"),
            ("funasr" in lowered and "标点恢复" in tail, "你启用了标点恢复，但当前环境缺少 funasr。请先运行 `./bootstrap.ps1 -InstallFunASR`，再重新提交任务。"),
            ("cuda out of memory" in lowered or "out of memory" in lowered or "显存不足" in tail, "显存不足。请先把 BatchSize 调到 1，关闭其它占显存程序后再试。"),
            ("ASR 模型目录不存在" in tail or "对齐模型目录不存在" in tail, "模型目录不存在。请先运行 `./bootstrap.ps1 -DownloadModels`，或者把模型路径改成真实存在的本地目录。"),
            ("未找到 ffmpeg" in tail or "未找到 ffprobe" in tail or ("ffmpeg" in lowered and ("not found" in lowered or "not recognized" in lowered)), "未找到 ffmpeg。音频处理需要 ffmpeg / ffprobe，请先安装并确认命令行能直接运行 `ffmpeg -version`。"),
            ("端口" in tail and "占用" in tail, "端口被占用。请关闭已有 WebUI，或者启动时换一个新的端口。"),
        ]

        for matched, message in rules:
            if matched:
                return message

        if job.kind in {"bootstrap", "bootstrap_funasr"}:
            return f"依赖安装失败（退出码 {exit_code}）。请先看日志最后几行；如果是网络问题，重试通常就能恢复。"

        return f"任务失败（退出码 {exit_code}）。请先看日志最后几行，通常能直接找到原因。"

    def create_asr_job(self, raw_payload: dict[str, Any]) -> dict[str, Any]:
        config = self.get_defaults()
        for key in config:
            if key in raw_payload:
                config[key] = raw_payload[key]
        config = self.normalize_form_config(config)

        hotword_library = str(config.get("hotword_library", "") or "").strip()
        hotword_text = normalize_hotword_library_content(str(config.get("hotword_text", "") or ""))
        warnings: list[str] = []
        if hotword_library and not hotword_text:
            try:
                hotword_text = self.load_hotword_library(hotword_library)["content"]
            except FileNotFoundError:
                hotword_text = ""
                warnings.append(f"热词库不存在：{hotword_library}。本次任务会忽略这个热词库。")
        config["hotword_library"] = hotword_library
        config["hotword_text"] = hotword_text

        try:
            batch_size = int(config.get("batch_size", 1))
        except Exception as exc:
            raise ValueError("批大小必须是整数。它表示一次并行处理多少条样本，填成文字或空值都不行。") from exc
        if batch_size < 1:
            raise ValueError("批大小不能小于 1。0 表示不会处理任何样本，任务没法正常开始。")
        config["batch_size"] = batch_size

        min_dur = _coerce_optional_float(config.get("min_dur"), "min_dur")
        max_dur = _coerce_optional_float(config.get("max_dur"), "max_dur")
        pad_left = _coerce_optional_float(config.get("pad_left"), "pad_left")
        pad_right = _coerce_optional_float(config.get("pad_right"), "pad_right")
        pause_threshold = _coerce_optional_float(config.get("pause_threshold"), "pause_threshold")
        if min_dur is not None and max_dur is not None and min_dur > max_dur:
            raise ValueError(f"最短句时长不能大于最长句时长。当前 min_dur={min_dur}，max_dur={max_dur}。")
        if pad_left is not None and pad_left < 0:
            raise ValueError("左补边不能为负数。先保持 0 或用很小的正数就行。")
        if pad_right is not None and pad_right < 0:
            raise ValueError("右补边不能为负数。先保持 0 或用很小的正数就行。")
        if pause_threshold is not None and pause_threshold <= 0:
            raise ValueError("停顿阈值必须大于 0。新手一般直接用默认值即可。")

        audio_value = str(config.get("audio", "") or "").strip()
        if not audio_value:
            raise ValueError("输入路径为空。请先填写一个音频文件或文件夹，第一次建议直接用 .\\inputs。")
        audio_path = resolve_project_path(audio_value)
        if not audio_path.exists():
            raise ValueError(f"输入路径不存在：{audio_path}。最常见原因是盘符写错、文件还没放进来，或者相对路径不是项目根目录。")

        ref_audio = str(config.get("ref_audio", "") or "").strip()
        if ref_audio:
            ref_audio_path = resolve_project_path(ref_audio)
            if not ref_audio_path.exists() or not ref_audio_path.is_file():
                raise ValueError(f"参考音频不存在或不是文件：{ref_audio_path}。如果你不是在导出 Qwen3-TTS 清单，就把它留空。")

        output_mode = str(config.get("output_mode", "auto") or "auto")
        if output_mode == "custom" and str(config.get("output_dir", "") or "").strip():
            output_dir = resolve_project_path(str(config["output_dir"]))
        else:
            output_dir = build_auto_output_dir(uuid.uuid4().hex, audio_value)

        job_id = uuid.uuid4().hex
        if output_mode == "auto":
            output_dir = build_auto_output_dir(job_id, audio_value)

        long_audio_warning_minutes = _coerce_optional_float(config.get("long_audio_warning_minutes"), "long_audio_warning_minutes")
        if long_audio_warning_minutes is None:
            long_audio_warning_minutes = 120.0
        if long_audio_warning_minutes <= 0:
            raise ValueError("长音频预警阈值必须大于 0。先保持默认值即可。")
        warning_text = ""
        if warnings:
            warning_text = "；".join(warnings)
        if audio_path.is_file():
            duration = probe_audio_duration_seconds(audio_path, timeout=10)
            if duration is not None and duration / 60.0 > long_audio_warning_minutes:
                extra_warning = f"音频较长（{duration / 60.0:.1f} 分钟），处理时间可能较久"
                warning_text = f"{warning_text}；{extra_warning}".strip("；") if warning_text else extra_warning

        runtime_hotword_file = ""
        hotword_tmp_path: Path | None = None
        try:
            if hotword_text:
                runtime_path = HOTWORD_RUNTIME_ROOT / f"{job_id}.txt"
                runtime_path.write_text(hotword_text + "\n", encoding="utf-8")
                runtime_hotword_file = str(runtime_path.resolve())
                hotword_tmp_path = runtime_path

            cmd = self._build_asr_command({**config, "audio": str(audio_path), "hotword_file": runtime_hotword_file}, output_dir)
            title = str(raw_payload.get("title", "") or "").strip() or infer_title_from_audio(audio_value)
            log_path = JOB_LOG_ROOT / f"{job_id}.log"
            rec = JobRecord(
                id=job_id,
                kind="asr",
                title=title,
                status="queued",
                created_at=now_iso(),
                config={**config, "output_mode": output_mode, "hotword_entries": len(parse_hotword_entries(hotword_text))},
                command=cmd,
                output_dir=str(output_dir.resolve()),
                log_path=str(log_path.resolve()),
                warning=warning_text,
                progress_label="等待前序任务完成后开始",
            )
            with self._lock:
                self._jobs[job_id] = rec
                self._pending_ids.append(job_id)
                self._save_jobs()
                self._queue.put(job_id)
        except Exception:
            with self._lock:
                self._jobs.pop(job_id, None)
                self._pending_ids = [x for x in self._pending_ids if x != job_id]
                self._cancelled_job_ids.discard(job_id)
            if hotword_tmp_path is not None:
                self._cleanup_hotword_runtime_file(job_id)
            raise
        return self.get_job(job_id)

    def create_maintenance_job(self, kind: str) -> dict[str, Any]:
        if kind not in {"bootstrap", "download_models", "bootstrap_funasr", "self_check"}:
            raise ValueError(f"不支持的维护任务类型：{kind}")
        job_id = uuid.uuid4().hex
        log_path = JOB_LOG_ROOT / f"{job_id}.log"
        if kind == "bootstrap":
            title = "安装基础依赖"
            cmd = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(BOOTSTRAP_SCRIPT_PATH.resolve())]
        elif kind == "download_models":
            title = "下载模型"
            cmd = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(BOOTSTRAP_SCRIPT_PATH.resolve()), "-DownloadModels"]
        elif kind == "bootstrap_funasr":
            title = "补装 FunASR"
            cmd = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(BOOTSTRAP_SCRIPT_PATH.resolve()), "-InstallFunASR"]
        else:
            title = "环境自检"
            cmd = [str(VENV_PYTHON_PATH.resolve()), str(SELF_CHECK_SCRIPT_PATH.resolve())]
        rec = JobRecord(id=job_id, kind=kind, title=title, status="queued", created_at=now_iso(), command=cmd, log_path=str(log_path.resolve()), progress_label="等待前序任务完成后开始")
        with self._lock:
            self._jobs[job_id] = rec
            self._pending_ids.append(job_id)
            self._save_jobs()
            self._queue.put(job_id)
        return self.get_job(job_id)

    def clone_job(self, job_id: str) -> dict[str, Any]:
        with self._lock:
            old = self._jobs.get(job_id)
            if not old:
                raise KeyError(job_id)
            kind = old.kind
            payload = dict(old.config) if kind == "asr" else None
            title = old.title
        if kind == "asr":
            assert payload is not None
            payload["title"] = f"重试 - {title}"
            if not str(payload.get("punc_model", "") or "").strip():
                # 旧任务可能保存的是空 punc_model；重试时按当前默认策略补上标点模型，避免再次输出无标点文本。
                payload["punc_model"] = self.get_base_defaults()["punc_model"]
            output_mode = str(payload.get("output_mode", "auto") or "auto").strip()
            output_dir = str(payload.get("output_dir", "") or "").strip()
            if output_mode == "custom" and output_dir:
                payload["output_dir"] = build_retry_output_dir(output_dir)
            return self.create_asr_job(payload)
        return self.create_maintenance_job(kind)

    def cancel_job(self, job_id: str) -> dict[str, Any]:
        process: subprocess.Popen[str] | None = None
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                raise KeyError(job_id)
            if job.status not in ("queued", "running"):
                raise ValueError("只能取消排队中或运行中的任务")
            job.status = "failed"
            job.error = "用户手动取消"
            job.finished_at = datetime.now().astimezone().isoformat()
            job.progress_label = "任务已被用户取消"
            job.progress_value = min(float(job.progress_value), 99.0)
            self._cancelled_job_ids.add(job_id)
            if job_id in self._pending_ids:
                self._pending_ids = [x for x in self._pending_ids if x != job_id]
            if self._process and self._running_job_id == job_id:
                process = self._process
                self._running_job_id = None
            self._save_jobs()
        if process is not None:
            self._terminate_process_tree(process)
        self._cleanup_hotword_runtime_file(job_id)
        return {"job": self.get_job(job_id)}

    def _should_persist_progress(self, job: JobRecord) -> bool:
        if time.time() - self._last_save_time >= PROGRESS_SAVE_INTERVAL_SECONDS:
            return True
        last = self._last_saved_progress.get(job.id, float(job.progress_value))
        return abs(float(job.progress_value) - float(last)) >= PROGRESS_SAVE_DELTA_PERCENT

    def _update_progress_from_line(self, job_id: str, line: str) -> None:
        batch_pattern = re.search(r"\[(\d+)/(\d+)\]", line)
        step_pattern = re.search(r"(?:步骤|step)\s*(\d+)\s*/\s*(\d+)", line, flags=re.IGNORECASE)
        percent_pattern = re.search(r"(?:进度约|progress)\s*(\d+)%", line, flags=re.IGNORECASE)
        with self._lock:
            job = self._jobs.get(job_id)
            if not job or job.status != "running":
                return
            old_progress = float(job.progress_value)
            old_label = str(job.progress_label)
            if step_pattern:
                idx = int(step_pattern.group(1))
                total = max(1, int(step_pattern.group(2)))
                if "完成" in line:
                    p = idx / total * 100.0
                elif percent_pattern:
                    inner = int(percent_pattern.group(1)) / 100.0
                    p = (idx - 1 + inner) / total * 100.0
                else:
                    p = max(old_progress, (idx - 1) / total * 100.0)
                job.progress_value = max(old_progress, min(p, 99.0))
                job.progress_label = line.strip()
            elif batch_pattern and job.kind == "asr":
                cur = int(batch_pattern.group(1))
                total = max(1, int(batch_pattern.group(2)))
                p = cur / total * 100.0 if "完成" in line else max(old_progress, (cur - 1) / total * 100.0)
                job.progress_value = max(old_progress, min(p, 99.0))
                job.progress_label = line.strip()
            elif line.strip():
                job.progress_label = line.strip()
            changed = abs(float(job.progress_value) - old_progress) > 1e-6 or str(job.progress_label) != old_label
            if changed and self._should_persist_progress(job):
                self._save_jobs()

    def _run_job(self, job_id: str) -> None:
        with self._lock:
            if job_id in self._pending_ids:
                self._pending_ids.remove(job_id)
            job = self._jobs.get(job_id)
            if not job:
                self._cancelled_job_ids.discard(job_id)
                return
            if job.status != "queued":
                self._cancelled_job_ids.discard(job_id)
                self._save_jobs()
                return
            self._running_job_id = job_id
            job.status = "running"
            job.started_at = now_iso()
            job.progress_value = 2.0
            job.progress_label = "任务已经启动，正在准备执行环境"
            self._save_jobs()

        log_path = Path(job.log_path)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        env = os.environ.copy()
        env["PYTHONUTF8"] = "1"
        process: subprocess.Popen[str] | None = None

        try:
            with log_path.open("a", encoding="utf-8") as log_handle:
                self._append_log(log_handle, f"[webui] {job.title} 已加入执行器")
                self._append_log(log_handle, f"[webui] 启动时间：{job.started_at}")
                self._append_log(log_handle, f"[webui] 执行命令：{' '.join(job.command)}")
                if job.output_dir:
                    self._append_log(log_handle, f"[webui] 结果目录：{job.output_dir}")
                try:
                    process = subprocess.Popen(job.command, cwd=str(PROJECT_ROOT.resolve()), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace", env=env)
                except Exception as exc:
                    with self._lock:
                        job.status = "failed"
                        job.finished_at = now_iso()
                        job.error = f"任务启动失败：{exc}"
                        job.progress_label = "任务启动失败"
                        job.exit_code = -1
                        self._running_job_id = None
                        self._save_jobs()
                    self._append_log(log_handle, f"[webui] 启动失败：{exc}")
                    return
                with self._lock:
                    self._process = process

                def _read_output() -> None:
                    assert process is not None
                    if process.stdout is None:
                        return
                    for raw in process.stdout:
                        line = raw.rstrip("\n")
                        self._append_log(log_handle, line)
                        self._update_progress_from_line(job_id, line)

                reader = threading.Thread(target=_read_output, name=f"job-log-reader-{job_id[:8]}", daemon=True)
                reader.start()
                timed_out = False
                try:
                    exit_code = process.wait(timeout=JOB_TIMEOUT_SECONDS)
                except subprocess.TimeoutExpired:
                    timed_out = True
                    self._append_log(log_handle, f"[webui] 任务超时（{JOB_TIMEOUT_SECONDS // 3600}小时），已强制终止进程")
                    self._terminate_process_tree(process)
                    try:
                        exit_code = process.wait(timeout=30)
                    except subprocess.TimeoutExpired:
                        exit_code = process.poll()
                        if exit_code is None:
                            exit_code = -1
                reader.join(timeout=5)

                with self._lock:
                    self._process = None
                    latest = self._jobs.get(job_id)
                    if not latest:
                        self._running_job_id = None
                        self._cancelled_job_ids.discard(job_id)
                        self._save_jobs()
                        return
                    cancelled = latest.error == "用户手动取消" or job_id in self._cancelled_job_ids
                    if cancelled:
                        latest.status = "failed"
                        latest.finished_at = now_iso()
                        latest.exit_code = exit_code
                        latest.progress_label = "任务已取消"
                    elif timed_out:
                        latest.status = "failed"
                        latest.finished_at = now_iso()
                        latest.exit_code = exit_code
                        latest.error = self._friendly_failure_message(latest, log_path, exit_code, timed_out=True)
                        latest.progress_label = "任务超时，已强制终止"
                        latest.progress_value = min(float(latest.progress_value), 99.0)
                    elif exit_code == 0:
                        latest.status = "success"
                        latest.finished_at = now_iso()
                        latest.exit_code = exit_code
                        latest.error = ""
                        latest.progress_value = 100.0
                        latest.progress_label = "任务成功完成"
                        latest.summary = self._build_job_summary(latest)
                        self._invalidate_results_cache()
                    else:
                        latest.status = "failed"
                        latest.finished_at = now_iso()
                        latest.exit_code = exit_code
                        latest.error = self._friendly_failure_message(latest, log_path, exit_code)
                        latest.progress_label = "任务执行失败，请看日志提示"
                        latest.progress_value = min(float(latest.progress_value), 98.0)
                    self._running_job_id = None
                    self._cancelled_job_ids.discard(job_id)
                    self._save_jobs()
        finally:
            with self._lock:
                if self._running_job_id == job_id:
                    self._running_job_id = None
                if self._process is process:
                    self._process = None
            self._cleanup_hotword_runtime_file(job_id)

    def _worker_loop(self) -> None:
        while True:
            job_id = self._queue.get()
            self._run_job(job_id)
            self._queue.task_done()

    def _result_dirs_for_root(self, output_root: Path) -> list[Path]:
        root = output_root.resolve()
        if not root.exists():
            return []
        found: dict[str, Path] = {}
        if (root / "meta.json").exists():
            found[str(root)] = root
        for meta_path in root.rglob("meta.json"):
            found[str(meta_path.parent.resolve())] = meta_path.parent.resolve()
        return sorted(found.values(), key=lambda p: p.stat().st_mtime, reverse=True)

    def _summarize_result_dir(self, run_dir: Path) -> dict[str, Any]:
        meta = read_json_file(run_dir / "meta.json", {})
        warning = str(meta.get("warning", "") or "") if isinstance(meta, dict) else ""
        preview = ""
        # 兼容新旧结果目录：优先读取 full_text.txt，旧目录回退到 text.txt。
        for txt in (run_dir / "full_text.txt", run_dir / "text.txt"):
            if not txt.exists():
                continue
            try:
                preview = txt.read_text(encoding="utf-8", errors="replace").strip()[:300]
                break
            except OSError:
                preview = ""
        return {
            "id": make_result_id(run_dir),
            "run_dir": str(run_dir.resolve()),
            "relative_run_dir": str(run_dir.resolve().relative_to(PROJECT_ROOT.resolve())) if PROJECT_ROOT.resolve() in run_dir.resolve().parents else str(run_dir.resolve()),
            "updated_at": datetime.fromtimestamp(run_dir.stat().st_mtime).astimezone().isoformat(),
            "title": str(meta.get("title", run_dir.name)) if isinstance(meta, dict) else run_dir.name,
            "warning": warning,
            "meta": meta if isinstance(meta, dict) else {},
            "preview": preview,
        }

    def _summaries_for_output_root(self, output_root: Path) -> list[dict[str, Any]]:
        return [self._summarize_result_dir(p) for p in self._result_dirs_for_root(output_root)]

    def list_results(self, refresh: bool = False) -> list[dict[str, Any]]:
        if not refresh and self._results_cache is not None and (time.time() - self._results_cache_time) < RESULTS_CACHE_TTL_SECONDS:
            return list(self._results_cache)
        roots: dict[str, Path] = {str(WEBUI_OUTPUT_ROOT.resolve()): WEBUI_OUTPUT_ROOT.resolve()}
        with self._lock:
            for job in self._jobs.values():
                if job.kind == "asr" and job.output_dir:
                    p = Path(job.output_dir).resolve()
                    roots[str(p)] = p
        found: dict[str, dict[str, Any]] = {}
        for root in roots.values():
            for row in self._summaries_for_output_root(root):
                found[row["id"]] = row
        rows = sorted(found.values(), key=lambda x: x["updated_at"], reverse=True)
        self._results_cache = list(rows)
        self._results_cache_time = time.time()
        return list(rows)

    def get_result(self, result_id: str) -> dict[str, Any]:
        summary = next((x for x in self.list_results(refresh=False) if x["id"] == result_id), None)
        if not summary:
            raise KeyError(result_id)
        run_dir = Path(summary["run_dir"]).resolve()
        meta = read_json_file(run_dir / "meta.json", {})
        artifacts = []
        for p in sorted(run_dir.rglob("*")):
            if p.is_file():
                artifacts.append({"name": p.name, "relative_path": str(p.relative_to(run_dir)).replace("\\", "/"), "size": p.stat().st_size, "media_type": guess_media_type(p)})
        detail = dict(summary)
        detail["meta"] = meta if isinstance(meta, dict) else {}
        detail["warning"] = str(detail["meta"].get("warning", "") or detail.get("warning", ""))
        detail["artifacts"] = artifacts
        return detail

    def resolve_result_artifact(self, result_id: str, relative_path: str) -> Path:
        result = self.get_result(result_id)
        run_dir = Path(result["run_dir"]).resolve()
        target = (run_dir / relative_path).resolve()
        if target != run_dir and run_dir not in target.parents:
            raise PermissionError("仅允许读取结果目录内文件")
        if not target.exists() or not target.is_file():
            raise FileNotFoundError(str(target))
        return target

    def export_qwen3_tts_dataset(self, result_id: str, ref_audio: str | None = None, output_dir: str | None = None) -> dict[str, Any]:
        result = self.get_result(result_id)
        run_dir = Path(result["run_dir"]).resolve()
        dst_root = resolve_project_path(output_dir or str(run_dir / "exports"))
        dst_root.mkdir(parents=True, exist_ok=True)
        dst = dst_root / f"{run_dir.name}_qwen3_tts.jsonl"
        src_q = run_dir / "qwen3_tts.jsonl"
        src_i = run_dir / "index.jsonl"
        count = 0
        if src_q.exists():
            lines = src_q.read_text(encoding="utf-8", errors="replace").splitlines()
            with dst.open("w", encoding="utf-8") as out:
                for line in lines:
                    line = line.strip()
                    if not line:
                        continue
                    payload = json.loads(line)
                    if ref_audio:
                        payload["ref_audio"] = str(ref_audio)
                    out.write(json.dumps(payload, ensure_ascii=False) + "\n")
                    count += 1
        elif src_i.exists():
            lines = src_i.read_text(encoding="utf-8", errors="replace").splitlines()
            with dst.open("w", encoding="utf-8") as out:
                for line in lines:
                    line = line.strip()
                    if not line:
                        continue
                    payload = json.loads(line)
                    # index.jsonl 是标准分段索引，音频字段名叫 wav；
                    # qwen3_tts.jsonl 才使用 audio 字段。这里两个都兼容，避免从旧结果二次导出时音频路径为空。
                    row = {"audio": payload.get("audio") or payload.get("wav", ""), "text": payload.get("text", "")}
                    if ref_audio:
                        row["ref_audio"] = str(ref_audio)
                    out.write(json.dumps(row, ensure_ascii=False) + "\n")
                    count += 1
        else:
            raise FileNotFoundError(f"未找到可导出清单：{src_q} / {src_i}")
        self._invalidate_results_cache()
        return {"result_id": result_id, "output": str(dst.resolve()), "records": count}

    def open_path_in_explorer(self, raw_path: str) -> None:
        target = Path(raw_path).expanduser().resolve()
        allowed_roots = [PROJECT_ROOT.resolve(), WEBUI_OUTPUT_ROOT.resolve()]
        with self._lock:
            for job in self._jobs.values():
                if job.output_dir:
                    allowed_roots.append(Path(job.output_dir).resolve())
        if not _path_is_within_any_root(target, allowed_roots):
            cached_results = list(self._results_cache or [])
            for item in cached_results:
                run_dir = str(item.get("run_dir", "") or "").strip()
                if run_dir:
                    allowed_roots.append(Path(run_dir).resolve())
            if not _path_is_within_any_root(target, allowed_roots):
                try:
                    cached_results = self.list_results(refresh=False)
                except OSError:
                    cached_results = []
                for item in cached_results:
                    run_dir = str(item.get("run_dir", "") or "").strip()
                    if run_dir:
                        allowed_roots.append(Path(run_dir).resolve())
        if not _path_is_within_any_root(target, allowed_roots):
            raise PermissionError("只允许打开项目内路径、当前任务输出目录和结果目录")
        if not target.exists():
            raise FileNotFoundError(str(target))
        subprocess.Popen(["explorer", str(target)])


ensure_runtime_dirs()
manager = JobManager()
