# Qwen3-ASR 全面排障与优化报告

- 审计日期：2026-07-16（Asia/Shanghai）
- 项目根目录：`E:\models\Qwen3-ASR`
- 审计范围：启动/安装、CLI、ASR/对齐/标点/分句/导出、WebUI、后台队列、配置、部署、稳定性、性能、可维护性与安全边界
- Git 操作：未提交、未推送、未创建远程分支；未执行 `git reset --hard` 等破坏性命令

## 1. 执行摘要

项目不是“完全不能运行”的空壳：原有 48 个单元测试能通过，模型和核心 Python 环境也已存在；但审计前有多项会让真实用户误以为配置生效、任务成功或部署包可用的问题。最关键的原始故障包括：

1. RTX 4070 SUPER 的正常桌面显存波动使默认 `9.5 GiB` 安全线误拦截核心任务。
2. `package_for_deploy.ps1` 默认把 `E:\models` 当成源目录，可能将相邻项目和大文件一并打包。
3. PowerShell 5.1 不会自动把 `pip.exe` 的非零退出码转成异常，初始化脚本可能在安装失败后继续并显示完成。
4. WebUI“打开目录”前端发送 JSON，后端却要求查询参数，真实浏览器稳定返回 HTTP 422。
5. WebUI 的 `max_new_tokens`、`chunk_seconds`、`min_cuda_free_gb`、`force_cpu` 四个字段被 Pydantic 静默丢弃。
6. 后台唯一工作线程遇到边界异常会退出，后续任务永久排队；Windows 并发替换 JSON 还会触发 `WinError 5`。

本次共归纳 24 个已确认问题或风险项：21 项已完成代码修复，2 项已完成风险缓解并保留明确边界，1 项属于现有虚拟环境的非项目依赖冲突，未擅自卸载用户包。没有发现仍由项目代码导致的 P0 阻断项。

当前结论：

- 核心 ASR 链路在本机 RTX 4070 SUPER 上已实际跑通：8 秒样本完成 ASR → ForcedAligner → FunASR 标点 → 分句 → wav/txt/index/meta 导出。
- 修复前默认 `9.5` 失败，同一流程显式改为 `9.0` 后成功；修复后的所有入口和配置默认值已统一为 `9.0`。
- 修复后第一次复测时，另一个 `E:\GPT-SoVITS-v2pro-20250604\runtime\python.exe` 正占用约 11.9/12.0 GiB 显存，安全预检按设计快速失败；该外部任务自然结束后再次复测，修复后的默认 9.0 GiB 完整 GPU 流程在约 62 秒内 **PASS**。
- WebUI 已通过隔离运行目录、真实 Uvicorn 和真实浏览器验证；目录接口从 422 恢复为 200，四个运行字段能保存并进入命令构造。
- 单元/接口测试从 48 个增加到 63 个（最终数量以本报告末尾最后一轮命令输出为准）；Ruff、格式、Mypy、编译、PowerShell AST、JSON 和 JavaScript 语法检查均已纳入回归。

## 2. 项目与环境信息

### 2.1 项目用途与运行链路

本项目是 Windows 本地离线语音识别与句子级切片工具。核心链路如下：

```text
音频文件/目录
  ├─ CLI：run_cli.bat → run.ps1
  └─ WebUI：run_webui.bat → start_webui.ps1 → FastAPI/Uvicorn
                                            ↓
                                    webui.service 后台队列
                                            ↓
                                         run.ps1
                                            ↓
scripts/asr_sentence_segment.py
  ffmpeg 转 16 kHz 单声道 WAV
  → Qwen3-ASR-1.7B 转写
  → Qwen3-ForcedAligner-0.6B 字符时间戳
  → 可选 FunASR 标点恢复
  → 停顿/标点/时长约束分句
  → segments/*.wav、*.txt、index.jsonl、full_text.txt、meta.json
  → 可选 qwen3_tts.jsonl
```

没有数据库、数据库迁移、消息队列服务器、Node 前端构建链或容器编排。WebUI 是 FastAPI 静态页面 + 原生 JavaScript；任务状态保存在 `.cache\webui\jobs.json`。

### 2.2 主要目录

| 路径 | 作用 |
|---|---|
| `scripts/` | ASR、对齐、标点、分句、导出、自检和共享配置读取 |
| `webui/` | FastAPI 路由、后台任务服务、静态 HTML/CSS/JS |
| `configs/defaults.json` | CLI/WebUI/Python 共享的 5 个分句默认值 |
| `configs/webui/` | 可复用 WebUI 任务预设，带 `_guide` 中文字段说明 |
| `configs/hotwords/` | 长期热词库，每行一个词或短语 |
| `models/` | Qwen3-ASR 与 ForcedAligner 本地模型（Git 忽略） |
| `inputs/` | 待处理音频（Git 忽略） |
| `outputs/` | CLI/WebUI 结果（Git 忽略） |
| `.cache/` | Hugging Face/ModelScope/Pip/任务日志/临时文件（Git 忽略） |
| `.venv/` | Python 虚拟环境（Git 忽略） |
| `tests/` | 纯函数、接口契约、JSON 原子写和执行器稳定性测试 |

### 2.3 技术栈与实测版本

| 项目 | 实测信息 |
|---|---|
| 操作系统 | Windows 10 API 标识，内核版本 `10.0.26200` |
| PowerShell | Windows PowerShell 5.1 启动链已实测 |
| Python | 3.11.9，项目要求 ≥ 3.10 |
| 包管理 | pip；运行依赖见 `requirements.txt`，开发检查见 `requirements-dev.txt` |
| Web 后端 | FastAPI + Uvicorn |
| 前端 | 原生 HTML/CSS/JavaScript，无需 npm/build |
| 音频工具 | ffmpeg/ffprobe，实测 2025-08-25 构建 |
| 推理框架 | PyTorch 2.6.0+cu124，CUDA 可用 |
| GPU | NVIDIA GeForce RTX 4070 SUPER，约 12 GiB 显存 |
| ASR | qwen-asr + 本地 Qwen3-ASR-1.7B |
| 对齐 | 本地 Qwen3-ForcedAligner-0.6B |
| 标点 | FunASR + `iic/punc_ct-transformer_cn-en-common-vocab471067-large` |
| 外部网络 | 首次下载 Python 包、Qwen 模型或标点模型时需要；本地缓存齐全后核心链路可离线运行 |

### 2.4 关键配置要求

- 所有项目内相对路径以项目根目录为基准，推荐使用 `.\inputs`、`.\models\...`。
- 默认 GPU 安全线为 `9.0 GiB`；这是启动前保护，不是质量参数。显存明显不足时应关闭占用进程，不应首先设为 0。
- `batch_size=1`、`chunk_seconds=60`、`max_new_tokens=1024` 是 12 GiB 显卡的保守起点。
- WebUI 默认只监听 `127.0.0.1`。当前没有登录认证，不应直接绑定公网或不可信局域网。
- `QWEN3_ASR_WEBUI_RUNTIME_ROOT` 是测试/多实例隔离用环境变量；普通用户无需设置。

## 3. 原始故障现象与根因

### 3.1 实际复现记录

1. 默认 CLI 处理 8 秒真实音频时，GPU 空闲约 `9.48 GiB`，低于旧默认 `9.5 GiB`，抛出 `GpuSafetyPrecheckError`，模型尚未加载。
2. 同一命令只覆盖 `-MinCudaFreeGB 9.0` 后，完整流程在约 90.6 秒内成功并导出 1 个片段；ASR 推理本身约 2 秒，首次 FunASR 标点模型下载/加载是主要冷启动成本。
3. 真实浏览器点击“打开输入目录”时，`POST /api/system/open` 返回 422；错误位置显示后端在找 query `target`，而前端发送的是 JSON `{target}`。
4. 直接构造 `AsrJobPayload`/`PreferencesPayload` 时，四个 WebUI 字段不在 `model_dump()` 中，证明值在进入服务层前已被丢弃。
5. 并发导入多个 WebUI 服务进程时，`tmp.replace(jobs.json)` 在 Windows 上触发 `PermissionError [WinError 5]`。
6. `package_for_deploy.ps1` 的默认源目录解析成 `E:\models`，而非项目根目录；代码注释与实际表达式相互矛盾。
7. `pip check` 报告现有虚拟环境中 `uncompyle6 3.9.3` 要求 `xdis<6.3`，但安装的是 `xdis 6.3.0`。两者均不在本项目依赖文件中。

## 4. 问题清单

| 编号 | 优先级 | 问题、影响与根因 | 修复与涉及文件 | 状态/验证 |
|---|---|---|---|---|
| QASR-001 | P0 | 旧 `9.5 GiB` 默认线高于本机正常桌面状态下的 9.48 GiB，核心任务被几十 MiB 波动误拦截 | 所有 CLI/Python/WebUI/JSON/README 默认统一为 9.0，并解释 GiB 与安全余量；`run.ps1`、`scripts/asr_sentence_segment.py`、`webui/*`、`configs/*`、`README.md` | **FIXED**；显式 9.0 与修复后默认 9.0 两次真实全流程均 PASS |
| QASR-002 | P0 | 部署脚本默认用脚本目录的父目录，可能把整个 `E:\models` 及相邻项目打包，存在数据泄露和超大包风险 | 默认改为 `$PSScriptRoot`，校验 5 个项目入口，清理前再次校验临时路径；`package_for_deploy.ps1` | **FIXED**；错误源目录快速拒绝，代码包 ZIP 烟测 PASS |
| QASR-003 | P0 | PowerShell 5.1 不会因原生程序非零退出码自动进入 catch，pip/venv/模型下载/自检失败后脚本可能继续并显示完成 | 新增 `Invoke-NativeChecked`，所有关键原生命令立即检查 `$LASTEXITCODE`；`bootstrap.ps1` | **FIXED**；模拟 exit 7 被捕获并转成异常 PASS |
| QASR-004 | P1 | WebUI 打开目录前端发 JSON，FastAPI 后端把标量当 query 参数，真实点击稳定 422 | 新增 `OpenSystemPathPayload`，后端读取 `payload.target`；`webui/app.py` | **FIXED**；TestClient 200 + Playwright 真浏览器 POST 200、0 console error |
| QASR-005 | P1 | 四个性能/安全字段未声明在 Pydantic 请求模型中，Pydantic 默认忽略额外字段，网页“改了但不生效” | 同步补全任务和偏好模型，增加中文专业解释与命令构造测试；`webui/app.py`、`tests/test_webui_contracts.py` | **FIXED**；浏览器保存后 API 返回 1536/30/8.5/true，命令构造测试 PASS |
| QASR-006 | P1 | 唯一后台工作线程在 `_run_job` 边界异常时退出，后续任务永久排队 | worker 增加异常边界、失败状态/日志记录、`task_done()` finally 和运行时热词清理；`webui/service.py` | **FIXED**；模拟首任务异常后第二任务仍执行 PASS |
| QASR-007 | P1 | Windows 文件索引器/杀毒/另一进程可能短暂占用 jobs.json，原子替换直接失败 | 保留临时文件+fsync+replace，并对 WinError 5/32/33 做 6 次有上限指数退避；`webui/service.py` | **FIXED**；前两次 PermissionError、第三次成功测试 PASS |
| QASR-008 | P1 | 两个受版本控制的 WebUI 预设包含维护者个人 D:/E: 绝对路径，换电脑即失效并泄露目录信息 | 改为 `.\inputs`/自动输出，补齐每个字段的 `_guide`；保存配置时自动保留说明；`configs/webui/*`、`webui/service.py` | **FIXED**；JSON 解析、无个人盘符搜索、配置保存说明测试 PASS |
| QASR-009 | P1 | 标点规范化无条件删除空格，`hello world` 会变成 `helloworld`；韩文同样依赖词间空格 | 只移除汉字/日文假名间的排版空格与标点两侧空格，英文/韩文等保留零时长空格并安全合并时间线；核心脚本/测试 | **FIXED**；英文、韩文和时间线回归 PASS |
| QASR-010 | P1 | 模型加载对所有 TypeError 都做兼容回退，第三方模型内部 TypeError 也会被掩盖并重复加载大模型 | 仅当消息明确是 unexpected keyword argument 且字段匹配时回退；核心脚本/测试 | **FIXED**；兼容错误/内部错误判别测试 PASS |
| QASR-011 | P1 | 标点异常被吞后任务显示成功，meta 仍只记录模型名，用户无法知道实际是无标点降级 | 新增 `punctuation_applied`、`punctuation_warning`，合并到通用 warning 供 WebUI 显示；核心脚本/测试 | **FIXED**；模拟标点服务故障的 meta 集成测试 PASS |
| QASR-012 | P1 | 目录批处理遇到第一个坏音频就终止，后续正常文件没有机会执行 | 每文件 try/catch，保留成功结果、继续后续项、最终汇总失败并返回非零；`run.ps1` | **FIXED**；两个损坏 wav 均被尝试，最后失败数=2、退出码非零 PASS |
| QASR-013 | P1 | 离线打包同时查 PyPI/CUDA 源但不固定 Torch 版本，可能因 PyPI 版本更高而误选 CPU wheel；torch/torchaudio 还可能不配套 | 安装和打包默认固定已实测共同版本 2.6.0，可显式覆盖；`bootstrap.ps1`、`package_for_deploy.ps1`、README | **FIXED**；参数/脚本语法和当前实测版本一致；完整 wheel 下载标记 NOT RUN |
| QASR-014 | P1 | 部署包排除整个 `.cache`，同时也排除了约 1.11 GiB 的默认 FunASR 标点模型；无网目标机会静默降级 | 完整包只定点复制已完成的标点缓存，跳过下载临时目录/任务状态；指南按是否包含动态说明；部署脚本/README | **FIXED**；小型模型夹具证明定点复制和动态指南 PASS，本机 1.11 GiB 缓存完整性 PASS；完整大包 NOT RUN |
| QASR-015 | P2 | CLI/WebUI 对负数、0、NaN、Infinity、min>max 等边界验证不一致，错误可能拖到模型加载后才出现 | Python、PowerShell、服务层统一快速校验并给新手可操作中文提示；核心脚本、`run.ps1`、服务层、测试 | **FIXED**；参数化测试和 ShowConfig/AST PASS |
| QASR-016 | P2 | Web 请求无超时；`setInterval` 不等待 Promise，后端慢时轮询可重叠，旧响应可能覆盖新状态 | 15 秒 AbortController 超时、jobs/results in-flight 标志和 finally 复位；`webui/static/app.js` | **FIXED**；Node 语法、真实页面轮询与 0 console error PASS |
| QASR-017 | P2 | 热词库加载失败时函数吞错但切换仍返回成功；服务端规范化热词后前端仍用旧 textarea 当“已保存”基准 | 加载返回布尔成功，失败恢复旧下拉；保存后使用服务端规范化内容更新 textarea/基准；`app.js` | **FIXED**；静态逻辑审查 + Node 语法 PASS，专用浏览器故障注入 NOT RUN |
| QASR-018 | P2 | 无 BOM 的中文 ps1 在 Windows PowerShell 5.1 中乱码；两个 bat 未先切 UTF-8；旧 `TRANSFORMERS_CACHE` 每次发弃用警告 | ps1 UTF-8 BOM、bat 入口 UTF-8、清除弃用变量并依赖 HF_HOME；env/bat 文件 | **FIXED**；PowerShell 5.1、run_cli.bat、bootstrap.bat 中文输出 PASS，弃用警告不再由项目设置 |
| QASR-019 | P2 | 部署指南声称 python.org embeddable ZIP 可解压内部 zip 来启用 pip/venv，此流程不成立；脚本结尾 Read-Host 阻塞自动化 | 改用官方完整版 Python 指引；默认不交互、不删除；仅 `-RemoveStaging` 安全清理；部署脚本/README | **FIXED**；随包 DEPLOY_GUIDE 内容与清理烟测 PASS |
| QASR-020 | P2 | 同名 ZIP 到最后才失败；旧部署 ZIP 可被再次打入新包；时间戳 staging 可能冲突 | 输出路径前置校验、排除 zip/7z/rar、GUID staging、自动建父目录；部署脚本 | **FIXED**；代码包烟测 PASS；同名包在约 1.38 秒内拒绝且未开始复制 |
| QASR-021 | P2 | WebUI 资源查询串长期不变，已访问用户可能继续缓存旧 JS 契约 | HTML 资源版本更新为 `audit-20260716`；`webui/static/index.html` | **FIXED**；真实浏览器加载新字段/新接口 PASS |
| QASR-022 | P2 | 项目配置了 Mypy/Ruff/Pytest，却没有可复现的开发依赖入口；Mypy 原本未安装 | 新增带中文说明的 `requirements-dev.txt`，修复两个真实类型问题；README 补检查命令 | **FIXED**；Mypy 6 个源码文件无问题、Ruff/pytest PASS |
| QASR-023 | P2 | WebUI 无认证但允许绑定 0.0.0.0，局域网用户可能调用任务/配置/打开目录接口 | 非回环地址启动时输出两条高可见安全警告，默认仍是 127.0.0.1；`start_webui.ps1` | **MITIGATED**；未强行引入账号系统；外网暴露仍不受支持 |
| QASR-024 | P3 | 多个手工启动的 WebUI 进程共享同一运行目录时仍是最后写入者覆盖；原子重试只能避免文件损坏，不能提供跨进程事务 | 增加运行目录隔离环境变量与文档注释；推荐单实例或每实例独立目录；`webui/service.py` | **DOCUMENTED/MITIGATED**；没有引入重量级锁依赖 |

## 5. 修改文件清单

### 5.1 新增文件

| 文件 | 目的 |
|---|---|
| `requirements-dev.txt` | 统一 Ruff、Pytest、Mypy、httpx 开发检查依赖，并解释与运行依赖的区别 |
| `tests/test_webui_contracts.py` | 覆盖四字段契约、打开目录 JSON、Windows JSON 重试、配置 `_guide`、worker 存活 |
| `TROUBLESHOOTING_AND_OPTIMIZATION_REPORT.md` | 本次完整排障、修复、验证和运行说明 |

### 5.2 修改文件

| 文件 | 主要修改目的 |
|---|---|
| `.gitignore` | 忽略质量工具缓存、覆盖率和部署 ZIP，避免误提交可再生/超大产物 |
| `README.md` | 同步 9.0 GiB、meta 降级字段、批处理策略、部署与质量检查说明 |
| `bootstrap.bat`、`run_cli.bat` | UTF-8 控制台入口，修复中文显示 |
| `bootstrap.ps1` | 原生命令退出码检查、固定已验证 Torch 版本 |
| `env.ps1` | UTF-8 BOM，移除弃用 TRANSFORMERS_CACHE |
| `run.ps1` | 9.0 默认、完整数值校验、批处理继续与失败汇总 |
| `start_webui.ps1` | 非回环监听安全警告 |
| `package_for_deploy.ps1` | 修复源根目录、离线依赖、标点模型、Python 指引、无交互清理、输出保护 |
| `configs/webui/current_workflow.json` | 可迁移通用默认值和全字段中文 `_guide` |
| `configs/webui/qwen3_tts_finetune.json` | 可迁移 TTS 导出预设和全字段中文 `_guide` |
| `scripts/asr_sentence_segment.py` | 9.0、参数校验、多语言空格、精确 TypeError、标点降级元数据 |
| `scripts/self_check.py` | Ruff 兼容、ffmpeg 10 秒超时、现代类型标注 |
| `tests/test_asr_sentence.py` | 新增空格、时间线、兼容异常、参数边界、标点降级测试 |
| `webui/app.py` | 补齐 Pydantic 字段并修复打开目录请求体 |
| `webui/service.py` | JSON 重试、worker 保护、可隔离运行目录、配置说明、校验与类型修复 |
| `webui/static/app.js` | 请求超时、防重叠轮询、热词状态修复 |
| `webui/static/index.html` | 更新静态资源缓存版本 |

未删除任何文件。

## 6. 关键修改说明

### 6.1 显存安全线：从“理论整数”改为实机可用安全余量

旧值 9.5 GiB 与实机空闲 9.48 GiB 只差约 20 MiB，属于 Windows 桌面合成和普通应用的正常波动，不代表模型一定无法加载。同一硬件在 9.0 GiB 线下完成了真实全流程，因此统一改为 9.0。保护机制本身保留：当前只有 0.08 GiB 时仍会快速失败，避免桌面卡死。

### 6.2 前后端契约：不允许“网页看起来保存了，后端却丢掉”

四个字段同时加入任务模型和偏好模型，并用测试验证三层：Pydantic `model_dump()`、服务命令行构造、真实浏览器保存后的 GET API。打开目录同样以真实前端 JSON 为权威同步后端。

### 6.3 状态写入与 worker：失败可见、线程继续

JSON 写入仍采用“临时文件 → flush/fsync → replace”，保证不会留下半截文件；Windows 短暂占用采用最多 6 次指数退避，最终失败仍抛出，不伪造成功。worker 在单任务边界捕获普通 Exception、标记失败并始终归还 queue 计数，避免一个任务摧毁整个队列。

### 6.4 标点是可降级步骤，但降级必须可追踪

标点模型不负责听音频。它失败时保留 ASR 原文是合理的可用性策略，但现在 `meta.json` 和 WebUI 会明确告诉用户没有应用标点以及原因。英文/韩文空格作为正文排版信息保留，新增空格使用零时长时间戳，不会拉长 wav。

### 6.5 部署包：可迁移、可复现、不会误带用户数据

源目录校验防止打包上级目录；`.cache` 仍整体排除，只按完整文件标志定点带入标点模型；Torch 版本固定，避免 CPU/CUDA 变体混用；默认不做交互式递归删除。`-SkipModels` 可生成小型代码包，完整包则保留本地 Qwen 模型和可用的标点模型。

## 7. 测试与验证结果

### 7.1 最终自动化与静态检查

| 状态 | 命令/检查 | 结果 |
|---|---|---|
| PASS | `.\.venv\Scripts\python.exe -m pytest` | 所有测试通过；覆盖纯函数、WebUI 契约、标点降级、JSON 重试、worker |
| PASS | `.\.venv\Scripts\python.exe -m ruff check .` | All checks passed |
| PASS | `.\.venv\Scripts\python.exe -m ruff format --check .` | 所有 Python 文件已格式化 |
| PASS | `.\.venv\Scripts\python.exe -m mypy scripts webui` | 6 个源码文件无类型问题 |
| PASS | `.\.venv\Scripts\python.exe -m compileall -q scripts webui tests` | Python 编译通过 |
| FAIL | `.\.venv\Scripts\python.exe -m pip check` | 非项目包 uncompyle6/xdis 版本冲突；核心依赖导入与真实业务仍通过，详见 8.1 |
| PASS | PowerShell AST 解析全部根目录 `*.ps1` | 无解析错误 |
| PASS | 递归解析 `configs/**/*.json` | 3 个 JSON 全部有效 |
| PASS | `node --check webui\static\app.js` | JavaScript 语法通过 |
| PASS | `git diff --check` | 无尾随空格/冲突标记 |

### 7.2 启动、接口与业务链路

| 状态 | 实际操作 | 结果 |
|---|---|---|
| PASS | `scripts/self_check.py` | Python、venv、ffmpeg、torch/CUDA、numpy、soundfile、qwen_asr、funasr、modelscope 全部 OK |
| PASS | `run_cli.bat -ShowConfig` | Windows cmd + PowerShell 5.1 中文正常，默认 `MinCudaFreeGB=9` |
| PASS | `bootstrap.bat -InstallFfmpegOnly` | 正确识别现有 ffmpeg 并安全跳过安装 |
| PASS | `run_webui.bat -OnlyCheck -NoAutoBootstrap -NoModelDownload -SkipFfmpegInstall` | WebUI 核心依赖、ffmpeg、本地模型检查通过，不启动服务 |
| PASS | Uvicorn 隔离运行目录 + Playwright 真实 Chromium | 页面加载；`POST /api/system/open` 200；console 0 error/0 warning |
| PASS | 浏览器填写并保存 1536/30/8.5/ForceCpu | GET preferences 返回完全一致的值 |
| PASS | 8 秒真实音频，旧代码路径显式 `-MinCudaFreeGB 9.0` | ASR→对齐→标点→导出全流程成功，1 个片段 |
| PASS | 修复后不覆盖阈值的默认 GPU 全流程 | 外部任务自然结束后空闲 11.11 GiB；完整命令约 62 秒、ASR+对齐约 3 秒，导出 1 个 16 kHz 单声道片段；meta 为 9.0 / punctuation=true / 无 warning |
| PASS | GPU 被外部进程占满的错误场景 | 空闲仅 0.08 GiB 时安全预检快速拒绝，没有继续加载模型或拖卡桌面；未擅自结束用户进程 |
| PASS | 两个伪造损坏 wav 的目录批处理 | 两项均执行，最终汇总 2 失败并返回非零，不在第一项停止 |

### 7.3 部署与失败路径

| 状态 | 实际操作 | 结果 |
|---|---|---|
| PASS | `package_for_deploy.ps1 -SourceRoot E:\models ...` | 在复制前拒绝，指出缺少项目入口 |
| PASS | `-SkipWheelDownload -SkipModels -RemoveStaging` 代码包烟测 | 生成约 154 KiB ZIP、包含入口/指南/配置/离线 requirements，并安全清理 staging |
| PASS | 对同一个 `-OutputZip` 立即重跑 | 约 1.38 秒内返回非零并拒绝覆盖，没有先复制数万文件 |
| PASS | 解读 ZIP 中 `DEPLOY_GUIDE.md` | 明确模型是否包含、拒绝 embeddable ZIP 误用、使用 `python -m venv` |
| PASS | 使用小型完整标点模型夹具执行部署打包 | ZIP 定点包含 `.cache/modelscope/.../model.pt`，指南显示“可离线恢复标点” |
| PASS | 从 bootstrap AST 单独调用 `Invoke-NativeChecked` 执行 exit 7 | 捕获非零退出码并抛中文异常 |
| NOT RUN | 完整下载全部离线 wheels | 会下载数 GB PyTorch/传递依赖；已验证命令构造与版本策略，但未把网络/带宽消耗伪写成 PASS |
| NOT RUN | 包含约 6 GiB Qwen 模型 + 1.11 GiB 标点模型的最终完整 ZIP | 已做小包真实压缩和本机标点缓存完整性检查；未重复制造超大临时产物 |
| NOT RUN | 从空目录完整重建 `.venv` | 会删除/替换现有可运行环境，属于破坏性验证；改用自检、pip 检查和原生命令失败注入 |

### 7.4 不适用项

- 数据库初始化/迁移：项目没有数据库或迁移文件，**NOT RUN（不适用）**。
- 前端 npm 构建：前端是原生静态文件，没有 `package.json` 或构建步骤，**NOT RUN（不适用）**；已用 Node 语法和真实浏览器替代验证。
- 容器启动：项目没有 Dockerfile/Compose，**NOT RUN（不适用）**。

## 8. 未解决问题与边界

### 8.1 现有虚拟环境的非项目依赖冲突

`pip check` 仍报告：

```text
uncompyle6 3.9.3 requires xdis<6.3,>=6.1.0, but xdis 6.3.0 is installed
```

`uncompyle6`/`xdis` 不在 `requirements.txt` 或 `requirements-dev.txt`，核心包导入和实际 ASR 已通过。为避免破坏用户在该 venv 中另行安装的反编译工具，本次没有擅自卸载或降级。建议近期用全新 `.venv` 重装项目依赖，或由用户确认这些工具不用后再移除。

### 8.2 审计期间的临时 GPU 资源竞争（已解除）

审计中途观察到 `E:\GPT-SoVITS-v2pro-20250604\runtime\python.exe` 占用几乎全部 RTX 4070 SUPER 显存。项目的 9.0 GiB 预检正确保护了系统；本次没有强制终止不属于本项目的进程。该任务之后自然结束，默认 GPU 全流程已经重新执行并 PASS，因此这不是当前未解决项，只保留为资源竞争故障样例。

### 8.3 多 WebUI 进程共享状态目录

原子写重试解决“短暂占用导致 JSON 损坏/异常”，但没有提供跨进程事务。不要手工启动多个共享 `.cache\webui` 的实例；确需并行时为每个进程设置不同的 `QWEN3_ASR_WEBUI_RUNTIME_ROOT`。单实例是当前支持边界。

### 8.4 非回环网络访问

WebUI 没有身份认证。默认 127.0.0.1 安全边界不变；如果用户自行改为 0.0.0.0，启动器会警告，但不会替用户配置防火墙、TLS、反向代理或账号系统。不要直接暴露到公网。

### 8.5 运行依赖仍非完全锁定

PyTorch/torchaudio 已固定为实测 2.6.0，但 `qwen-asr`、FastAPI、FunASR 等运行依赖仍采用非锁定清单。这对初学者安装更宽容，但长期可复现性有限。建议发布正式版本时从干净环境生成经过验证的 constraints/lock 文件，而不是直接复制当前含个人额外包的 `pip freeze`。

### 8.6 FunASR 第三方控制台噪声

FunASR 1.3.9 在真实标点回归中重复打印两组 jieba 初始化行，并显示过一个负数 `rtf_avg`。标点输出、时间线、片段和 meta 均正确，这些行来自第三方包内部日志/计时，不是本项目重复执行任务的证据。本次没有通过全局屏蔽 stdout 来掩盖它，以免同时丢失真正的模型加载错误；后续升级 FunASR 时应重新观察。

## 9. 后续建议

### 9.1 必须尽快处理

1. 正式离线交付前，在与目标机相同的 Python 3.11 x64 环境执行一次不带 `-SkipWheelDownload/-SkipModels` 的完整打包，并在断网测试机安装验证。

### 9.2 建议近期处理

1. 建一个干净 `.venv` 消除 uncompyle6/xdis 的环境污染，不要在生产 ASR 环境混装反编译工具。
2. 为运行依赖生成经过短音频、WebUI、离线部署共同验证的 constraints 文件。
3. 增加一个不加载模型的 PowerShell Pester 测试层，直接覆盖批处理汇总、bat 入口和部署参数组合。

### 9.3 长期架构改进

1. 如果未来必须多实例运行，将 jobs 状态迁移到 SQLite（事务/锁）或实现明确的单实例进程锁；不要继续扩展 JSON 为多写者数据库。
2. 如果需要局域网共享，引入明确的认证、CSRF/来源策略、TLS 反向代理和最小权限设计。
3. 对长批次增加可恢复清单：记录每个源文件的哈希、参数和完成状态，重跑时只处理失败/变化项。

### 9.4 可选优化

- 在稳定 GPU 空闲环境中分别以 30/60/90 秒分块做同一长音频基准，记录峰值显存、实时倍速和转写一致性，再决定是否按显卡型号提供预设；当前没有用理论猜测替代基准。

## 10. 当前验证过的程序运行说明

### 10.1 首次准备环境

在项目根目录双击或执行：

```bat
bootstrap.bat
```

等价 PowerShell：

```powershell
.\bootstrap.ps1
```

脚本会检查/安装项目内 ffmpeg、创建 `.venv`、安装固定配套的 PyTorch 2.6.0/torchaudio 2.6.0 和运行依赖。网络失败会返回非零退出码，不会继续伪报完成。

### 10.2 准备音频与配置

1. 把 wav/mp3/m4a/flac/aac/ogg/opus/wma/webm/mp4/mkv/mov 放到 `.\inputs`。
2. 第一次保持 `configs\webui\current_workflow.json` 或 `run.ps1` 默认值。
3. `configs\webui\*.json` 的 `_guide.fields` 对每个配置项都有中文解释；`_guide` 不参与运行。

### 10.3 启动 WebUI

```bat
run_webui.bat
```

或：

```powershell
.\start_webui.ps1
```

默认地址是 `http://127.0.0.1:8765`。停止方法：回到启动 WebUI 的终端按 `Ctrl+C`；不要直接杀死未知 Python 进程。

只检查、不启动：

```powershell
.\start_webui.ps1 -OnlyCheck -NoAutoBootstrap -NoModelDownload -SkipFfmpegInstall
```

### 10.4 CLI 处理短音频

```bat
run_cli.bat -Audio .\inputs\demo.wav -Language Chinese
```

指定输出目录：

```powershell
.\run.ps1 -Audio .\inputs\demo.wav -OutDir .\outputs\demo_run -Language Chinese
```

如果提示空闲显存不足：

1. 先执行 `nvidia-smi` 看显存状态。
2. 关闭或等待 ComfyUI、GPT-SoVITS、游戏、视频、其它大模型任务结束。
3. 保持 `BatchSize=1`；长音频可把 `ChunkSeconds` 从 60 降到 30。
4. `MinCudaFreeGB=0` 会关闭保护，只适合明确理解风险的排查，不是首选修复。
5. `-ForceCpu` 可验证流程，但 1.7B + 对齐模型在 CPU 上很慢且仍需要大量内存。

### 10.5 开发检查

```powershell
.\.venv\Scripts\python.exe -m pip install -r .\requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
.\.venv\Scripts\python.exe -m mypy scripts webui
.\.venv\Scripts\python.exe .\scripts\self_check.py
```

### 10.6 生成部署包

完整 CUDA 12.4 包（会很大）：

```powershell
.\package_for_deploy.ps1 -OutputZip .\Qwen3-ASR_deploy.zip -TorchVariant cu124
```

代码包（目标机另行准备模型/依赖）：

```powershell
.\package_for_deploy.ps1 -OutputZip .\Qwen3-ASR_code_only.zip -SkipWheelDownload -SkipModels
```

默认保留 staging 供核对；确认无需调试时显式加 `-RemoveStaging`。脚本不会覆盖同名 ZIP。

### 10.7 常见故障快速定位

| 现象 | 优先检查 |
|---|---|
| 虚拟环境不存在/包导入失败 | 运行 `bootstrap.bat`，看第一个非零退出命令的最后几行 |
| ffmpeg/ffprobe 找不到 | `bootstrap.bat -InstallFfmpegOnly` |
| 显存不足 | `nvidia-smi`、关闭其它推理进程、BatchSize=1、ChunkSeconds=30 |
| WebUI 端口占用 | `run_webui.bat -Port 8766` |
| 标点失败但有文字 | 查看 `meta.json` 的 `punctuation_warning`；核心 ASR 已降级保留原文 |
| 某个批处理文件坏掉 | 最后失败清单列出文件；成功项已保留，只重跑失败项 |
| 配置看不懂 | 查看 `configs\webui\*.json` 的 `_guide.fields` 或 WebUI 字段下方长说明 |
| pip check 的 uncompyle6/xdis 冲突 | 使用干净项目 venv，或确认不用反编译工具后再处理；它不是本项目依赖 |
