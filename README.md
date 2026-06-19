# Qwen3-ASR 本地使用教程


这是一份面向入门用户和进阶用户的 Windows / PowerShell 使用教程。  
本项目的核心作用不是“训练模型”，而是把本地音频文件跑完整个识别闭环：

`输入音频 -> 统一转码 -> 语音识别 -> 时间对齐 -> 默认标点恢复 -> 按句切分 -> 导出 wav/txt/index.jsonl`

如果你是电脑小白，先看下面的「小白 3 步快速开始（WebUI 优先）」；不懂 `ASR` / `Forced Alignment` / `JSONL` 也没关系，先跑起来再回来补概念。 如果你更想走命令行，优先用 `bootstrap.bat` + `run_cli.bat`，不需要先手动处理 PowerShell 执行策略。

## 小白 3 步快速开始（WebUI 优先）

> 新手优先用 WebUI。你不用先弄懂所有参数，先把界面跑起来最重要。

1. 第一次使用先准备环境
   - Python 版本至少 `3.10`
    - `.venv` 可以理解成“项目专用的 Python 小房间”，不用你手动创建，`bootstrap.bat` 会帮你处理
   - `ffmpeg`：项目会自动检测，如果电脑上没有会自动下载到项目内目录（`.tools\ffmpeg`），不需要你手动装
    - 如果你还没有初始化环境，先运行一次 `.\bootstrap.bat`
   - 第一次安装可能会比较慢，因为要下载 PyTorch、核心依赖，必要时还会下载模型

2. 双击 `run_webui.bat`
   - 这是给小白准备的最简单入口
   - 首次运行如果检测到缺少 ffmpeg，会自动下载（约 80 MB），请耐心等待
   - 如果你已经在 PowerShell 里，也可以运行 `.\start_webui.ps1`

3. 浏览器会自动打开 `http://127.0.0.1:8765`
   - 把要处理的音频放进 `.\inputs` 文件夹
   - 如果没有自动打开，就手动复制这个地址
   - 如果提示端口被占用，改用 `.\start_webui.ps1 -Port 8766`
   - WebUI 首屏会先做环境检查：如果某项是红色，直接按提示点"安装基础依赖""下载模型"或"打开输入目录"即可

小白第一次最容易卡住的 3 个地方：

- Python 太旧：请装 Python `3.10` 及以上
- 网络不稳定导致下载失败：重新运行一次通常就能恢复；Pip/Conda 镜像慢可以参考后面的『镜像源排错』章节
- 还没执行 `.\bootstrap.bat`：先把 `.venv` 和依赖装出来

如果你更想看命令行，直接往下跳到第 5 节；如果你更想先理解原理，继续看第 2 节。

---

## 1. 这个项目是做什么的（极简版）

这部分只讲最核心的作用。你如果只是想先跑起来，前面的 WebUI 快速开始已经够用了。

本项目基于：

- `Qwen/Qwen3-ASR-1.7B`：负责把音频识别成文字。
- `Qwen/Qwen3-ForcedAligner-0.6B`：负责把识别出的文字重新对齐到音频时间轴上。

然后项目会把整段音频切成一句一句的小片段，并导出：

- 每一句对应的音频切片 `.wav`
- 每一句对应的文本 `.txt`
- 一个机器可继续处理的索引文件 `index.jsonl`
- 全文文本 `full_text.txt`
- 本次运行参数记录 `meta.json`

这类工具常见用途有：

- 给长音频自动切句，方便人工校对
- 制作语音数据集
- 提取带时间边界的语音片段
- 后续拿去做配音、字幕、检索、标注等工作

---

## 2. 你需要先理解的几个基础概念（不懂可先跳过）

如果你是入门用户，这一段建议认真看一遍；如果你只是想先跑通项目，也可以先跳过，等跑通后再回来补理解。

### 2.1 ASR 是什么

`ASR` 是 `Automatic Speech Recognition`，中文通常叫“自动语音识别”。

它做的事情很直接：

- 输入：音频
- 输出：文字

例如一段音频里说了“大家好，欢迎来到这里”，ASR 就尝试把这句话识别出来。

### 2.2 Forced Alignment 是什么

`Forced Alignment` 中文常叫“强制对齐”或“时间对齐”。

它不是重新“猜一句话说了什么”，而是回答另一个问题：

“既然已经知道这句文本了，那么这句文本里的每一段内容在音频的什么时间出现？”

例如：

- “大家好”可能对应 `0.52s ~ 1.10s`
- “欢迎来到这里”可能对应 `1.10s ~ 2.40s`

这样项目后面才能把整段音频切成一句一句的小段。

### 2.3 为什么要先转成 16k 单声道 wav

不同音频可能来自：

- 手机录音
- 视频提取音轨
- AAC / MP3 / M4A / FLAC
- 双声道或多声道
- 各种采样率

为了让模型输入更稳定，脚本会先调用 `ffmpeg` 统一转成：

- 采样率 `16000 Hz`
- 单声道 `mono`
- `wav` 格式

这一步你可以理解为“先把原材料整理成模型更容易吃进去的标准格式”。

### 2.4 标点恢复是什么

语音识别模型输出的文本，很多时候标点不完整，或者比较口语化。  
所谓 `PuncModel`，就是一个“标点恢复模型”，用来给识别结果补逗号、句号、问号等。

它的作用不是必须的，但对“按句切分”很有帮助，因为：

- 没有标点时，分句更多依赖停顿长度
- 有了标点后，句子边界通常会更自然

### 2.5 JSONL 是什么

`JSONL` 是 `JSON Lines` 的缩写。  
它不是一个大 JSON 数组，而是“每一行都是一个独立的 JSON 对象”。

这样做的好处是：

- 方便程序一行一行读
- 大文件不需要一次性全部加载到内存
- 后续做批处理很方便

---

## 3. 当前项目的真实结构

下面是这个目录里真正重要的部分（以项目根目录为准）：

```text
项目根目录
├─ .cache                         # 项目私有缓存目录
├─ .venv                          # Python 虚拟环境
├─ inputs                         # 你放待处理音频的地方
├─ models                         # 本地模型目录
│  ├─ Qwen3-ASR-1.7B
│  └─ Qwen3-ForcedAligner-0.6B
├─ outputs                        # 输出结果目录
├─ configs                        # 默认参数、热词库、WebUI 配置
├─ scripts                        # 核心处理脚本
├─ webui                          # WebUI 代码
├─ env.ps1                        # 统一设置缓存目录等环境变量
├─ bootstrap.bat                  # 双击初始化环境
├─ bootstrap.ps1                  # 初始化环境、安装依赖、自检（高级用户可直接调）
├─ run_cli.bat                    # 双击启动 CLI
├─ run.ps1                        # 命令行主入口（高级用户可直接调）
├─ run_webui.bat                  # 双击启动 WebUI
├─ start_webui.ps1                # WebUI 启动脚本
└─ README.md                      # 当前这份教程
```

普通用户常用入口：

- `run_webui.bat`：双击启动 WebUI，最适合第一次使用
- `bootstrap.bat`：第一次安装环境时用，免手动处理执行策略
- `run_cli.bat`：双击启动 CLI，免手动处理执行策略
- `bootstrap.ps1` / `run.ps1`：高级用户直接调用时再用
- `inputs`：把音频放这里

普通用户通常可以先忽略：

- `.cache`：缓存
- `.venv`：虚拟环境
- `scripts`：核心实现，除非你要看代码或改流程
- `webui`：WebUI 代码，除非你要改界面
- `configs`：默认配置和热词，除非你要调高级参数

---

## 4. 路径统一说明：以后都优先用相对路径

后面的示例都默认从项目根目录出发写，例如：

- `.\inputs`：输入音频目录
- `.\outputs`：输出目录
- `.\models\Qwen3-ASR-1.7B`：ASR 模型目录
- `.\models\Qwen3-ForcedAligner-0.6B`：对齐模型目录

如果你看到旧资料里的绝对路径写法，不要照抄，直接换成当前项目根目录下的相对路径。

最推荐的做法是把待处理音频放到 `inputs` 文件夹里，然后直接处理 `.\inputs`。

### 方案 A：修改 `run.ps1` 里的配置

把 `Audio` 和 `OutDir` 改成相对路径或留空。

例如最推荐这样改：

```powershell
Audio = ".\inputs"
OutDir = ""
```

解释：

- `Audio = ".\inputs"` 表示从项目内的 `inputs` 文件夹读取音频
- `OutDir = ""` 表示让脚本自动创建带时间戳的输出目录，避免把历史结果混在一起

### 方案 B：运行时临时覆盖参数

也就是不改默认配置，而是在命令里明确指定。

这种方式适合：

- 你不想反复改文件
- 你想不同任务用不同输入路径

后文会给你可直接复制的命令。

---

## 5. 命令行快速开始（推荐 `run_cli.bat`）

如果你只是想先跑起来，优先按这条低门槛路径走：

- 第一次使用先双击 `bootstrap.bat`，完成环境初始化
- 之后双击 `run_cli.bat`，或者在命令行里运行 `.\run_cli.bat -ShowConfig` 先看配置
- 只有你要直接调用 `.ps1` 且被执行策略拦住时，才看下面的 PowerShell 高级用法

### 高级用法：直接调用 PowerShell

### 第 1 步：进入项目目录

如果你已经在项目根目录，这一步可以直接跳过；否则先切到项目根目录，再继续往下做。

```powershell
Set-Location "<项目根目录>"
```

如果你的项目不在这个位置，把上面的路径改成你自己的项目根目录。

### 第 2 步：如果你直接调用 `.ps1` 时被执行策略拦住，先临时放行

有些 Windows 默认会阻止 `.ps1` 脚本执行。  
如果你直接运行 `bootstrap.ps1` / `run.ps1` 时遇到“禁止运行脚本”之类报错，先执行：

```powershell
Set-ExecutionPolicy -Scope Process Bypass
```

说明：

- `-Scope Process` 表示只对当前 PowerShell 窗口生效
- 关闭这个窗口后，设置就失效了
- 这比改系统全局策略更安全，也更适合新手
- 新手日常优先用 `bootstrap.bat` / `run_cli.bat`，通常不需要手动执行这一步

### 第 3 步：加载项目环境变量

```powershell
. .\env.ps1
```

注意这里前面有一个点和一个空格，不能漏：

- `. .\env.ps1`

这叫“点源执行（dot-sourcing）”，意思是：

- 不开新进程
- 直接把脚本里的环境变量加载到当前 PowerShell 会话

如果你只是执行：

```powershell
.\env.ps1
```

那通常只是跑完脚本本身，但环境变量不一定保留在当前会话里。

### 第 4 步：初始化环境

```powershell
.\bootstrap.ps1
```

它会做这些事情：

1. 检查 Python 是否可用
2. 创建或复用 `.venv` 虚拟环境
3. 升级 `pip / setuptools / wheel`
4. 安装 `torch / torchaudio`
5. 安装 `qwen-asr / soundfile / modelscope`
6. 执行 `scripts/self_check.py` 做环境自检

第一次安装可能会比较久，这是正常的，因为依赖里有几个比较大的包。
当前默认会启用“标点恢复”，也就是让识别出的 `.txt` 带上逗号、句号、问号等标点。  
新环境运行 `bootstrap.ps1` 时会按 `requirements.txt` 安装 `funasr`；如果你是旧环境，或者之前已经初始化过但缺少标点依赖，可以额外运行：

```powershell
.\bootstrap.ps1 -InstallFunASR
```

### 第 5 步：准备输入音频

把你要处理的音频放进：

```text
.\inputs
```

支持的常见格式包括：

- `.wav`
- `.mp3`
- `.m4a`
- `.flac`
- `.aac`
- `.ogg`
- `.opus`
- `.wma`
- `.webm`
- `.mp4`
- `.mkv`
- `.mov`

说明：

- 这些后缀不代表它们全都是“纯音频容器”
- 例如 `.mp4`、`.mkv`、`.mov` 也可能是视频文件
- 只要里面有音频轨，脚本就能尝试提取并处理

### 第 6 步：运行识别和分句

如果你坚持直接用 PowerShell，最推荐的命令如下：

```powershell
.\run.ps1 `
  -Audio ".\inputs" `
  -OutDir "" `
  -AsrCkpt ".\models\Qwen3-ASR-1.7B" `
  -AlignerCkpt ".\models\Qwen3-ForcedAligner-0.6B" `
  -Language "None"
```

这里每个参数的意思是：

- `-Audio ".\inputs"`
  表示处理 `inputs` 文件夹中的所有音频

- `-OutDir ""`
  表示自动创建输出目录，例如 `outputs\run_20260314_190000`

- `-AsrCkpt`
  指向本地 ASR 模型目录

- `-AlignerCkpt`
  指向本地强制对齐模型目录

- `-Language "None"`
  表示让模型自动判断语言  
  如果你非常确定全部都是中文，也可以改成 `Chinese`

### 第 7 步：查看输出结果

脚本跑完后，你会在输出目录里看到类似内容：

```text
outputs\run_YYYYMMDD_HHMMSS
├─ _tmp
│  └─ input_16k_mono.wav
├─ segments
│  ├─ seg_0001__某一句话.wav
│  ├─ seg_0001__某一句话.txt
│  └─ ...
├─ data                          # 仅在 Qwen3-TTS 模式下生成
│  ├─ audio
│  │  ├─ utt0001.wav
│  │  └─ ...
│  └─ ref
│     └─ ref.wav
├─ full_text.txt
├─ index.jsonl
├─ qwen3_tts.jsonl              # 仅在 Qwen3-TTS 模式下生成
└─ meta.json
```

---

## 6. 推荐的两种使用方式

本项目主要有两种操作方式。你选一种长期使用即可。

### 方式 1：直接改 `run.ps1` 里的配置块

适合：

- 你每次都在这个项目里做同类任务
- 你希望双击 `run_cli.bat`，或者直接执行 `.\run.ps1` 就能跑
- 你不想每次在命令行里写很多参数

你只要打开 [run.ps1](./run.ps1) 的 `CONFIG` 配置块，重点改下面这些值：

新手最稳妥的做法是先保留这两个默认值：`Audio = ".\inputs"`、`OutDir = ""`。

```powershell
$Config = [ordered]@{
    Audio = ".\inputs"
    OutDir = ""
    DatasetFormat = "standard"
    RefAudio = ""
    AsrCkpt = ".\models\Qwen3-ASR-1.7B"
    AlignerCkpt = ".\models\Qwen3-ForcedAligner-0.6B"
    Language = "None"
    PuncModel = "iic/punc_ct-transformer_cn-en-common-vocab471067-large"
    PauseThreshold = 0.60
    MinDur = 0.80
    MaxDur = 8.00
    PadLeft = 0.05
    PadRight = 0.10
    EtaRTF = 2.0
    ScanSubfolders = $false
}
```

改完后执行：

```powershell
.\run.ps1
```

### 方式 2：不改文件，直接在命令行里覆盖参数

适合：

- 你想针对不同任务临时指定不同路径
- 你不想修改脚本文件
- 你希望把命令记录下来，方便以后直接复用

示例：

```powershell
.\run.ps1 `
  -Audio ".\inputs" `
  -OutDir ".\outputs\my_result" `
  -AsrCkpt ".\models\Qwen3-ASR-1.7B" `
  -AlignerCkpt ".\models\Qwen3-ForcedAligner-0.6B" `
  -Language "Chinese" `
  -ScanSubfolders
```

---

## 7. 每个配置项怎么理解

下面是最重要的配置项解释。你不用一次全记住，但建议收藏这张说明。

### 7.1 `Audio`

作用：输入音频路径。

可接受两种情况：

- 单个文件，例如 `.\inputs\demo.wav`
- 一个文件夹，例如 `.\inputs`

区别：

- 如果是单文件，脚本只处理这一个文件
- 如果是文件夹，脚本会批量处理里面的所有支持后缀音频

对新手的默认建议：把音频放进 `inputs` 文件夹，然后直接填 `.\inputs`。

### 7.2 `OutDir`

作用：输出目录。

建议你理解成两种模式：

- 填具体路径：结果就写入这个固定目录，例如 `.\outputs\my_run`
- 留空字符串 `""`：脚本自动创建 `.\outputs\run_时间戳`

对新手最推荐：

```powershell
OutDir = ""
```

因为这样最不容易把多次运行结果混在一起。

### 7.3 `DatasetFormat`

作用：决定输出清单的格式。

可选值：

- `standard`：默认值，生成普通的 `index.jsonl`
- `qwen3_tts`：额外生成适合 Qwen3-TTS 的 `qwen3_tts.jsonl`

如果你只是想先跑通识别和切句，先保持 `standard` 不动。

### 7.4 `AsrCkpt`

作用：ASR 模型位置。

建议直接填写本地目录，例如：

- `.\models\Qwen3-ASR-1.7B`

这个项目当前默认按“本地模型目录”路线工作。虽然模型仓库里也会看到像 `Qwen/Qwen3-ASR-1.7B` 这样的 Hub ID，但 `run.ps1` / WebUI 默认会先校验本地路径，所以新手不要直接填 Hub ID。
最稳妥的做法是：先运行 `.\bootstrap.ps1 -DownloadModels`，或者直接在 WebUI 里点“下载模型”，把模型补到 `models` 目录后，再在这里填写本地目录。

### 7.5 `AlignerCkpt`

作用：强制对齐模型位置。

建议和 `AsrCkpt` 一样，优先使用本地路径：

```powershell
.\models\Qwen3-ForcedAligner-0.6B
```

它的重要性很高，因为这个项目不是只要全文文本，还要切句，所以时间对齐是关键一步。

### 7.6 `Language`

作用：告诉模型识别语言。

常见用法：

- `Chinese`：你明确知道输入主要是中文
- `None`：让模型自动判断

建议：

- 语种很稳定时，用明确语言，结果通常更稳
- 混合语种或不确定时，用 `None`

### 7.7 `PuncModel`

作用：标点恢复模型。当前项目默认填写推荐模型，让输出的 `.txt` 更容易阅读，也让后续分句更自然。

如果为空字符串：

- 脚本会跳过标点恢复
- 输出文本通常会更像 ASR 原始结果，也就是很多句子没有逗号、句号、问号

如果填写模型名：

- 脚本会使用已经安装好的 `funasr` 来执行标点恢复
- 这里的“恢复”不是重新听音频，而是读取 ASR 识别出的文字，再根据上下文补标点

示例：

```powershell
PuncModel = "iic/punc_ct-transformer_cn-en-common-vocab471067-large"
```

注意：

- 如果你是旧环境，之前没有安装过 `funasr`
- 却又设置了 `PuncModel`
- 那么很可能会报依赖缺失

新环境直接运行 `.\bootstrap.ps1` 会安装 `funasr`。旧环境如果报缺依赖，运行 `.\bootstrap.ps1 -InstallFunASR` 修复即可。  
如果你明确想要无标点原文，可以把 `PuncModel` 改成空字符串。

### 7.8 `HotwordFile` / `HotwordLibrary`

作用：给模型一份“热词提示”，帮助它识别人名、品牌名、术语等容易错的词。

你可以把它理解成轻量版的 RAG 热词库：先告诉模型“这些词很重要”，再去做识别。

- `HotwordFile`：直接指定一个热词文件
- `HotwordLibrary`：使用 `configs\hotwords` 里预置的热词库文件名

如果你不确定要不要用，先留空，不影响正常跑通。

补充说明：

- `HotwordFile` 会优先于 `HotwordLibrary`
- `HotwordText` / 临时热词只影响当前任务，不会改动长期热词库
- 普通用户只要记住：长期热词放库里，临时热词写当前任务就行

### 7.9 `BatchSize`

作用：ASR 内部批大小。

默认建议先用 `1`。

- 值越大，通常越快，但也越吃显存
- 如果出现显存不足，第一步通常就是把它调小
- 只有你确认 GPU 余量足够时，再尝试调大

显存安全相关参数：

- `MaxNewTokens`：每个音频块最多生成多少 token。token 可以粗略理解为模型内部的一小段文字单位；默认 `1024`。值越大越不容易截断，但 KV 缓存越大、越吃显存，也更容易在异常片段上拖很久。
- `ChunkSeconds`：长音频安全分块时长，默认 `60` 秒。块越短，单次峰值显存越低；4070S 12GB 如果仍然卡，可以试 `30`。
- `MinCudaFreeGB`：GPU 推理前最低空闲显存，默认 `9.5` GiB。空闲显存不够时脚本会提前报错，避免 Windows 桌面一起卡死。
- `ForceCpu`：强制 CPU 推理。速度会慢很多，但适合用短音频排查“是不是显存/GPU 导致的问题”。

新手建议：`BatchSize = 1`、`MaxNewTokens = 1024`、`ChunkSeconds = 60`、`MinCudaFreeGB = 9.5` 先不要动。确认能稳定跑完后，再根据显存余量微调。

### 7.10 `PauseThreshold`

作用：按停顿切分句子的阈值，单位是秒。

你可以理解成：

- 相邻两段语音之间停顿超过这个值，就更倾向于切开

经验理解：

- 值更大：更不容易切句，结果会更长
- 值更小：更容易切句，结果会更碎

### 7.11 `MinDur`

作用：最短句时长，单位是秒。

用途：

- 避免切出过短、过碎的语音片段

例如某个片段只有 0.2 秒，通常没有太大使用价值，这个参数就是用来抑制这种情况的。

### 7.12 `MaxDur`

作用：最长句时长，单位是秒。

用途：

- 防止某个句子拖得过长
- 即使标点和停顿不明显，也会在必要时强制切开

### 7.13 `PadLeft` / `PadRight`

作用：切片时在左右两边额外补一点时间。

为什么需要它：

- 识别边界有时会比较“紧”
- 如果完全按字符时间戳去切，可能会把开头或结尾的轻微发音切掉

所以脚本默认会：

- 左边补 `0.05` 秒
- 右边补 `0.10` 秒

这是一种很常见的实用策略。

### 7.14 `EtaRTF`

作用：仅用于估算进度条和预计剩余时间。

这里的 `RTF` 可以理解为 `Real Time Factor` 相关概念：

- `1.0x` 实时：处理 1 秒音频，大约花 1 秒计算
- `2.0x`：处理速度大约是实时的 2 倍

注意：

- 它不会改变识别精度
- 它只影响“预计还要多久”的显示

### 7.15 `ScanSubfolders`

作用：当 `Audio` 是文件夹时，是否递归扫描子目录。

- `$false`：只看当前目录
- `$true`：继续往下扫描所有子目录

如果你的音频按多层目录分类存放，这个参数很有用。

### 7.16 `AudioExtensions`

作用：允许被识别为“可处理音频”的后缀白名单。

通常新手不需要改它，除非：

- 你有一些特殊格式文件
- 或者你想刻意排除某些后缀

---

## 8. 实际运行时，脚本内部到底做了什么

这一段是“理解闭环”的关键。

[scripts/asr_sentence_segment.py](./scripts/asr_sentence_segment.py) 的主流程大致如下：

### 第 1 步：把输入音频转成 16k / mono / wav

脚本调用 `ffmpeg`，把原始音频转成标准格式：

- 降采样到 16kHz
- 转成单声道
- 存到输出目录下的 `_tmp\input_16k_mono.wav`

意义：

- 让模型输入规范一致
- 降低后续处理的不确定性

### 第 2 步：加载 Qwen3-ASR 和 ForcedAligner

脚本会自动判断设备：

- 如果检测到 CUDA，就优先走 GPU
- 否则退回 CPU

并选择合适精度：

- GPU 支持时优先 `bfloat16` 或 `float16`
- CPU 时用 `float32`

这一步对应的是“准备推理环境”。

### 第 3 步：执行 ASR，并拿到时间戳

这一阶段不仅要识别文字，还要返回 `time_stamps`。

你可以把 `time_stamps` 理解成：

- 文本片段
- 每一段对应的开始时间
- 每一段对应的结束时间

这正是后面切句的依据。

### 第 4 步：可选标点恢复

如果你设置了 `PuncModel`，脚本会尝试：

1. 用标点模型生成更自然的文本
2. 把新增标点重新合并到字符时间线里

这一步的技术难点在于：

- 标点本来不一定存在于原始识别结果里
- 但切句逻辑又很依赖标点

所以脚本会把“补出来的标点”挂到附近字符的时间位置上，尽量让分句更自然。

### 第 5 步：按句切分

脚本用的是一个“贪心分句策略”，优先级大致是：

1. 强边界：`。！？?!`
2. 软边界：`，,；;`
3. 停顿边界：相邻字符时间间隔大于阈值
4. 如果以上都不满足，再按最大时长强制切

这意味着它不是“完全按标点切”，也不是“完全按停顿切”，而是两者结合。

### 第 6 步：导出结果

最后脚本会：

1. 用原始输入音频导出每一句对应的 `.wav`
2. 为每一句写一个同名 `.txt`
3. 把所有片段写入 `index.jsonl`
4. 把全文写入 `full_text.txt`
5. 把本次运行配置写入 `meta.json`

---

## 9. 输出结果怎么读

假设某次输出目录是：

```text
.\outputs\run_20260314_193000
```

那么常见文件含义如下。

### 9.1 `_tmp\input_16k_mono.wav`

这是中间文件。

用途：

- 给 ASR 模型使用的标准化音频
- 通常不需要你手动处理

### 9.2 `segments\*.wav`

这是分句后的音频片段。

每个文件代表一句话或一个切分片段。

文件名现在固定带有 `seg_0001` 这种序号前缀。  
这个序号是片段的稳定主键，也等于音频里的时间顺序。

为什么不直接把整句文字当文件名：

- Windows 资源管理器按“名称”排序时，纯中文句子会按文本顺序排，不是按音频时间排
- 长文件名会被资源管理器截断，看起来很像“文件名和内容对不上”
- 序号前缀能保证 `.wav`、`.txt`、`index.jsonl` 三处更容易互相核对

### 9.3 `segments\*.txt`

这是对应音频片段的文本内容。

通常：

- 一个 `.wav`
- 对应一个 `.txt`

### 9.4 `full_text.txt`

这是整段音频的全文识别结果。

适合：

- 快速浏览整体文本
- 复制出来做人工校对

### 9.5 `meta.json`

这是本次运行的元信息。

里面通常会记录：

- 输入音频路径
- 模型路径
- 语言设置
- 标点模型
- 分句阈值
- 导出的片段数量

它的价值在于“可追溯”。  
以后你回头看结果时，可以知道当时到底用了什么参数。

### 9.6 `index.jsonl`

这是最重要的结构化结果文件之一。

每一行大致长这样：

```json
{"id":"seg_0001","wav":"segments/seg_0001__大家好，欢迎来到这里.wav","txt":"segments/seg_0001__大家好，欢迎来到这里.txt","start":0.52,"end":2.14,"text":"大家好，欢迎来到这里。"}
```

字段解释：

- `id`：片段编号
- `wav`：片段音频相对路径
- `txt`：片段文本相对路径
- `start`：该片段在原始音频中的开始时间，单位秒
- `end`：该片段在原始音频中的结束时间，单位秒
- `text`：片段文本内容

如果你后续想：

- 做数据集整理
- 导入数据库
- 写脚本继续处理

这个文件会非常有用。

### 9.7 `qwen3_tts.jsonl`（可选）

当你把 `DatasetFormat` 设为 `qwen3_tts` 时，结果目录里还会额外生成一份更适合 Qwen3 TTS 自动收集微调数据的清单：

```json
{"audio":"data/audio/utt0001.wav","text":"她说中午前会到。","ref_audio":"data/ref/ref.wav","language":"Auto"}
```

它的特点是：

- `audio`：指向标准化后的片段音频路径
- `text`：片段文本
- `ref_audio`：你传入的参考音频，会被复制到结果目录下的 `data/ref`
- `language`：当 `Language=None` 时会写成 `Auto`，否则沿用你指定的语言值

如果输入是一个目录，根输出目录下还会额外汇总一份 `qwen3_tts.jsonl`，方便你批量收集数据。

---

## 10. 常用命令速查

### 10.1 仅查看帮助

```powershell
.\run.ps1 -Help
```

### 10.2 查看当前生效配置

```powershell
.\run.ps1 -ShowConfig
```

这个命令很适合排错，因为它能直接告诉你：

- 当前 `Audio` 到底指向哪里
- 当前 `OutDir` 到底写到哪里
- 当前模型路径是否正确

### 10.3 处理单个音频文件

```powershell
.\run.ps1 `
  -Audio ".\inputs\demo.wav" `
  -OutDir "" `
  -AsrCkpt ".\models\Qwen3-ASR-1.7B" `
  -AlignerCkpt ".\models\Qwen3-ForcedAligner-0.6B"
```

### 10.4 批量处理整个输入目录

```powershell
.\run.ps1 `
  -Audio ".\inputs" `
  -OutDir "" `
  -AsrCkpt ".\models\Qwen3-ASR-1.7B" `
  -AlignerCkpt ".\models\Qwen3-ForcedAligner-0.6B"
```

### 10.5 递归处理所有子目录

```powershell
.\run.ps1 `
  -Audio ".\inputs" `
  -OutDir "" `
  -AsrCkpt ".\models\Qwen3-ASR-1.7B" `
  -AlignerCkpt ".\models\Qwen3-ForcedAligner-0.6B" `
  -ScanSubfolders
```

### 10.6 启用或修复标点恢复

当前默认已经启用标点恢复。如果旧环境提示缺少 `funasr`，先运行：

```powershell
.\bootstrap.ps1 -InstallFunASR
```

然后运行时保持 `PuncModel` 不为空，例如：

```powershell
.\run.ps1 `
  -Audio ".\inputs" `
  -OutDir "" `
  -AsrCkpt ".\models\Qwen3-ASR-1.7B" `
  -AlignerCkpt ".\models\Qwen3-ForcedAligner-0.6B" `
  -PuncModel "iic/punc_ct-transformer_cn-en-common-vocab471067-large"
```

### 10.7 导出 Qwen3-TTS 微调清单

```powershell
.\run.ps1 `
  -Audio ".\inputs" `
  -OutDir "" `
  -DatasetFormat "qwen3_tts" `
  -RefAudio ".\inputs\ref.wav" `
  -AsrCkpt ".\models\Qwen3-ASR-1.7B" `
  -AlignerCkpt ".\models\Qwen3-ForcedAligner-0.6B" `
  -Language "None"
```

---

## 11. 什么时候该调哪些参数

### 场景 1：切得太碎

现象：

- 一句话被切成很多很短的小段

优先尝试：

- 增大 `PauseThreshold`
- 增大 `MinDur`

例如：

```powershell
.\run.ps1 `
  -Audio ".\inputs" `
  -OutDir "" `
  -AsrCkpt ".\models\Qwen3-ASR-1.7B" `
  -AlignerCkpt ".\models\Qwen3-ForcedAligner-0.6B" `
  -PauseThreshold 0.80 `
  -MinDur 1.20
```

### 场景 2：切得太长

现象：

- 好几句话粘在一起，没有切开

优先尝试：

- 减小 `PauseThreshold`
- 减小 `MaxDur`

### 场景 3：句首或句尾经常被切掉一点

优先尝试：

- 略微增大 `PadLeft`
- 略微增大 `PadRight`

例如：

```powershell
-PadLeft 0.08 -PadRight 0.15
```

### 场景 4：中文为主，但识别结果不够自然

优先尝试：

- 把 `Language` 明确设成 `Chinese`
- 开启 `PuncModel`

---

## 12. 常见问题与排错

### 12.1 找不到虚拟环境

现象：运行 `run_cli.bat`、`run.ps1` 或 `start_webui.ps1` 时，提示找不到 `.venv`、`python.exe`，或者环境未就绪。

最常见原因：你还没运行过 `bootstrap.bat`，或者上次安装中断了。

你现在该怎么做：先运行 `bootstrap.bat`；如果还是失败，回到前面的安装前提，先确认 Python 正常（ffmpeg 项目会自动安装，不需要手动处理）。

### 12.2 输入路径不存在

现象：脚本说找不到输入音频、找不到目录，或者直接跳过了任务。

最常见原因：`Audio` 写错了，或者还在用旧的绝对路径。

你现在该怎么做：先运行 `.\run_cli.bat -ShowConfig` 看 `Audio` / `OutDir`，然后把音频放进 `.\inputs` 这类相对路径里。

### 12.3 `ffmpeg` / `ffprobe` not found

现象：自检或处理时提示 `ffmpeg` / `ffprobe` 找不到。

最常见原因：自动下载 ffmpeg 时网络中断，或下载完但解压不完整。

你现在该怎么做：
- 检查 `.tools\ffmpeg\bin` 目录里有没有 `ffmpeg.exe` 和 `ffprobe.exe`
- 如果没有，重新运行 `.\bootstrap.bat` 或 `.\start_webui.ps1`，项目会自动重试下载
- 也可以手动从 https://www.gyan.dev/ffmpeg/builds/ 下载 `ffmpeg-release-essentials.zip`，解压后将整个解压目录的内容放入 `.tools\ffmpeg`（确保 `.tools\ffmpeg\bin\ffmpeg.exe` 存在即可）
- 如果系统 PATH 里已经有 ffmpeg，项目会优先使用系统版本，不需要额外操作

### 12.4 模型加载失败

现象：启动时提示模型找不到、加载失败，或者路径不对。

最常见原因：`AsrCkpt` / `AlignerCkpt` 指到了错误位置，或者本地模型目录不存在。

你现在该怎么做：确认 `.\models\Qwen3-ASR-1.7B` 和 `.\models\Qwen3-ForcedAligner-0.6B` 还在；如果没有本地模型，先运行 `.\bootstrap.ps1 -DownloadModels`，或者在 WebUI 里点“下载模型”。

### 12.5 默认标点恢复提示缺少 `funasr`

如果你用 WebUI，也可以直接点“补装 FunASR”来补依赖。

现象：提交任务后提示缺少 `funasr`，或者日志里出现“标点恢复依赖”相关错误。

最常见原因：这是旧环境，之前初始化时还没有把 `funasr` 装进去。

你现在该怎么做：先运行 `.\bootstrap.ps1 -InstallFunASR`；如果你暂时不需要标点恢复，把 `PuncModel` 留空。

WebUI 里也有“补装 FunASR”按钮。

### 12.6 没有 GPU 能不能跑

现象：你只有 CPU，没有 CUDA。

最常见原因：这不是报错，是机器配置不同。

你现在该怎么做：可以跑，只是会慢一些；脚本会自动回退到 CPU。

### 12.7 输出目录很乱怎么办

现象：`outputs` 里堆了很多批次，分不清哪次是哪次。

最常见原因：你给了固定 `OutDir`，或者手工复用了同一个目录。

你现在该怎么做：默认用 `-OutDir ""`，让脚本自动生成时间戳目录；WebUI 自动模式也会写到 `.\outputs\webui_runs`。

### 12.8 直接运行 `.ps1` 被执行策略拦住

如果你直接双击或直接调用 `bootstrap.ps1`、`run.ps1`、`start_webui.ps1`，PowerShell 可能会在脚本启动前拦截执行。

日常推荐直接用这些低门槛入口：

- `bootstrap.bat`
- `run_cli.bat`
- `run_webui.bat`

只有你坚持直接运行 `.ps1`，才在当前窗口临时执行：

```powershell
Set-ExecutionPolicy -Scope Process Bypass
```

这只对当前 PowerShell 窗口生效，关闭窗口后就失效了。

---

## 13. 当前项目已经确认过的状态

为了避免你怀疑“教程是不是空写的”，这里把我已经核对过的实际情况列出来：

- 项目根目录就是当前仓库
- 本地模型目录已经存在
- `.\models\Qwen3-ASR-1.7B`
- `.\models\Qwen3-ForcedAligner-0.6B`
- 项目虚拟环境已经存在
  - `.venv\Scripts\python.exe`
- `bootstrap.ps1` 自检已通过
  - Python 正常
  - 虚拟环境正常
  - `ffmpeg` 正常
  - `torch` 正常
  - CUDA GPU 可用
  - `qwen_asr` 正常
  - `modelscope` 正常

当前唯一最需要你注意的使用问题，不是环境，而是：

- 路径示例已经统一改成相对路径
- 第一次运行时，优先按本文给出的命令覆盖参数即可

---

## 14. 给新手的最短版本操作清单

如果你只想复制最短步骤，直接按下面做；如果你更想用 WebUI，回到第 2 节即可。

```powershell
Set-Location "<项目根目录>"
.\bootstrap.bat
```

如果你的项目不在这个位置，把 `<项目根目录>` 换成你自己的项目目录；或者直接在项目根目录双击 `bootstrap.bat`。

把音频放进 `.\inputs` 之后，再执行：

```powershell
.\run_cli.bat `
  -Audio ".\inputs" `
  -OutDir "" `
  -AsrCkpt ".\models\Qwen3-ASR-1.7B" `
  -AlignerCkpt ".\models\Qwen3-ForcedAligner-0.6B" `
  -Language "None"
```

处理完成后，去 `.\outputs\run_时间戳` 目录里看：

- `segments`
- `full_text.txt`
- `index.jsonl`
- `meta.json`

如果你愿意，我下一步可以继续直接帮你做两件事中的任意一件：

1. 把 [run.ps1](./run.ps1) 的配置块改成更适合你当前环境的默认值  
2. 再给你补一份“每个输出文件怎么继续拿来做数据集”的进阶教程

---

## 15. WebUI 图形控制台

现在项目里已经额外提供了一个本地 Web 控制台，入口脚本是：

- [run_webui.bat](./run_webui.bat)
- [start_webui.ps1](./start_webui.ps1)

这个 WebUI 适合下面这类使用方式：

- 你不想反复手写 PowerShell 命令
- 你想把参数配置、任务历史、实时日志、结果浏览放在一个界面里
- 你希望长期把它当作本地处理工作台，而不是临时脚本面板

### 15.1 启动方法

先进入项目目录：

```powershell
Set-Location "<项目根目录>"
```

如果你的项目不在这个位置，把路径改成你自己的项目根目录。

如果你还没初始化环境，先执行：

```powershell
.\bootstrap.bat
```

然后启动 WebUI：

```bat
.\run_webui.bat
```

或者：

```powershell
.\start_webui.ps1
```

默认会在浏览器里打开：

```text
http://127.0.0.1:8765
```

### 15.2 可选参数

如果你不想自动打开浏览器：

```bat
.\run_webui.bat -NoBrowser
```

或者：

```powershell
.\start_webui.ps1 -NoBrowser
```

如果默认端口被占用，可以换一个端口：

```bat
.\run_webui.bat -Port 8766
```

或者：

```powershell
.\start_webui.ps1 -Port 8766
```

### 15.3 这个 WebUI 能做什么

当前版本已经支持：

- 图形化填写 `run.ps1` 相关配置
- 配置文件保存、加载、重命名、删除，以及设置默认启动配置
- 保存默认配置
- 创建任务并进入任务历史
- 实时查看任务状态和日志
- 浏览结果库
- 一键导出 Qwen3-TTS 数据集目录
- 打开项目目录、结果目录
- 执行环境维护动作，例如基础环境初始化和标点依赖安装

对新手更重要的是：

- 首屏会先显示环境检查和下一步建议
- 可以一键打开输入目录，把音频放进去再提交任务
- 如果模型没准备好，可以直接点“下载模型”
- 如果提示缺少标点恢复依赖，可以直接点“补装 FunASR”
- 失败任务会尽量显示能直接照着做的修复建议，而不是只给退出码

### 15.4 结果库默认位置

为了避免把旧的零散输出和新任务混在一起，WebUI 自动模式下会把结果写入：

```text
.\outputs\webui_runs
```

这样做的好处是：

- 任务历史和结果目录更容易对应
- 不会污染你原来已经堆满散文件的 `outputs`
- 更适合后续继续做结果回看和参数对比
