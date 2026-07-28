# CODEX Project Manifest

## 1. 文档元信息

| 元数据项 | 值 |
|---|---|
| 项目名称 | Qwen3-ASR（Qwen3 Audio Speech Recognition） |
| 当前项目版本 | v0.1.0（基线版本，程序元数据中尚未硬编码） |
| 文档格式版本 | 1.0 |
| 创建时间 | 2026-07-20 |
| 最后更新时间 | 2026-07-20 |
| 当前 Git 分支 | `main` |
| 当前 Git Commit | `45a1b7942c982bd9b5183d60d6fb07326286d400` |
| Git 工作区状态 | 仅存在一个未跟踪文件 `CODEX_PROJECT_MANIFEST.md`，其余干净 |
| 版本信息来源 | 未发现已发布的版本标签；`webui/app.py:122` FastAPI 中标注 `version="1.0.0"` 作为 WebUI 版本 |
| 文档可信状态 | VERIFIED |
| 最后验证人或执行者 | OpenCode Agent（自动分析） |
| 当前总体状态 | 项目可运行，核心流程完整，为个人/小团队使用级别的成熟度 |

## 2. 项目概述

### 项目用途
Qwen3-ASR 是一个本地运行的、基于 Qwen3-ASR 模型的离线音频转写（ASR）+ 强制对齐（Forced Alignment）+ 句子级切分（Sentence Segmentation）工具。它将长音频文件自动识别为文字，按句子边界切割为独立音频片段，并导出标准化的索引文件和可选的 Qwen3-TTS 微调数据集。

### 目标用户
- 需要将长音频（播客、配音、有声书、游戏语音等）转为文字并切割句子的内容创作者
- 准备 Qwen3-TTS 微调数据集的数据准备人员
- 对音频/语音处理感兴趣的本地开发者

### 核心问题
将长音频自动识别、时间戳对齐、并按自然语义边界切割为独立的句子级片段，同时保持文本和音频片段的严格对应。

### 主要能力
1. 接收各种常见音频格式（通过 ffmpeg 转码）
2. 使用 Qwen3-ASR 模型进行语音转文字，附带字符级时间戳（通过 Qwen3-ForcedAligner）
3. 可选的标点恢复（通过 FunASR）
4. 基于停顿阈值和句长约束的贪心分句算法
5. 导出切分后的 wav/txt 片段和 index.jsonl 清单
6. 可选的 Qwen3-TTS 微调数据集导出格式
7. 热词提示（通过识别上下文注入）
8. 批处理支持（自动处理目录下所有音频）
9. GPU 显存安全预检和自动 CPU 回退
10. WebUI 图形界面（通过 FastAPI + 静态前端）
11. 任务队列管理和历史结果浏览
12. 配置保存/加载功能
13. 环境自检脚本

### 使用方式
- **CLI 命令行**：`./run_cli.bat` 或 `./run.ps1` 配合参数
- **WebUI 网页**：双击 `run_webui.bat` 或执行 `./start_webui.ps1`
- **Python 直接调用**：`python scripts/asr_sentence_segment.py --audio <file>`

### 当前阶段
项目的核心 ASR + 对齐 + 分句管线已完全可用。WebUI 前端/后端功能完整，有基本的自动化测试覆盖。当前处于"功能完整、持续优化"阶段。

### 已实现范围
- 完整的离线 ASR + 对齐 + 分句管线
- WebUI 图形界面（任务提交、队列管理、结果浏览）
- 标点恢复（可选）
- 热词提示
- GPU 显存安全预检
- 自动 batch_size 降级和 CPU 回退
- 配置文件保存/加载
- 环境自检和自动 bootstrap 安装
- 单元测试覆盖核心纯函数
- 部署打包脚本

### 未实现范围
- 尚未集成音频播放器（见 `P0-3-webui-audio-player.md`）
- 无实时流式 ASR
- 无多语言自动切换（需手动指定）
- 无分布式/多 GPU 支持
- 无 Docker 容器化部署
- 无 CI/CD 自动化流水线
- 无在线更新/版本检查机制
- 非 Windows 平台的安装脚本不完善（项目明确为 Windows 设计）

### 项目边界
- 本项目是**纯本地离线工具**，不依赖任何外部 API 服务
- 所有依赖（模型、ffmpeg、Python 包）均可通过 `bootstrap.ps1` 自动下载安装
- 缓存目录全部在项目 `.cache/` 下，不污染系统目录
- 仅支持 Windows 平台（基于 PowerShell 脚本构建）；macOS/Linux 需手动适配

## 3. 当前开发进度

### 已完成
- ASR 音频转写管线（脚本 `scripts/asr_sentence_segment.py`）
- 字符级时间戳扩展和对齐
- 贪心分句算法（包含强边界/软边界/停顿/硬切四级策略）
- 标点恢复集成（FunASR CT-Transformer）
- 标点正文改动检测和安全降级
- 标点文本到时间线的合并
- wav/txt 分段导出和 index.jsonl 清单生成
- Qwen3-TTS 数据集清单导出
- 热词加载和上下文注入
- ffmpeg 音频转码（16k mono wav）
- ffprobe 音频信息探测
- GPU 显存安全预检
- CUDA OOM 自动降级（batch_size 1 → CPU）
- WebUI 全套（FastAPI + 静态 SPA）
- 任务队列管理（排队→运行→完成/失败）
- 任务进度解析和实时日志
- 配置/偏好保存、加载、管理
- 热词库管理（保存、加载、编辑）
- 环境自检脚本（`scripts/self_check.py`）
- 完整的 bootstrap 自动安装脚本（venv、pip 依赖、ffmpeg、模型下载）
- WebUI 启动自动检查/修复机制
- 部署打包脚本（`package_for_deploy.ps1`）
- 测试覆盖核心纯函数和 WebUI 契约

### 部分完成
- WebUI 音频播放器（功能需求已文档化 `P0-3-webui-audio-player.md`，尚未实现）
- 结果目录的文本预览和摘要（已有基础功能，但可扩展）

### 正在开发
- 无（当前为维护期，功能完整）

### 尚未开始
- CI/CD 自动化
- Docker 容器化
- macOS/Linux 跨平台支持
- 实时流式 ASR
- 音频播放器组件（WebUI）

### 已废弃
- 无明确废弃的代码

### 当前阻断项
- 无

## 4. 系统架构

### 组件说明

```
┌─────────────────────────────────────────────────────────────┐
│                        Qwen3-ASR                              │
│                                                               │
│  ┌─────────┐    ┌──────────────────┐    ┌──────────────────┐ │
│  │ 用户界面 │───▶│   运行控制层     │───▶│   ASR 核心管线   │ │
│  │         │    │                  │    │                  │ │
│  │ run.ps1 │    │ run.ps1 (PS)     │    │ asr_sentence_    │ │
│  │ run_    │    │ bootstrap.ps1    │    │ segment.py       │ │
│  │ webui   │    │ start_webui.ps1  │    │                  │ │
│  │ .bat    │    │ webui/service.py │    │ - 音频转码       │ │
│  │         │    │                  │    │ - 模型加载       │ │
│  │ WebUI   │    │ 配置管理         │    │ - ASR 推理       │ │
│  │ 浏览器  │    │ 任务队列         │    │ - 时间戳提取     │ │
│  └─────────┘    │ 日志管理         │    │ - 标点恢复       │ │
│                 └──────────────────┘    │ - 贪心分句       │ │
│                                         │ - 音频/文本导出  │ │
│                                         └──────────────────┘ │
│                                                               │
│  ┌────────────────┐   ┌──────────────┐   ┌──────────────────┐│
│  │ 共享库          │   │ 配置文件      │   │ 外部工具         ││
│  │ shared.py      │   │ defaults.json│   │ ffmpeg/ffprobe  ││
│  │ - 项目根路径   │   │ WebUI 配置   │   │ nvidia-smi       ││
│  │ - 分句默认值   │   │ 热词库       │   │ PowerShell       ││
│  └────────────────┘   └──────────────┘   └──────────────────┘│
│                                                               │
│  ┌─────────────────────────────────────────────────────────┐  │
│  │ 模型 (Qwen3-ASR-1.7B + Qwen3-ForcedAligner-0.6B)       │  │
│  │ qwen_asr 库 │ transformers │ torch │ funasr            │  │
│  └─────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

### 模块关系

```
shared.py  ────────── 供给 read_split_defaults()
    │
    ├── asr_sentence_segment.py (import shared)
    │         │
    │         ├── run.ps1 (PowerShell → Python subprocess)
    │         ├── webui/service.py (通过 subprocess 启动 run.ps1)
    │         └── 直接 CLI: python scripts/asr_sentence_segment.py --audio ...
    │
    └── webui/service.py (import shared)
              │
              ├── webui/app.py (FastAPI, import service.manager)
              ├── webui/static/index.html (前端 SPA)
              ├── webui/static/app.js (AJAX 调用后端 API)
              └── webui/static/styles.css (界面样式)
```

### 调用链

**CLI 模式：**
```
用户 → run_cli.bat → run.ps1 → 调用 scripts/asr_sentence_segment.py (Python)
   → ffmpeg 转码 → 加载 Qwen3-ASR 模型 → ASR 推理 + 对齐 → 标点恢复（可选）
   → 贪心分句 → 导出 wav/txt/jsonl → 输出到 outputs/ 目录
```

**WebUI 模式：**
```
用户 → run_webui.bat → start_webui.ps1 (环境检查 + 自修复)
   → uvicorn webui/app.py (FastAPI)
   → 浏览器访问 http://127.0.0.1:8765
   → app.js 通过 REST API 与后端交互
   → 提交任务 → service.JobManager 创建 JobRecord
   → 后台工作线程按顺序执行 subprocess(run.ps1 ...)
   → run.ps1 调用 asr_sentence_segment.py
   → 结果输出到 outputs/webui_runs/
   → WebUI 轮询任务状态，完成后展示结果
```

### 数据流

```
音频文件 (.wav/.mp3/.aac/...)
    │
    ▼
ffmpeg 转码 ──▶ 16k 单声道 wav
    │
    ▼
split_wav_for_asr() ──▶ 音频分块（默认 60 秒一块）
    │
    ▼
model.transcribe() ──▶ 每块 ASR 推理 + 强制对齐
    │                      └── 返回 text + time_stamps
    ▼
parse_unit_timestamps() ──▶ 解析字符级时间戳单元
    │
    ▼
expand_units_to_char_timeline() ──▶ CharStamp 时间线
    │
    ▼  (可选)
apply_punctuation() ──▶ 标点恢复 → merge_punc_text_to_timeline()
    │
    ▼
greedy_sentence_split() ──▶ 句子边界切分
    │                         ├── 优先级：强边界 > 软边界 > 停顿 > 硬切
    │                         ├── min_dur / max_dur 约束
    │                         └── 收尾短段合并
    ▼
write_segments_and_index() ──▶ 导出切片
    │                           ├── segments/*.wav
    │                           ├── segments/*.txt
    │                           ├── index.jsonl
    │                           ├── full_text.txt
    │                           └── meta.json
    ▼ (可选)
export_qwen3_tts_manifest() ──▶ qwen3_tts.jsonl
```

### 外部服务
- 无（全部离线运行）
- 模型来源：Hugging Face 或 ModelScope（下载后本地使用）
- ffmpeg：从 gyan.dev 自动下载便携版

### 运行进程

| 进程 | 用途 | 端口 |
|---|---|---|
| Python (`asr_sentence_segment.py`) | ASR 管线主进程 | 无 |
| PowerShell (`run.ps1`) | CLI 包装器/参数验证 | 无 |
| uvicorn (`webui/app.py`) | WebUI 后端服务 | 8765（默认） |
| 浏览器 | WebUI 前端 | N/A |
| ffmpeg/ffprobe (subprocess) | 音频转码和探测 | 无 |
| nvidia-smi (subprocess) | 显存信息查询 | 无 |

### 网络端口

| 端口 | 服务 | 绑定地址 | 用途 |
|---|---|---|---|
| 8765（默认） | FastAPI WebUI | 127.0.0.1 | 前端 SPA + REST API |

### 持久化方式

| 数据 | 存储路径 | 格式 |
|---|---|---|
| 任务队列 | `.cache/webui/jobs.json` | JSON |
| 用户偏好 | `.cache/webui/preferences.json` | JSON |
| 默认配置名 | `.cache/webui/default_config.json` | JSON |
| WebUI 日志 | `.cache/webui/logs/{job_id}.log` | 文本 |
| WebUI 任务输出 | `outputs/webui_runs/{timestamp}__{name}__{id}/` | 目录 |
| CLI 任务输出 | `outputs/run_{timestamp}/` | 目录 |
| WebUI 配置文件 | `configs/webui/*.json` | JSON |
| 热词库 | `configs/hotwords/*.txt` | 文本 |
| 分句默认值 | `configs/defaults.json` | JSON |
| 模型缓存 | `.cache/hf/hub/` | Hugging Face 缓存 |
| ASR 模型权重 | `models/Qwen3-ASR-1.7B/` | 模型文件 |
| 对齐模型权重 | `models/Qwen3-ForcedAligner-0.6B/` | 模型文件 |

## 5. 技术栈与运行环境

| 类型 | 技术 | 版本 | 用途 | 版本来源 | 实际验证 |
|---|---|---|---|---|---|
| 语言 | Python | >= 3.10 | 主编程语言 | pyproject.toml + self_check.py | NOT_RUN |
| 深度学习框架 | PyTorch | 2.6.0 | 模型推理框架 | bootstrap.ps1 | NOT_RUN |
| ASR 库 | qwen-asr | 未固定 | Qwen3-ASR 模型加载和推理 | requirements.txt | NOT_RUN |
| ASR 模型 | Qwen/Qwen3-ASR-1.7B | 1.7B 参数 | 语音转文字模型 | bootstrap.ps1 默认参数 | NOT_RUN |
| 对齐模型 | Qwen/Qwen3-ForcedAligner-0.6B | 0.6B 参数 | 字符级时间戳生成 | bootstrap.ps1 默认参数 | NOT_RUN |
| 标点恢复 | FunASR / CT-Transformer | 未固定 | 识别文本标点恢复 | requirements.txt | NOT_RUN |
| 音频处理 | soundfile | 未固定 | 读取 wav 音频文件信息 | requirements.txt | NOT_RUN |
| 后端框架 | FastAPI | 未固定 | WebUI REST API | requirements.txt | NOT_RUN |
| ASGI 服务器 | uvicorn | 未固定 | FastAPI 运行服务器 | requirements.txt | NOT_RUN |
| 模型下载 | huggingface_hub | 未固定 | 从 Hugging Face 下载模型 | requirements.txt | NOT_RUN |
| 模型下载 | modelscope | 未固定 | 从 ModelScope 下载模型（可选） | requirements.txt | NOT_RUN |
| 音频工具 | ffmpeg/ffprobe | 最新（自动下载） | 音频格式转码和元信息探测 | bootstrap.ps1 | NOT_RUN |
| 包管理器 | pip | 系统自带 | Python 依赖安装 | 无 | NOT_RUN |
| 前端 | HTML/CSS/JS | 标准 | WebUI 单页应用 | 源代码 | NOT_RUN |
| 测试 | pytest | 未固定 | 单元测试和集成测试 | requirements-dev.txt | NOT_RUN |
| 测试 | httpx | 未固定 | FastAPI TestClient HTTP 模拟 | requirements-dev.txt | NOT_RUN |
| 静态检查 | ruff | 未固定 | Lint 和格式化 | pyproject.toml + requirements-dev.txt | NOT_RUN |
| 类型检查 | mypy | 未固定 | 可选的静态类型检查 | requirements-dev.txt | NOT_RUN |
| 操作系统 | Windows | 10/11 | 目标运行平台 | 脚本设计（PowerShell/bat） | NOT_RUN |
| GPU | NVIDIA CUDA | 自动检测 | GPU 加速推理 | bootstrap.ps1 auto 模式 | NOT_RUN |
| 脚本引擎 | PowerShell | 5.1+ | 安装/启动/运行脚本 | bat 脚本调用 | NOT_RUN |

## 6. 项目目录树

```
E:\models\Qwen3-ASR\              ← 项目根目录
│
├── .editorconfig                 # 编辑器格式规范
├── .gitattributes                # Git 属性配置
├── .gitignore                    # Git 忽略规则
├── pyproject.toml                # Python 项目工具配置（ruff/pytest/mypy）
├── requirements.txt              # 运行依赖
├── requirements-dev.txt          # 开发/质量检查依赖
│
├── env.ps1                       # 环境变量加载脚本（缓存目录/ffmpeg PATH）
├── bootstrap.ps1                 # 全自动环境安装脚本（venv/ffmpeg/模型）
├── bootstrap.bat                 # bootstrap.ps1 的 cmd 双击入口
├── run.ps1                       # CLI 主运行脚本（参数处理/调用 ASR 管线）
├── run_cli.bat                   # run.ps1 的 cmd 双击入口
├── run_webui.bat                 # WebUI 启动的 cmd 双击入口
├── start_webui.ps1               # WebUI 总启动脚本（环境检查/修复/启动）
├── package_for_deploy.ps1        # 部署包打包脚本
│
├── README.md                     # 项目说明文档
├── TROUBLESHOOTING_AND_OPTIMIZATION_REPORT.md  # 故障排查和优化报告
├── P0-3-webui-audio-player.md    # WebUI 音频播放器功能需求文档
│
├── CODEX_PROJECT_MANIFEST.md     # 本文件 - 项目全景档案（未跟踪）
│
├── scripts/
│   ├── shared.py                 # 共享常量和工具函数
│   ├── asr_sentence_segment.py   # ASR 管线主程序（核心逻辑）
│   └── self_check.py             # 环境自检脚本
│
├── webui/
│   ├── __init__.py               # WebUI 包入口
│   ├── app.py                    # FastAPI 应用（路由/API 端点）
│   ├── service.py                # WebUI 后端服务（JobManager/配置管理）
│   └── static/
│       ├── index.html            # WebUI 首页（SPA 入口）
│       ├── app.js                # WebUI 前端逻辑（AJAX 状态管理）
│       ├── styles.css            # WebUI 样式
│       └── favicon.svg           # 网页图标
│
├── configs/
│   ├── defaults.json             # 分句参数默认值（集中管理）
│   ├── webui/
│   │   ├── current_workflow.json # 通用 WebUI 配置文件
│   │   └── qwen3_tts_finetune.json # Qwen3-TTS 微调场景预设
│   └── hotwords/
│       ├── luo_zheng_ling.txt    # 洛天依/天依热词库
│       └── Nikki.txt             # 暖暖/大喵热词库
│
├── tests/
│   ├── test_shared.py            # 共享库测试
│   ├── test_asr_sentence.py      # ASR 管线纯函数测试
│   └── test_webui_contracts.py   # WebUI 前后端契约测试
│
├── inputs/                       # 输入音频目录（用户放入待处理文件）
│   └── (*.aac, *.wav, ...)
│
├── outputs/                      # 输出目录（CLI 和 WebUI 结果）
│   ├── run_{timestamp}/
│   └── webui_runs/
│
├── models/                       # 本地模型权重
│   ├── Qwen3-ASR-1.7B/
│   └── Qwen3-ForcedAligner-0.6B/
│
├── .venv/                        # Python 虚拟环境（by bootstrap.ps1）
├── .cache/                       # 运行时缓存（HF/torch/pip/模型/tmp）
├── .tools/                       # 自动下载的外部工具（ffmpeg）
│
├── asr_output/                   # （用户自定义输出目录，gitignored）
└── .pytest_cache/
    .mypy_cache/
    .ruff_cache/
    .playwright-cli/              # （缓存/临时，均已 gitignored）
```

**排除的子目录内容：** `.venv/`、`.cache/`、`.tools/`、`__pycache__/`、`.pytest_cache/`、`.mypy_cache/`、`.ruff_cache/`、`.playwright-cli/` 的内部文件为自动生成或第三方依赖，不逐一说明。

**Git 忽略（`.gitignore`）：** `.venv/`、`.cache/`、`.tools/`、`.playwright-cli/`、`outputs/`、`asr_output/`、`models/`、`inputs/`、`__pycache__/`、`*.pyc`、`*.log`、`*.zip`、缓存目录、编译产物。

## 7. 目录职责说明

| 目录 | 职责 | 包含内容 | 与其他目录关系 | 核心路径 | 修改风险 |
|---|---|---|---|---|---|
| `scripts/` | ASR 管线核心代码和共享工具 | `shared.py`、`asr_sentence_segment.py`、`self_check.py` | `shared.py` 被 `asr_sentence_segment.py` 和 `webui/service.py` 导入 | 是 | 高（核心逻辑） |
| `webui/` | WebUI 后端和前端静态文件 | `__init__.py`、`app.py`、`service.py`、`static/` | `service.py` 导入 `shared.py`；`app.py` 依赖 `service.py` | 是 | 高（前端交互） |
| `configs/` | 所有可配置的 JSON/TXT 数据 | `defaults.json`、`webui/*.json`、`hotwords/*.txt` | 被 `shared.py`、`webui/service.py`、`run.ps1` 读取 | 是 | 中（修改影响默认行为） |
| `tests/` | 自动化测试 | `test_shared.py`、`test_asr_sentence.py`、`test_webui_contracts.py` | 测试 `scripts/` 和 `webui/` 模块 | 否（质量保障） | 低（测试变更） |
| `inputs/` | 用户输入音频存放位置 | 用户放入的音频文件（gitignored） | 被 `run.ps1`、`webui/service.py` 扫描 | 否（用户数据） | 低 |
| `outputs/` | 管线运行结果输出位置 | CLI 和 WebUI 的运行结果（gitignored） | 由 `asr_sentence_segment.py` 写入 | 否（输出数据） | 低 |
| `models/` | 本地预训练模型权重 | `Qwen3-ASR-1.7B/`、`Qwen3-ForcedAligner-0.6B/`（gitignored） | 由 `bootstrap.ps1 -DownloadModels` 下载，被 `asr_sentence_segment.py` 加载 | 是（需要存在） | 高（模型完整性） |
| `.venv/` | Python 虚拟环境（gitignored） | Python 解释器和已安装包 | 由 `bootstrap.ps1` 创建，所有脚本通过其 `python.exe` 运行 | 是（需要存在） | 低（可重建） |
| `.cache/` | 运行时缓存（gitignored） | HF hub、torch、pip、tmp、webui 等子目录 | 由 `env.ps1` 设置环境变量指向 | 否（可再生） | 低 |
| `.tools/` | 自动下载的工具（gitignored） | ffmpeg 便携版 | 由 `bootstrap.ps1` 下载，通过 PATH 引用 | 否（可替换） | 低 |

## 8. 全量文件职责索引

### 项目自有有效文件：共 35 个（不含 CODEX_PROJECT_MANIFEST.md）
### 已建立职责说明：35 个
### 被排除的文件类型：`.venv/`、`.cache/`、`.tools/`、`__pycache__/`、`.pytest_cache/`、`.mypy_cache/`、`.ruff_cache/`、`.playwright-cli/`、`outputs/`、`inputs/`、`models/` 下的自动生成/第三方/用户数据文件
### 是否存在未识别文件：否

| 文件路径 | 类型 | 主要职责 | 关键入口 | 依赖 | 被谁调用 | 影响范围 | 风险 | 测试状态 | 当前状态 |
|---|---|---|---|---|---|---|---|---|---|
| `pyproject.toml` | 配置 | Python 工具配置（ruff lint/format、pytest、mypy 设置） | `[tool.ruff]`、`[tool.pytest]`、`[tool.mypy]` | 无 | `ruff`、`pytest`、`mypy` 自动读取 | 代码质量工具行为 | 低 | N/A | 稳定 |
| `requirements.txt` | 配置 | 运行期 Python 包依赖列表 | qwen-asr, soundfile, fastapi, uvicorn, modelscope, huggingface_hub, funasr | pip | `bootstrap.ps1` 安装时读取 | 运行环境依赖安装 | 中（加/删依赖） | N/A | 稳定 |
| `requirements-dev.txt` | 配置 | 开发/质量检查 Python 包依赖 | ruff, pytest, mypy, httpx | pip | 开发者手动安装 | 开发工具链 | 低 | N/A | 稳定 |
| `.editorconfig` | 配置 | 跨编辑器格式规范 | 缩进、编码、行尾 | 无 | IDE/编辑器自动读取 | 代码格式一致性 | 低 | N/A | 稳定 |
| `.gitattributes` | 配置 | Git 文本文件规范化 | `* text=auto` | Git | Git 自动处理 | 跨平台文本文件换行 | 低 | N/A | 稳定 |
| `.gitignore` | 配置 | Git 忽略规则 | 排除 venv/cache/outputs/models 等 | Git | Git 自动读取 | 版本控制范围 | 中（漏加/误加） | N/A | 稳定 |
| `env.ps1` | 脚本 | 设置项目内环境变量（缓存目录、ffmpeg PATH、HF 配置） | `$env:HF_HOME` 等 | 无 | `bootstrap.ps1`、`run.ps1`、`start_webui.ps1` 加载 | 所有子进程的缓存/工具路径 | 中 | N/A | 稳定 |
| `bootstrap.ps1` | 脚本 | 全自动环境初始化：检测 Python、创建 venv、pip 安装依赖、下载 ffmpeg、下载模型 | 主流程、`Invoke-Step`、`Invoke-NativeChecked` | `requirements.txt`、`env.ps1` | 用户直接执行或 `start_webui.ps1` 自动调用 | 整个运行环境的搭建 | 中（安装逻辑） | NOT_RUN | 稳定 |
| `bootstrap.bat` | 脚本 | `bootstrap.ps1` 的 cmd 双击入口 | PowerShell 调用 | 无 | 用户双击 | 启动 bootstrap.ps1 | 低 | N/A | 稳定 |
| `run.ps1` | 脚本 | CLI 主入口：参数处理、环境校验、调用 ASR Python 管线 | `param(...)` 参数定义、`main` 调用 ASR 脚本 | `env.ps1`、`scripts/asr_sentence_segment.py`、`.venv` | 用户执行 `./run.ps1` 或 `run_cli.bat` | 整个 CLI 使用流程 | 高（参数转发） | N/A | 稳定 |
| `run_cli.bat` | 脚本 | `run.ps1` 的 cmd 双击入口 | PowerShell 调用 | 无 | 用户双击 | 启动 run.ps1 | 低 | N/A | 稳定 |
| `run_webui.bat` | 脚本 | WebUI 启动的 cmd 双击入口 | PowerShell 调用 `start_webui.ps1` | `start_webui.ps1` | 用户双击 | 启动 WebUI | 低 | N/A | 稳定 |
| `start_webui.ps1` | 脚本 | WebUI 总启动：环境检查、自动修复、Port 处理、启动 uvicorn | 启动流程控制 | `bootstrap.ps1`、`env.ps1`、`webui/app.py` | 用户执行或 `run_webui.bat` 调用 | WebUI 启动全过程 | 高（启动流程） | N/A | 稳定 |
| `package_for_deploy.ps1` | 脚本 | 部署包打包（生成 ZIP） | 文件收集、压缩 | 无 | 用户手动执行 | 部署分发 | 低 | N/A | 稳定 |
| `scripts/shared.py` | 源码 | 共享常量和工具：项目根路径、分句默认值读取 | `project_root()`、`read_split_defaults()`、`DEFAULT_SPLIT_DEFAULTS` | `configs/defaults.json` | `scripts/asr_sentence_segment.py`、`webui/service.py` 导入 | 分句参数全局一致性 | 中 | PASS（4 测试） | 稳定 |
| `scripts/asr_sentence_segment.py` | 源码 | ASR 管线核心：模型加载、音频转码、ASR 推理、分句、导出 | `main()`、`run_pipeline()`、`transcribe_with_timestamps()`、`greedy_sentence_split()` | `shared.py`、`qwen_asr`、`soundfile`、`torch`、`funasr`、ffmpeg | `run.ps1` 通过 `python.exe` 调用 | 全部 ASR 功能 | **极高**（核心） | PARTIAL（11 测试覆盖纯函数） | 稳定 |
| `scripts/self_check.py` | 脚本 | 环境自检：Python/venv/ffmpeg/torch/依赖导入 | `main()`、`check_python()`、`check_ffmpeg()`、`check_torch()` | 无（运行时导入依赖） | 用户直接执行或 WebUI 触发 | 环境诊断 | 低 | NOT_RUN | 稳定 |
| `webui/__init__.py` | 源码 | WebUI 包入口 | 空文件 | 无 | Python 包导入 | 使 webui/ 成为包 | 低 | N/A | 稳定 |
| `webui/app.py` | 源码 | FastAPI 应用定义和所有 REST API 端点 | `app = FastAPI(...)`、`@app.get|post|put` 路由 | `webui/service.py` | `uvicorn` 启动加载 | WebUI 全部后端 API | **高** | PARTIAL（WebUI 契约测试） | 稳定 |
| `webui/service.py` | 源码 | WebUI 后端核心服务：JobManager（任务队列、进程管理、结果扫描、配置管理、偏好管理、热词管理、导出） | `manager = JobManager()`、`JobRecord`、`JobManager` 全部方法 | `shared.py`、`configs/` 目录 | `webui/app.py` 通过 `manager` 对象调用 | WebUI 全部业务逻辑 | **极高** | PARTIAL（部分方法有测试） | 稳定 |
| `webui/static/index.html` | 前端 | WebUI 单页应用 HTML 入口 | `<div id="...">` 元素 | `styles.css`、`app.js` | 浏览器通过 `/` 路由加载 | WebUI 用户界面结构 | 中 | NOT_RUN | 稳定 |
| `webui/static/app.js` | 前端 | WebUI 前端全部交互逻辑：状态管理、API 调用、UI 渲染 | `state`、`el`、`init()`、`render*` 系列函数 | `index.html`、后端 API | 浏览器执行 | WebUI 全部用户交互 | 中 | NOT_RUN | 稳定 |
| `webui/static/styles.css` | 前端 | WebUI 前端全部样式 | CSS 选择器和属性 | 无 | `index.html` 引用 | WebUI 界面外观 | 低 | NOT_RUN | 稳定 |
| `webui/static/favicon.svg` | 资源 | 网页图标 | SVG 图形 | 无 | `index.html` `<link rel="icon">` | 浏览器标签页图标 | 低 | N/A | 稳定 |
| `configs/defaults.json` | 配置 | 分句 5 参数默认值集中管理 | `pause_threshold`、`min_dur`、`max_dur`、`pad_left`、`pad_right` | 无 | `scripts/shared.py` 读取 | CLI/WebUI/Python 三端分句参数基准 | 中 | PASS（通过 shared 测试） | 稳定 |
| `configs/webui/current_workflow.json` | 配置 | 通用 WebUI 入门配置预设 | 全部表单字段的默认值 | 无 | `webui/service.py` 加载 | WebUI 表单默认值 | 中 | NOT_RUN | 稳定 |
| `configs/webui/qwen3_tts_finetune.json` | 配置 | Qwen3-TTS 微调场景配置预设 | 与 `current_workflow.json` 同结构，不同默认值 | 无 | `webui/service.py` 加载 | WebUI 可选配置 | 低 | NOT_RUN | 稳定 |
| `configs/hotwords/luo_zheng_ling.txt` | 配置 | 示例热词库：洛天依相关专有名词 | `洛天依`、`天依` | 无 | WebUI 热词管理/CLI hotword 参数 | ASR 识别上下文提示 | 低 | NOT_RUN | 稳定 |
| `configs/hotwords/Nikki.txt` | 配置 | 示例热词库：暖暖游戏相关专有名词 | `暖暖`、`大喵` | 无 | WebUI 热词管理/CLI hotword 参数 | ASR 识别上下文提示 | 低 | NOT_RUN | 稳定 |
| `tests/test_shared.py` | 测试 | `shared.py` 的单元测试（5 个测试函数） | `test_default_split_defaults_structure`、`test_read_split_defaults_*` | `shared.py`、`pytest` | 开发者 `pytest tests/` | 验证 shared.py 功能 | 低 | N/A | 稳定 |
| `tests/test_asr_sentence.py` | 测试 | `asr_sentence_segment.py` 纯函数测试：分句/标点/安全/参数校验（30+ 测试函数） | 各类 `test_*` 函数 | `asr_sentence_segment.py`、`pytest` | 开发者 `pytest tests/` | 验证分句等纯函数正确性 | 低 | N/A | 稳定 |
| `tests/test_webui_contracts.py` | 测试 | WebUI 契约测试：参数序列化/文件操作/配置保存/工作线程容错（6 个测试函数） | `test_runtime_fields_*`、`test_atomic_json_write_*` 等 | `webui/app.py`、`webui/service.py`、`pytest`、`httpx` | 开发者 `pytest tests/` | 验证 WebUI 后端契约和稳定性 | 低 | N/A | 稳定 |
| `README.md` | 文档 | 项目说明文档 | 安装/使用/配置说明 | 无 | 用户阅读 | 项目使用指引 | 低 | N/A | 存在 |
| `TROUBLESHOOTING_AND_OPTIMIZATION_REPORT.md` | 文档 | 故障排查和优化报告 | 已知问题/优化建议 | 无 | 用户阅读 | 辅助排查 | 低 | N/A | 存在 |
| `P0-3-webui-audio-player.md` | 文档 | WebUI 音频播放器 P0-P3 功能需求 | P0-P3 需求描述、实现方案 | 无 | 开发者阅读 | 功能规划 | 低 | N/A | 规划 |

## 9. 核心模块说明

### 9.1 ASR 管线核心（`scripts/asr_sentence_segment.py`）

**模块目标：** 实现完整的离线音频→文字→时间戳→分句→导出流程。

**关键文件：** `scripts/asr_sentence_segment.py`（1503 行）

**输入：**
- 音频文件路径（支持多种格式，通过 ffmpeg 转码）
- CLI 参数（模型路径、语言、分句参数、批处理参数等）

**输出：**
- `segments/*.wav`：切割后的句子级音频片段
- `segments/*.txt`：对应的纯文本
- `index.jsonl`：标准分段索引（JSONL 格式）
- `full_text.txt`：全部识别文本
- `meta.json`：任务元数据
- `qwen3_tts.jsonl`（可选）：Qwen3-TTS 微调清单

**核心流程（5 步）：**
1. **ffmpeg 转码**：输入音频 → 16kHz 单声道 wav
2. **模型加载**：Qwen3-ASR + Qwen3-ForcedAligner（含批大小和 max_new_tokens）
3. **ASR 推理 + 时间戳**：音频分块 → 逐块推理 → 合并时间戳
4. **标点恢复（可选）**：FunASR 标点模型 → 检查正文改动 → 合并到时间线
5. **贪心分句 + 导出**：四级切分策略（强边界>软边界>停顿>硬切）→ wav/txt/jsonl 写入

**数据结构：**
- `CharStamp`：`{char: str, start: float, end: float}` — 字符级时间戳
- `segment`：`{char_start_idx, char_end_idx, start, end, text}` — 分句结果
- `meta.json`：完整任务配置、检测到的语言、警告信息

**外部依赖：**
- `qwen_asr.Qwen3ASRModel`：ASR 模型接口
- `soundfile`：读取/验证 wav 文件
- `torch`：CUDA/CPU 设备管理
- `funasr.AutoModel`：标点恢复
- `ffmpeg` / `ffprobe`：音频转码和探测
- `nvidia-smi`（可选）：显存信息查询

**错误处理：**
- `GpuSafetyPrecheckError`：显存不足时阻止启动
- CUDA OOM 自动降级：batch_size > 1 → 1 → CPU
- 标点模型改正文检测 → 拒绝标点结果 + 元数据标记降级
- 参数校验（`validate_runtime_args`）：加载模型前快速失败
- 键盘中断（`KeyboardInterrupt`）处理

**测试覆盖：**
- 纯函数测试（分句算法、标点规范化、参数校验、文件名安全）
- 依赖 GPU 和非纯函数的路径**未**覆盖（标记为占位/跳过）

**已知限制：**
- 不支持实时流式 ASR
- 不支持多 GPU 并行
- 默认 12GB 显存安全线（可调整）
- 无增量/断点续传

### 9.2 共享库（`scripts/shared.py`）

**模块目标：** 提供 CLI、Python 脚本、WebUI 三者共享的常量和工具。

**关键文件：** `scripts/shared.py`（45 行）

**内容：**
- `DEFAULT_SPLIT_DEFAULTS`：分句参数内置默认值字典
- `project_root()`：返回项目根目录的 Path 对象
- `read_split_defaults()`：从 `configs/defaults.json` 读取分句默认值（文件缺失/损坏时回退到内置值）

**测试覆盖：** 5 个测试函数（结构验证、文件缺失、有效 JSON、部分字段、无效 JSON）

### 9.3 WebUI 后端服务（`webui/service.py`）

**模块目标：** 实现 WebUI 的任务队列管理、配置管理、热词管理、结果浏览等后端业务逻辑。

**关键文件：** `webui/service.py`（1810 行）

**核心组件：**
- `JobRecord`（dataclass）：任务记录的数据结构
- `JobManager`：全部后端业务逻辑的容器类
  - 任务队列：`create_asr_job()` / `create_maintenance_job()` / `cancel_job()` / `clone_job()`
  - 后台执行：`_worker_loop()` →`_run_job()`（subprocess 执行 PowerShell 脚本）
  - 进度解析：`_update_progress_from_line()`（正则解析 stdout）
  - 结果管理：`list_results()` / `get_result()` / `export_qwen3_tts_dataset()`
  - 配置管理：`save_config_file()` / `load_config_file()` / `rename_config_file()` / `delete_config_file()`
  - 热词管理：`save_hotword_library()` / `load_hotword_library()`
  - 偏好管理：`save_preferences()` / `get_preferences()`
  - 环境快照：`get_environment_snapshot()`

**路径常量（18 条）：** 定义项目内各类数据目录路径。

**持久化机制：**
- `write_json_file()`：原子写（临时文件→重命名，含指数退避重试）
- `read_json_file()`：安全读取，失败返回默认值

**数据流：** 用户 API 请求 → JobManager 方法 → 创建 JobRecord → 入队 → 后台线程 subprocess(run.ps1) → 日志轮询 → 状态更新 → 持久化 → 结果扫描

### 9.4 WebUI API 路由（`webui/app.py`）

**模块目标：** 定义 FastAPI 应用和全部 REST API 端点。

**关键文件：** `webui/app.py`（426 行）

**API 端点清单：**

| 端点 | 方法 | 用途 |
|---|---|---|
| `/` | GET | 返回静态首页 `index.html` |
| `/favicon.ico` | GET | 图标 |
| `/api/health` | GET | 健康检查 |
| `/api/meta` | GET | 获取完整环境信息 |
| `/api/preferences` | GET/PUT | 获取/保存用户偏好 |
| `/api/config-files` | GET | 列出配置文件 |
| `/api/config-files/load` | POST | 加载配置 |
| `/api/config-files/save` | POST | 保存配置 |
| `/api/config-files/set-default` | POST | 设置默认配置 |
| `/api/config-files/rename` | POST | 重命名配置 |
| `/api/config-files/delete` | POST | 删除配置 |
| `/api/hotwords` | GET | 列出热词库 |
| `/api/hotwords/load` | POST | 加载热词库 |
| `/api/hotwords/save` | POST | 保存热词库 |
| `/api/jobs` | GET | 列出任务 |
| `/api/jobs/asr` | POST | 创建 ASR 任务 |
| `/api/jobs/actions/{kind}` | POST | 创建维护任务（bootstrap/download/self_check） |
| `/api/jobs/{job_id}` | GET | 获取任务详情 |
| `/api/jobs/{job_id}/retry` | POST | 重试任务 |
| `/api/jobs/{job_id}/cancel` | POST | 取消任务 |
| `/api/jobs/{job_id}/open-output` | POST | 在资源管理器打开输出目录 |
| `/api/results` | GET | 列出结果 |
| `/api/results/{result_id}` | GET | 获取结果详情 |
| `/api/results/{result_id}/artifact` | GET | 获取结果中的文件 |
| `/api/results/{result_id}/export-qwen3-tts` | POST | 导出 Qwen3-TTS 清单 |
| `/api/results/{result_id}/open` | POST | 在资源管理器打开结果目录 |
| `/api/system/open` | POST | 打开预定义系统目录 |
| `/api/system/open-path` | POST | 打开任意项目路径 |

**Pydantic 模型：** `PreferencesPayload`、`AsrJobPayload`、`ExportQwen3TtsPayload`、`OpenPathPayload`、`OpenSystemPathPayload`、`ConfigFileLoadPayload`、`ConfigFileSavePayload`、`ConfigFileRenamePayload`、`HotwordLibraryLoadPayload`、`HotwordLibrarySavePayload`

## 10. 程序启动与运行链路

### 环境准备

1. 安装 Python 3.10+
2. （可选但推荐）执行 `bootstrap.ps1` 自动创建 `.venv` 并安装全部依赖
3. （可选）下载模型：`bootstrap.ps1 -DownloadModels`

### 安装依赖

```powershell
# 完整安装（推荐）
.\bootstrap.ps1

# 只安装基础
.\bootstrap.ps1

# 额外安装模型
.\bootstrap.ps1 -DownloadModels

# 额外安装 FunASR（标点恢复）
.\bootstrap.ps1 -InstallFunASR
```
**状态：** NOT_RUN

### 配置文件

- **分句默认值：** `configs/defaults.json`
- **WebUI 配置预设：** `configs/webui/current_workflow.json`
- **WebUI 配置文件目录：** `configs/webui/`
- **热词库目录：** `configs/hotwords/`
- **运行时配置：** 可通过 `run.ps1 -ShowConfig` 查看当前生效配置

### 环境变量

可在系统环境或 `env.ps1` 中设置：

| 变量名 | 用途 | 默认值 |
|---|---|---|
| `QWEN3_ASR_WEBUI_RUNTIME_ROOT` | WebUI 运行时根目录 | `.cache/webui` |
| `WEBUI_JOB_TIMEOUT_SECONDS` | 任务超时秒数 | `86400`（24h） |

### 数据库初始化

- 无传统数据库
- 任务队列持久化：`.cache/webui/jobs.json`（首次 JobManager 初始化时自动创建）
- `env.ps1` 会在首次加载时自动创建缓存/输入/输出目录

### 开发启动

```powershell
# 直接运行 ASR Python 脚本
python scripts/asr_sentence_segment.py --audio .\inputs\test.wav

# 通过 run.ps1
.\run.ps1 -Audio .\inputs\test.wav

# 运行测试
pytest tests/

# 静态检查
ruff check .

# 类型检查
mypy scripts/ webui/
```
**状态：** NOT_RUN（除 `pytest tests/` 外）

### 生产启动

```powershell
# CLI 批处理
.\run.ps1 -Audio .\inputs -ScanSubfolders

# WebUI
.\start_webui.ps1
# 或双击 run_webui.bat
```
**状态：** NOT_RUN

### 前端/后端启动

```powershell
# WebUI 前端 (SPA 内嵌在后端中)
.\start_webui.ps1

# WebUI 后端服务
.\start_webui.ps1
# 内部执行: uvicorn webui.app:app --host 127.0.0.1 --port 8765
```
**状态：** NOT_RUN

### 停止方法

- **CLI：** 按 `Ctrl+C`（捕获 `KeyboardInterrupt`，返回退出码 130）
- **WebUI：** 在终端按 `Ctrl+C`，或关闭终端窗口
- **WebUI 后台任务：** 可点击 WebUI 中的"取消"按钮（通过 `taskkill /F /T /PID`）

### 日志位置

| 来源 | 路径 |
|---|---|
| CLI 运行日志 | 任务输出目录的 `run.ps1` stdout |
| WebUI 任务日志 | `.cache/webui/logs/{job_id}.log` |
| WebUI 运行时日志 | uvicorn 控制台 stdout |
| WebUI 任务队列 | `.cache/webui/jobs.json` |

### 健康检查

- HTTP：`GET /api/health` 返回 `{"status": "ok"}`
- CLI：无 HTTP 端点；可通过退出码判断（0=成功，其它=失败）
- 自检脚本：`python scripts/self_check.py`

### 常见失败原因

| 症状 | 常见原因 | 解决方案 |
|---|---|---|
| 未找到虚拟环境 | 未运行 `bootstrap.ps1` | `.\bootstrap.ps1` |
| 未找到 ffmpeg | 未安装或不在 PATH | 项目内自动下载或手动安装 |
| 显存不足 | 其它程序占用显存 | 关闭 ComfyUI/游戏/浏览器视频 |
| 模型目录不存在 | 未下载模型 | `.\bootstrap.ps1 -DownloadModels` |
| 标点恢复失败 | 缺 FunASR | `.\bootstrap.ps1 -InstallFunASR` |
| 端口被占用 | 已有实例运行 | 换端口或关闭已有实例 |
| 输入路径不存在 | 路径写错 | 检查盘符和路径 |
| 目录下无音频 | inputs 为空 | 先把音频放入目录 |

## 11. 配置与环境变量

### 配置项

| 配置项 | 必需 | 默认值 | 用途 | 来源 | 敏感 | 使用位置 |
|---|---|---|---|---|---|---|
| `audio` | 是 | `.\inputs` | 输入音频路径（文件或目录） | 表单/CLI 参数 | 否 | `asr_sentence_segment.py` |
| `output_mode` | 否 | `auto` | 输出目录模式（auto/custom） | 表单 | 否 | `webui/service.py` |
| `output_dir` | 否 | `""` | 自定义输出目录 | 表单/CLI 参数 | 否 | `asr_sentence_segment.py` |
| `dataset_format` | 否 | `standard` | 导出格式（standard/qwen3_tts） | 表单/CLI 参数 | 否 | `asr_sentence_segment.py` |
| `ref_audio` | 否 | `""` | Qwen3-TTS 参考音频路径 | 表单/CLI 参数 | 否 | `asr_sentence_segment.py` |
| `hotword_library` | 否 | `""` | 热词库文件名 | 表单 | 否 | `webui/service.py` |
| `hotword_text` | 否 | `""` | 临时热词正文（每行一个词） | 表单/CLI 参数 | 否 | `asr_sentence_segment.py` |
| `asr_ckpt` | 是 | `.\models\Qwen3-ASR-1.7B` | ASR 模型路径 | 表单/CLI 参数 | 否 | `asr_sentence_segment.py` |
| `aligner_ckpt` | 是 | `.\models\Qwen3-ForcedAligner-0.6B` | 对齐模型路径 | 表单/CLI 参数 | 否 | `asr_sentence_segment.py` |
| `language` | 否 | `None` | 语言策略（None=自动） | 表单/CLI 参数 | 否 | `asr_sentence_segment.py` |
| `punc_model` | 否 | `iic/punc_ct-transformer_cn-en-common-vocab471067-large` | 标点恢复模型 | 表单/CLI 参数 | 否 | `asr_sentence_segment.py` |
| `batch_size` | 否 | `1` | ASR 推理批大小 | 表单/CLI 参数 | 否 | `asr_sentence_segment.py` |
| `max_new_tokens` | 否 | `1024` | 每块最大生成 Token 数 | 表单/CLI 参数 | 否 | `asr_sentence_segment.py` |
| `chunk_seconds` | 否 | `60.0` | 音频分块秒数 | 表单/CLI 参数 | 否 | `asr_sentence_segment.py` |
| `min_cuda_free_gb` | 否 | `9.0` | 最低空闲显存（GiB） | 表单/CLI 参数 | 否 | `asr_sentence_segment.py` |
| `force_cpu` | 否 | `false` | 强制 CPU 推理 | 表单/CLI 参数 | 否 | `asr_sentence_segment.py` |
| `pause_threshold` | 否 | `0.6` | 停顿分句阈值（秒） | 表单/CLI 参数/`defaults.json` | 否 | `asr_sentence_segment.py` |
| `min_dur` | 否 | `0.8` | 最短句时长（秒） | 表单/CLI 参数/`defaults.json` | 否 | `asr_sentence_segment.py` |
| `max_dur` | 否 | `8.0` | 最长句时长（秒） | 表单/CLI 参数/`defaults.json` | 否 | `asr_sentence_segment.py` |
| `pad_left` | 否 | `0.05` | 句首补边（秒） | 表单/CLI 参数/`defaults.json` | 否 | `asr_sentence_segment.py` |
| `pad_right` | 否 | `0.10` | 句尾补边（秒） | 表单/CLI 参数/`defaults.json` | 否 | `asr_sentence_segment.py` |
| `eta_rtf` | 否 | `2.0` | ETA 估算速度系数 | 表单/CLI 参数 | 否 | `asr_sentence_segment.py` |
| `long_audio_warning_minutes` | 否 | `120` | 长音频预警阈值 | 表单 | 否 | `webui/service.py` |
| `scan_subfolders` | 否 | `false` | 递归扫描子目录 | 表单/CLI 参数 | 否 | `run.ps1` |

### 环境变量

| 变量 | 必需 | 默认值 | 用途 | 来源 | 敏感 | 使用位置 |
|---|---|---|---|---|---|---|
| `HF_HOME` | 否 | `.cache/hf` | Hugging Face 缓存根目录 | `env.ps1` | 否 | transformers/huggingface_hub |
| `HUGGINGFACE_HUB_CACHE` | 否 | `.cache/hf/hub` | HF 模型快照缓存 | `env.ps1` | 否 | huggingface_hub |
| `TORCH_HOME` | 否 | `.cache/torch` | PyTorch 缓存 | `env.ps1` | 否 | torch |
| `MODELSCOPE_CACHE` | 否 | `.cache/modelscope` | ModelScope 缓存 | `env.ps1` | 否 | modelscope |
| `XDG_CACHE_HOME` | 否 | `.cache/xdg` | XDG 缓存基本目录 | `env.ps1` | 否 | 各种库 |
| `PIP_CACHE_DIR` | 否 | `.cache/pip` | pip 下载缓存 | `env.ps1` | 否 | pip |
| `QWEN_ASR_CACHE` | 否 | `.cache/qwen_asr` | qwen-asr 缓存 | `env.ps1` | 否 | qwen_asr |
| `QWEN3_ASR_WEBUI_RUNTIME_ROOT` | 否 | `.cache/webui` | WebUI 运行时根目录 | 用户环境 | 否 | `webui/service.py` |
| `WEBUI_JOB_TIMEOUT_SECONDS` | 否 | `86400` | 任务超时秒数 | 用户环境 | 否 | `webui/service.py` |
| `PYTHONUTF8` | 否 | `1` | Python UTF-8 模式 | `env.ps1` | 否 | Python 解释器 |
| `HF_HUB_DISABLE_SYMLINKS_WARNING` | 否 | `1` | 禁用 Windows 符号链接警告 | `env.ps1` | 否 | huggingface_hub |

## 12. 依赖管理

### 运行依赖（`requirements.txt`）

| 包名 | 是否必需 | 用途 | 固定版本 |
|---|---|---|---|
| `qwen-asr` | 是 | Qwen3-ASR 模型加载和推理 | 否 |
| `soundfile` | 是 | 音频文件读取 | 否 |
| `fastapi` | 是 | WebUI REST API 框架 | 否 |
| `uvicorn` | 是 | FastAPI ASGI 服务器 | 否 |
| `modelscope` | 否 | 从 ModelScope 下载模型（可选） | 否 |
| `huggingface_hub` | 是 | 从 Hugging Face 下载模型 | 否 |
| `funasr` | 是 | 标点恢复模型 | 否 |

### 开发依赖（`requirements-dev.txt`）

| 包名 | 用途 |
|---|---|
| `ruff` | Lint 和格式化 |
| `pytest` | 测试框架 |
| `mypy` | 可选的静态类型检查 |
| `httpx` | FastAPI TestClient HTTP 模拟 |

### 系统依赖

| 软件 | 用途 | 安装方式 |
|---|---|---|
| **Python** >= 3.10 | 运行环境 | 用户手动安装 |
| **ffmpeg** + **ffprobe** | 音频转码和探测 | 自动下载到 `.tools/ffmpeg/bin/`，或系统安装 |
| **PowerShell** 5.1+ | 脚本运行引擎 | Windows 自带 |
| **NVIDIA CUDA** | GPU 加速（可选） | 用户手动安装 + PyTorch CUDA 版 |

### 外部服务

| 服务 | 用途 | 是否需要凭据 |
|---|---|---|
| Hugging Face（`huggingface.co`） | 下载 Qwen3-ASR / ForcedAligner 模型 | 否（公开模型） |
| gyan.dev | 下载 ffmpeg 便携版 | 否 |

### 依赖版本冲突
- 当前依赖未固定补丁版本，可能存在兼容性问题
- `qwen-asr` 库仍在快速迭代，API 签名可能变化（`asr_sentence_segment.py` 中有针对 `max_inference_batch_size` 和 `max_new_tokens` 参数的兼容处理）
- FunASR 的 `disable_update` 和 `device` 参数在不同版本间可能不同（代码中有回退逻辑）

## 13. 数据库与持久化

### 数据库类型
- 无传统数据库（SQL/NoSQL）
- 持久化全部使用文件系统 JSON 文件

### ORM
- 无 ORM

### 持久化文件

| 文件 | 类型 | 用途 | 创建者 |
|---|---|---|---|
| `.cache/webui/jobs.json` | JSON 数组 | 任务队列持久化 | `JobManager.__init__()` |
| `.cache/webui/preferences.json` | JSON 对象 | 用户偏好持久化 | `save_preferences()` |
| `.cache/webui/default_config.json` | JSON 对象 | 默认配置文件名记录 | `set_default_config_file()` |
| `.cache/webui/logs/{job_id}.log` | 文本 | 单任务日志 | `_run_job()` |
| `outputs/webui_runs/{stamp}__{name}__{id}/meta.json` | JSON | 任务元数据 | `asr_sentence_segment.py` |
| `outputs/webui_runs/{stamp}__{name}__{id}/index.jsonl` | JSONL | 分段索引 | `asr_sentence_segment.py` |
| `outputs/webui_runs/{stamp}__{name}__{id}/full_text.txt` | 文本 | 完整识别文本 | `asr_sentence_segment.py` |

### 数据关系
```
用户偏好 → 覆盖默认配置 → 覆盖 WebUI 配置预设 → 覆盖 configs/defaults.json
                ↓
         AsrJobPayload
                ↓
         meta.json（记录该次任务的全部最终配置）
```

## 14. 接口与数据契约

### 14.1 HTTP API（WebUI）

**基础 URL：** `http://127.0.0.1:8765`

**通用约定：**
- 请求体格式：`application/json`
- 响应体格式：`application/json`
- 错误响应格式：`{"detail": "错误描述"}`（FastAPI 标准）
- 状态码：200（成功）、400（请求错误）、403（权限拒绝）、404（未找到）

详见 `webui/app.py` 中的完整端点列表（9.4 节）。

### 14.2 命令行接口

```
python scripts/asr_sentence_segment.py --audio <path> [options]
```

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `--audio` | str | 必填 | 输入音频文件路径 |
| `--out_dir` | str | 自动生成 | 输出目录 |
| `--asr_ckpt` | str | `Qwen/Qwen3-ASR-1.7B` | ASR 模型路径 |
| `--aligner_ckpt` | str | `Qwen/Qwen3-ForcedAligner-0.6B` | 对齐模型路径 |
| `--language` | str | `Chinese` | 语言（None=自动检测） |
| `--punc_model` | str | `""` | 标点恢复模型名 |
| `--pause_threshold` | float | 0.6 | 停顿阈值（秒） |
| `--min_dur` | float | 0.8 | 最短句时长（秒） |
| `--max_dur` | float | 8.0 | 最长句时长（秒） |
| `--pad_left` | float | 0.05 | 左补边（秒） |
| `--pad_right` | float | 0.10 | 右补边（秒） |
| `--max_new_tokens` | int | 1024 | 每块最大 Token 数 |
| `--batch_size` | int | 1 | 推理批大小 |
| `--chunk_seconds` | float | 60.0 | 分块时长（秒） |
| `--min_cuda_free_gb` | float | 9.0 | 最低空闲显存（GiB） |
| `--force_cpu` | flag | false | 强制 CPU |
| `--eta_rtf` | float | 2.0 | ETA 估算速度 |
| `--dataset_format` | str | `standard` | 导出格式 |
| `--ref_audio` | str | `""` | 参考音频路径 |
| `--hotword_file` | str | `""` | 热词文件路径 |

### 14.3 PowerShell CLI（`run.ps1`）

```
.\run.ps1 [-Audio <str>] [-OutDir <str>] [-DatasetFormat <str>] [-RefAudio <str>]
          [-HotwordFile <str>] [-HotwordLibrary <str>] [-AsrCkpt <str>]
          [-AlignerCkpt <str>] [-Language <str>] [-PuncModel <str>]
          [-PauseThreshold <double>] [-MinDur <double>] [-MaxDur <double>]
          [-PadLeft <double>] [-PadRight <double>] [-BatchSize <int>]
          [-MaxNewTokens <int>] [-ChunkSeconds <double>] [-MinCudaFreeGB <double>]
          [-EtaRTF <double>] [-ForceCpu] [-ScanSubfolders] [-ShowConfig] [-Help]
```

### 14.4 输出文件格式

**`index.jsonl` 每行：**
```json
{
  "id": "seg_0001",
  "wav": "segments/seg_0001__文本预览.wav",
  "txt": "segments/seg_0001__文本预览.txt",
  "start": 0.0,
  "end": 3.5,
  "text": "识别文本内容。"
}
```

**`qwen3_tts.jsonl` 每行：**
```json
{
  "audio": "data/audio/utt0001.wav",
  "text": "识别文本内容。",
  "language": "Chinese",
  "ref_audio": "data/ref/ref_audio.wav"  // 可选
}
```

**`meta.json` 结构：** 包含全部运行参数、模型路径、检测到的语言、警告信息、分段统计等。

### 14.5 内部模块接口

**`shared.py` → 调用者契约：**
- `read_split_defaults() -> dict[str, float]`：返回分句 5 参数
- `project_root() -> Path`：返回项目根目录

**`asr_sentence_segment.py` 核心函数契约：**
- `transcribe_with_timestamps(model, wav_path, ...) -> (text, timestamps, language)`
- `greedy_sentence_split(timeline, ...) -> list[dict]`
- `normalize_punctuation_text(text) -> str`
- `validate_punctuation_text(raw, punc) -> str`
- `write_segments_and_index(source_audio, segments, out_dir) -> list[dict]`

## 15. 测试与质量状态

### 测试框架
- pytest（`pyproject.toml` 中配置为 Python 3.10、`tests/` 目录、`test_*.py` 匹配）

### 测试目录
- `tests/test_shared.py`（5 个测试函数）：共享库测试
- `tests/test_asr_sentence.py`（30+ 测试函数/类）：ASR 管线纯函数测试
- `tests/test_webui_contracts.py`（6 个测试函数）：WebUI 契约测试

### 测试覆盖情况

| 模块 | 测试覆盖范围 | 未覆盖的关键路径 | 状态 |
|---|---|---|---|
| `shared.py` | 所有函数和常量 | 无 | PASS |
| `asr_sentence_segment.py` | 纯函数：分句、标点规范化、参数校验、文件名安全、错误类型检测 | GPU 推理、模型加载、音频转码、WebUI 调用管线、ffmpeg 操作 | PARTIAL |
| `webui/service.py` | 原子写文件、配置保存保留 guide、工作线程容错、任务队列基本行为 | JobManager 全流程、进程管理、日志轮询、结果扫描 | PARTIAL |
| `webui/app.py` | 参数序列化、系统路径打开 API | 全部其他 API 端点 | PARTIAL |
| `start_webui.ps1` | 无 | 全部 | NOT_RUN |
| `run.ps1` | 无 | 全部 | NOT_RUN |
| `bootstrap.ps1` | 无 | 全部 | NOT_RUN |

### 执行命令
```powershell
# 运行全部测试
pytest tests/
```
**状态：** NOT_RUN（当前未执行）

### 静态检查
```powershell
# Ruff lint
ruff check .

# Ruff format check
ruff format --check .
```
**状态：** NOT_RUN

### 类型检查
```powershell
mypy scripts/ webui/
```
**状态：** NOT_RUN

## 16. 已知问题与技术债

| 编号 | 优先级 | 问题描述 | 故障现象 | 根本原因 | 影响范围 | 相关文件 | 临时方案 | 正式方案 | 状态 |
|---|---|---|---|---|---|---|---|---|---|
| KNOWN-001 | P2 | qwen-asr API 签名不兼容 | TypeError: unexpected keyword argument | qwen-asr 仍在快速迭代，参数签名变化 | ASR 模型加载 | `asr_sentence_segment.py:456-481` | 代码已实现自动检测 + 降级 retry | 随 qwen-asr 稳定后统一 | 已处理（有兼容代码） |
| KNOWN-002 | P2 | FunASR 参数签名不兼容 | TypeError at startup | 不同 FunASR 版本 `AutoModel` 参数不同 | 标点恢复 | `asr_sentence_segment.py:854-877` | 代码已实现自动降级 | 同 KNOWN-001 | 已处理（有兼容代码） |
| KNOWN-003 | P3 | WebUI 结果预览没有音频播放器 | 只能下载文件，不能直接在网页上听 | 功能未实现 | WebUI 用户体验 | `P0-3-webui-audio-player.md` | 手动下载音频后在本地播放 | 按 P0-P3 分阶段实现 | 已规划 |
| KNOWN-004 | P2 | 依赖版本未固定 | 不同时间安装可能得到不同版本 | `requirements.txt` 未固定补丁版本 | 全部 | `requirements.txt` | 无（目前可接受） | 发布前在隔离环境锁定版本 | 开放 |
| KNOWN-005 | P3 | 无跨平台支持 | macOS/Linux 无法直接运行 | 脚本基于 PowerShell/Windows | 全部 | 所有 `.ps1`/`.bat` | Windows 是唯一目标平台 | 无计划 | 接受 |
| KNOWN-006 | P2 | 类型检查可能存在误报 | mypy 可能报告错误 | `mypy` 配置中 `ignore_missing_imports = true` | 类型安全 | `pyproject.toml` | 当前配置允许缺失导入 | 完善类型标注 | 开放 |

## 17. 安全与敏感信息边界

### 身份验证
- 无身份验证（本机单用户工具）
- WebUI 默认仅绑定 `127.0.0.1`（仅本机可访问）

### 权限控制
- `webui/app.py` 中的路径访问受到限制：
  - `open_path_in_explorer()` 仅允许已注册的项目内路径
  - `resolve_result_artifact()` 防止路径穿越（检查目标是否在结果目录内）
  - API 端点仅允许打开预定义的四个安全目录

### 密钥读取方式
- 无 API Key / Token / 密码需要存储或读取
- 模型下载来自公开的 Hugging Face / ModelScope 仓库

### 敏感日志
- 日志中不记录个人身份信息或敏感数据
- ASR 推理日志可能包含音频中的识别文本（属于用户数据）

### 用户输入
- `audio` 路径：解析时做了 `resolve_project_path()` 安全处理
- 热词内容：仅作为 ASR 上下文提示传入模型
- WebUI 表单数据：按类型严格校验（`_coerce_optional_float`、`int()` 等）

### 文件访问
- 输出写入：仅写入项目 `outputs/` 目录
- WebUI 文件访问：限制在结果目录和项目目录内
- Git 已覆盖所有敏感数据目录（`.env`、`models/`、`outputs/` 等均被 `.gitignore` 排除）

### 已知风险
- 无 HTTPS（本机使用，风险低）
- 无进程间沙箱隔离（ASR 子进程与 WebUI 同权限运行）
- 模型加载可能消耗大量内存/显存（已做预检保护）

## 18. 版本管理规范

### 当前版本
- **v0.1.0**（基线版本）
- 程序元数据中未统一硬编码版本号
- `webui/app.py:122` 中 FastAPI 标注 `version="1.0.0"`（此为 WebUI API 版本，非项目版本）

### 版本信息来源
建议以 Git Tag 作为唯一真实版本来源。

### 版本升级规则

采用语义化版本（SemVer）：`MAJOR.MINOR.PATCH`

| 级别 | 含义 | 示例 |
|---|---|---|
| MAJOR | 不兼容接口/数据/架构变更 | v1.0.0 → v2.0.0 |
| MINOR | 向后兼容的新功能 | v0.1.0 → v0.2.0 |
| PATCH | 向后兼容的 Bug 修复/优化 | v0.1.0 → v0.1.1 |

开发阶段后缀：`v0.2.0-alpha.1`、`v0.2.0-beta.1`

### 分支规则
- `main`：稳定版本，可发布
- 功能开发在本地分支进行，完成后合入 `main`

### 提交规则
- 提交信息建议遵循常规提交规范（conventional commits）：`类型(范围): 描述`
- 示例：`feat(asr): add forced aligner fallback`、`fix(webui): resolve port conflict`、`docs: update README`

### Tag 规则
- 版本发布时创建 annotated tag：`git tag -a v0.1.0 -m "v0.1.0: 初始基线版本"`
- Tag 名称格式：`vMAJOR.MINOR.PATCH`

### 发布规则
1. 确认所有测试通过
2. 更新 `CODEX_PROJECT_MANIFEST.md` 的版本历史和当前版本说明
3. 创建 Git Tag
4. （可选）运行 `package_for_deploy.ps1` 创建部署包

### 回滚规则
- 代码回滚：`git revert <commit>` 或 `git reset --hard <前一个tag>`
- 版本回滚：删除错误 Tag，重新标记前一个版本
- 数据回滚：无数据库；旧的任务输出保留在原目录

### 文档同步规则
- 每次代码修改后必须同步更新 `CODEX_PROJECT_MANIFEST.md`
- 当前状态章节原位更新
- 版本历史章节只追加

## 19. 当前版本说明

### v0.1.0（项目档案基线）

| 元数据项 | 值 |
|---|---|
| 版本号 | v0.1.0 |
| 日期 | 2026-07-20 |
| Git Commit | `45a1b7942c982bd9b5183d60d6fb07326286d400` |
| Git 分支 | `main` |
| 工作区状态 | 干净（仅未跟踪的 CODEX_PROJECT_MANIFEST.md） |
| 版本类型 | 开发基线 |
| 主要功能 | 完整 ASR + 对齐 + 分句管线 + WebUI 图形界面 |
| 已知问题 | 见第 16 节 |
| 配置变化 | 无（首次建档） |
| 数据库变化 | 无 |
| 兼容性情况 | Windows-only，Python >= 3.10，建议 NVIDIA GPU 12GB+ |
| 测试状态 | 核心纯函数已覆盖；GPU 和集成路径未执行 |

## 20. 版本历史

### v0.1.0 — 2026-07-20

**类型：** 初始基线
**原因：** 首次建立项目全景档案和版本管理规范

**Git 信息：**
- 分支：`main`
- Commit：`45a1b7942c982bd9b5183d60d6fb07326286d400`
- 工作区：干净

**项目已有提交历史（自初始版本）：**

| Commit | 说明 |
|---|---|
| `77dd734` | Initial commit |
| `d11356e` | ffmpeg自动构建更新 |
| `5bd66a0` | 修复识别和标点错误 |
| `8a7d458` | 修复已知bug |
| `7fbd741` | 修复严重bug |
| `e294041` | 修复bug |
| `45a1b79` | 更新，修复bug |

**文件索引（建档时项目自有文件）：**
- 共 35 个有效文件（不含本档案）
- 7 个源码文件（`.py`）：`scripts/shared.py`、`scripts/asr_sentence_segment.py`、`scripts/self_check.py`、`webui/__init__.py`、`webui/app.py`、`webui/service.py`
- 5 个前端文件：`webui/static/index.html`、`webui/static/app.js`、`webui/static/styles.css`、`webui/static/favicon.svg`
- 6 个配置文件：`pyproject.toml`、`requirements.txt`、`requirements-dev.txt`、`.editorconfig`、`.gitattributes`、`.gitignore`、`configs/defaults.json`、`configs/webui/current_workflow.json`、`configs/webui/qwen3_tts_finetune.json`、`configs/hotwords/luo_zheng_ling.txt`、`configs/hotwords/Nikki.txt`
- 8 个脚本文件：`env.ps1`、`bootstrap.ps1`、`bootstrap.bat`、`run.ps1`、`run_cli.bat`、`run_webui.bat`、`start_webui.ps1`、`package_for_deploy.ps1`
- 3 个测试文件：`tests/test_shared.py`、`tests/test_asr_sentence.py`、`tests/test_webui_contracts.py`
- 4 个文档文件：`README.md`、`TROUBLESHOOTING_AND_OPTIMIZATION_REPORT.md`、`P0-3-webui-audio-player.md`

**测试状态（建档时）：**
- 测试框架已配置（pytest）
- 存在 3 个测试文件，覆盖核心纯函数和 WebUI 契约
- GPU/集成路径依赖真实环境，未自动执行

**已知遗留问题：**
- 见第 16 节 KNOWN-001 至 KNOWN-006

## 21. 文档维护规则

1. **每次代码任务完成后必须同步更新本文件。**

2. **当前状态章节（第 1-17 节）必须原位更新。**
   - 文件新增、修改、删除、重命名必须反映在第 6/7/8 节
   - 架构、配置、依赖、接口变化必须反映在第 4/11/12/14 节
   - 版本号变化必须反映在第 1/18/19 节
   - 测试结果必须反映在第 15 节
   - 已知问题必须反映在第 16 节

3. **版本历史（第 20 节）只能追加，不可修改已有记录。**
   - 创建新版本记录时复制第 20 节的模板
   - 不得复制整个旧文档到末尾
   - 不得删除历史版本

4. **实际代码和验证结果优先于旧文档。**
   - 当实际代码与文档不一致时，更新文档以反映实际代码
   - 测试未执行不得标记为通过
   - 未验证的命令或特性必须标记 `NOT_RUN`

5. **文档本身修改也须记入版本历史。**

6. **安全红线：**
   - 文档中不得写入真实密钥、Token、密码
   - 绝对路径和用户名路径应使用项目相对路径或 `<REDACTED>` 替换

7. **第 8 节的完整性检查：**
   - 每次提交前应重新扫描项目自有文件列表
   - 确保所有有效文件都有职责说明
   - 删除已不存在的文件记录
   - 更新已重命名的路径

---

*本文档由 OpenCode Agent 于 2026-07-20 自动分析生成并初始建立。*
*基于代码实际状态，以 README、源代码、配置、测试、脚本和 Git 状态为准。*
