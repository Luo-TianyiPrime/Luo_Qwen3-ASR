<#
.SYNOPSIS
Qwen3-ASR 本地一键运行脚本（单文件配置版，支持单文件/整目录批处理）。

.DESCRIPTION
你只需要修改本文件中的 `$Config` 配置块，然后执行 `./run.ps1` 即可。
脚本会自动完成：读取配置、校验环境、执行 ASR + 对齐 + 分句。

.EXAMPLE
./run.ps1

.EXAMPLE
./run.ps1 -ShowConfig

.EXAMPLE
./run.ps1 -Audio ./inputs/test.wav

.EXAMPLE
./run.ps1 -Help
#>

param(
    [string]$Audio,
    [string]$OutDir,
    [string]$DatasetFormat,
    [string]$RefAudio,
    [string]$HotwordFile,
    [string]$HotwordLibrary,
    [string]$AsrCkpt,
    [string]$AlignerCkpt,
    [string]$Language,
    [string]$PuncModel,
    [double]$PauseThreshold,
    [double]$MinDur,
    [double]$MaxDur,
    [double]$PadLeft,
    [double]$PadRight,
    [int]$BatchSize,
    [int]$MaxNewTokens,
    [double]$EtaRTF,
    [switch]$ScanSubfolders,
    [switch]$ShowConfig,
    [switch]$Help
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# 项目根目录与主脚本路径
$ProjectRoot = $PSScriptRoot
$ScriptPath = Join-Path $ProjectRoot "scripts\asr_sentence_segment.py"
$PythonExe = Join-Path $ProjectRoot ".venv\Scripts\python.exe"

# 加载项目环境变量（缓存目录等）
if (Test-Path (Join-Path $ProjectRoot "env.ps1")) {
    . (Join-Path $ProjectRoot "env.ps1")
}

function Show-Usage {
    @"
==================== Qwen3-ASR 使用方法 ====================

一、推荐流程
1) 先把音频放进 `.\inputs`，或者命令行临时指定 `-Audio`
2) 第一次建议先保留默认值，直接执行：./run.ps1
3) 结果输出到 outputs/run_时间戳 目录

二、Audio 支持两种输入
        - 单文件：例如 .\inputs\demo.wav
        - 文件夹：例如 .\inputs
          脚本会自动批量处理该目录下所有音频（可选递归子目录）  

三、你通常只需要改这几项
- Audio: 输入音频路径（文件或文件夹）；第一次运行直接用默认的 `.\inputs` 最省事
- AsrCkpt: ASR 模型目录（建议先用 bootstrap 下载好的本地目录）
- AlignerCkpt: 对齐模型目录（建议先用 bootstrap 下载好的本地目录）
- Language: 识别语言（如 Chinese / None）
- DatasetFormat: 结果清单格式（standard / qwen3_tts）
- RefAudio: 可选。只有导出 Qwen3-TTS 清单时才需要
- HotwordLibrary / HotwordFile: 可选。`HotwordFile` 会优先于 `HotwordLibrary`；临时热词只影响当前任务
        - BatchSize: ASR 内部批大小。不懂就保持 1；如果爆显存，脚本会先自动降到 1，再不行会尝试 CPU 回退
- PauseThreshold / MinDur / MaxDur: 分句参数
- EtaRTF: 只影响预计剩余时间的显示，不影响结果

四、常用命令
- 查看生效配置：./run.ps1 -ShowConfig
- 临时覆盖音频：./run.ps1 -Audio ./inputs/demo.wav
        - 批量处理并递归子目录：./run.ps1 -Audio .\inputs -ScanSubfolders
- 指定输出目录：./run.ps1 -OutDir ./outputs/my_run
- 导出可直接整理成 Qwen3-TTS 微调数据的清单：./run.ps1 -DatasetFormat qwen3_tts
- 导出带参考音频字段的 Qwen3-TTS 清单：./run.ps1 -DatasetFormat qwen3_tts -RefAudio ./data/ref/ref.wav
- 使用 RAG 热词库参与识别：./run.ps1 -HotwordLibrary luo_hotwords.txt
- 提高 ASR 并行批大小：./run.ps1 -BatchSize 4
- 查看帮助：./run.ps1 -Help

五、常见报错
- 未找到虚拟环境：先执行 `./bootstrap.ps1`，完成后再重新运行 `./run.ps1`
- 未找到主脚本：确认当前目录就是项目根目录，或者重新解压完整项目
- 输入路径为空或不存在：先确认 `Audio`，默认值建议直接保留 `.\inputs`
- 输入目录为空：把音频文件放进 `.\inputs`，或者把 `Audio` 改成正确的音频目录
- 参考音频不存在：只有导出 Qwen3-TTS 时才需要填写 `RefAudio`
- 未找到 ffmpeg：先安装 ffmpeg，并确认命令行能直接运行 `ffmpeg -version`
- 模型目录不存在：先运行 `./bootstrap.ps1 -DownloadModels`，或者把模型路径改成真实存在的本地目录
- 标点恢复失败：默认会填写 `PuncModel`；如果提示缺少 funasr，先运行 `./bootstrap.ps1 -InstallFunASR`
- 批大小非法：先保持 `BatchSize = 1`

===========================================================
"@ | Write-Host
}

function Resolve-ProjectPath {
    param([string]$PathValue)

    if ([string]::IsNullOrWhiteSpace($PathValue)) {
        return $PathValue
    }

    if ([System.IO.Path]::IsPathRooted($PathValue)) {
        return $PathValue
    }

    return (Join-Path $ProjectRoot $PathValue)
}

function Resolve-CkptValue {
    param([string]$Value)

    if ([string]::IsNullOrWhiteSpace($Value)) {
        return $Value
    }

    if ([System.IO.Path]::IsPathRooted($Value)) {
        return $Value
    }

    if (
        $Value.StartsWith(".\\") -or
        $Value.StartsWith("./") -or
        $Value.Contains("\\") -or
        $Value.Contains("/")
    ) {
        return (Join-Path $ProjectRoot $Value)
    }

    $candidate = Join-Path $ProjectRoot $Value
    if (Test-Path $candidate) {
        return $candidate
    }

    return $Value
}

function Get-SafeName {
    param([string]$Name)
    return ([regex]::Replace($Name, '[\\/:*?""<>|]', '_'))
}

function Format-Duration {
    param([double]$Seconds)

    $s = [math]::Max(0, [int][math]::Round($Seconds))
    $h = [math]::Floor($s / 3600)
    $m = [math]::Floor(($s % 3600) / 60)
    $sec = $s % 60

    if ($h -gt 0) { return ("{0}h{1:D2}m{2:D2}s" -f $h, $m, $sec) }
    if ($m -gt 0) { return ("{0}m{1:D2}s" -f $m, $sec) }
    return ("{0}s" -f $sec)
}

function Normalize-DatasetFormat {
    param([string]$Value)

    if ([string]::IsNullOrWhiteSpace($Value)) {
        return "standard"
    }

    $normalized = $Value.Trim().ToLowerInvariant()
    switch ($normalized) {
        "standard" { return "standard" }
        "qwen3_tts" { return "qwen3_tts" }
        default {
            throw "DatasetFormat 仅支持 standard 或 qwen3_tts，当前为：$Value"
        }
    }
}

function Get-Utf8NoBomEncoding {
    return (New-Object System.Text.UTF8Encoding $false)
}

function New-ActionableError {
    param(
        [string]$Problem,
        [string]$Cause,
        [string]$NextStep
    )

    return @(
        $Problem
        "常见原因：$Cause"
        "下一步：$NextStep"
    ) -join [Environment]::NewLine
}

function Append-Qwen3TtsManifest {
    param(
        [string]$RunDir,
        [string]$RootOutDir,
        [string]$Prefix
    )

    $runManifest = Join-Path $RunDir "qwen3_tts.jsonl"
    if (-not (Test-Path $runManifest -PathType Leaf)) {
        return
    }

    $rootManifest = Join-Path $RootOutDir "qwen3_tts.jsonl"
    $prefixPart = ($Prefix -replace "\\", "/").Trim("/")

    foreach ($line in (Get-Content -LiteralPath $runManifest -Encoding UTF8)) {
        if ([string]::IsNullOrWhiteSpace($line)) {
            continue
        }

        $payload = $line | ConvertFrom-Json
        if (-not [string]::IsNullOrWhiteSpace($prefixPart)) {
            $audioVal = if ($payload.PSObject.Properties["audio"]) { $payload.audio } else { "" }
            if (-not [string]::IsNullOrWhiteSpace($audioVal)) {
                $payload.audio = "$prefixPart/$audioVal"
            }
            $refAudioVal = if ($payload.PSObject.Properties["ref_audio"]) { $payload.ref_audio } else { "" }
            if (-not [string]::IsNullOrWhiteSpace($refAudioVal)) {
                $payload.ref_audio = "$prefixPart/$refAudioVal"
            }
        }

        [System.IO.File]::AppendAllText(
            $rootManifest,
            (($payload | ConvertTo-Json -Compress) + [Environment]::NewLine),
            (Get-Utf8NoBomEncoding)
        )
    }
}

function Invoke-OneAudio {
    param(
        [string]$AudioPath,
        [string]$OutputPath,
        [hashtable]$Cfg
    )

    New-Item -ItemType Directory -Force -Path $OutputPath | Out-Null

    $args = @(
        "--audio", $AudioPath,
        "--out_dir", $OutputPath,
        "--dataset_format", $Cfg.DatasetFormat,
        "--asr_ckpt", $Cfg.AsrCkpt,
        "--aligner_ckpt", $Cfg.AlignerCkpt,
        "--language", $Cfg.Language,
        "--pause_threshold", "$($Cfg.PauseThreshold)",
        "--min_dur", "$($Cfg.MinDur)",
        "--max_dur", "$($Cfg.MaxDur)",
        "--pad_left", "$($Cfg.PadLeft)",
        "--pad_right", "$($Cfg.PadRight)",
        "--batch_size", "$($Cfg.BatchSize)",
        "--max_new_tokens", "$($Cfg.MaxNewTokens)",
        "--eta_rtf", "$($Cfg.EtaRTF)"
    )

    if (-not [string]::IsNullOrWhiteSpace($Cfg.PuncModel)) {
        $args += @("--punc_model", $Cfg.PuncModel)
    }

    if (-not [string]::IsNullOrWhiteSpace($Cfg.RefAudio)) {
        $args += @("--ref_audio", $Cfg.RefAudio)
    }

    if (-not [string]::IsNullOrWhiteSpace($Cfg.HotwordFile)) {
        $args += @("--hotword_file", $Cfg.HotwordFile)
    }

    & $PythonExe $ScriptPath @args
    $code = $LASTEXITCODE
    if ($code -ne 0) {
        throw "处理失败（exit code=$code）：$AudioPath"
    }
}

function Get-SharedSplitDefaults {
    # 这 5 个字段是“分句核心参数”，默认值集中在 configs/defaults.json。
    # 这样做的目的：run.ps1、WebUI、asr_sentence_segment.py 三处始终一致，
    # 避免“脚本默认值改了、WebUI 还停留在旧值”的隐性问题。
    $fallback = [ordered]@{
        PauseThreshold = 0.60
        MinDur = 0.80
        MaxDur = 8.00
        PadLeft = 0.05
        PadRight = 0.10
    }

    $path = Join-Path $ProjectRoot "configs\\defaults.json"
    if (-not (Test-Path $path -PathType Leaf)) {
        return $fallback
    }

    try {
        $raw = Get-Content -LiteralPath $path -Raw -Encoding UTF8 | ConvertFrom-Json
        if ($null -ne $raw.pause_threshold) { $fallback.PauseThreshold = [double]$raw.pause_threshold }
        if ($null -ne $raw.min_dur) { $fallback.MinDur = [double]$raw.min_dur }
        if ($null -ne $raw.max_dur) { $fallback.MaxDur = [double]$raw.max_dur }
        if ($null -ne $raw.pad_left) { $fallback.PadLeft = [double]$raw.pad_left }
        if ($null -ne $raw.pad_right) { $fallback.PadRight = [double]$raw.pad_right }
    }
    catch {
        Write-Warning "读取 configs/defaults.json 失败，改用内置默认分句参数。错误：$($_.Exception.Message)"
    }

    return $fallback
}

if ($Help) {
    Show-Usage
    exit 0
}

$SplitDefaults = Get-SharedSplitDefaults

# ------------------ CONFIG START ------------------
# 你主要修改这个配置块即可控制全流程。
# 相对路径均基于本脚本所在目录（$ProjectRoot）。
$Config = [ordered]@{
    # 输入音频路径：支持单文件或文件夹
    Audio = ".\inputs"

    # 输出目录：
    # - 留空：自动创建 outputs\run_YYYYMMDD_HHMMSS
    # - 填路径：输出到指定目录
    OutDir = ""

    # 结果清单格式：
    # - standard  = 保持原有 index.jsonl 输出
    # - qwen3_tts = 额外导出可直接给 Qwen3-TTS 微调使用的 qwen3_tts.jsonl
    #               这只是“多导出一种数据集格式”，不会改变 ASR 本身的识别流程
    DatasetFormat = "standard"

    # Qwen3-TTS 导出时可选的参考音频（可相对项目根目录）：
    # - 留空：仍然导出 qwen3_tts.jsonl，但不写 ref_audio 字段，也不会生成 data\ref
    # - 填写：会把该音频复制到结果目录的 data\ref，并在每条记录里写入 ref_audio
    # 这个字段不参与 ASR 识别本身，只是给后续 TTS 数据集保留“参考音色锚点”
    RefAudio = ""

    # 热词文件路径（每行一个词，注入识别上下文）
    # 如果你已经在 configs\hotwords 里维护好了热词库，通常更推荐下面的 HotwordLibrary
    HotwordFile = ""

    # 热词库文件名（位于 configs\hotwords\ 下）
    # 例如：luo_hotwords.txt
    # 填这个以后，脚本会自动找到对应文件并作为 ASR 上下文注入
    HotwordLibrary = ""

    # 模型：建议使用本地目录；如果还没下载，先运行 bootstrap.ps1 -DownloadModels
    AsrCkpt = ".\models\Qwen3-ASR-1.7B"
    AlignerCkpt = ".\models\Qwen3-ForcedAligner-0.6B"

    # 识别语言：Chinese / None（自动识别）
    Language = "None"

    # 标点恢复模型（可选）：
    # - 当前默认启用 FunASR 的中文/中英通用标点模型，用来给 ASR 原始识别文本补上逗号、句号、问号等标点
    # - 这个模型不会重新“听”音频，它只读取 ASR 已经识别出来的文字，再根据上下文判断哪里应该加标点
    # - 标点恢复对后续“按句切分”很重要：没有标点时，脚本只能更多依赖停顿时间；有标点后，句子边界通常更自然
    # - 如果你只想要完全原始、无标点的识别文本，可以把这里改回空字符串：PuncModel = ""
    # - 启用此项需要 Python 环境里安装 funasr；本项目 requirements.txt 已包含 funasr，旧环境可运行 .\bootstrap.ps1 -InstallFunASR 补装
    PuncModel = "iic/punc_ct-transformer_cn-en-common-vocab471067-large"

    # ASR 批大小（batch_size）：
    # - 1 = 最稳妥，显存占用最低，也是当前项目原本的默认行为
    # - 更大通常会更快，但显存占用也会更高，而且不一定线性提速
    # - 如果出现 CUDA out of memory / 显存不足，第一步通常就是把它调小
    # - 以 12GB 显存为例，常见可以从 2 或 4 试起；如果你不确定，就先用 1
    BatchSize = 1

    # ASR 最大生成 token 数（max_new_tokens）：
    # - 控制每次 ASR 推理的最大输出长度，值越大 KV 缓存占用显存越多
    # - 正常语音识别输出通常在 2000 tokens 以内
    # - 如果显存不足，优先降低这个值（如 1024 或 2048）
    MaxNewTokens = 2048

    # 分句参数（单位：秒）
    PauseThreshold = $SplitDefaults.PauseThreshold
    MinDur = $SplitDefaults.MinDur
    MaxDur = $SplitDefaults.MaxDur

    # 音频切片左右补偿（单位：秒）
    PadLeft = $SplitDefaults.PadLeft
    PadRight = $SplitDefaults.PadRight

    # 第 3 步 ETA 估算速度（x 实时）。例如：
    # 2.0 = 估算每 1 秒音频需 0.5 秒计算
    # 3.0 = 估算每 1 秒音频需 0.33 秒计算
    EtaRTF = 2.0

    # 当 Audio 是文件夹时：
    # false = 仅扫描当前目录
    # true  = 递归扫描全部子目录
    ScanSubfolders = $false

    # 支持的音频后缀（小写）
    AudioExtensions = @(
        ".wav", ".mp3", ".m4a", ".flac", ".aac",
        ".ogg", ".opus", ".wma", ".webm", ".mp4", ".mkv", ".mov"
    )
}
# ------------------- CONFIG END -------------------

# ------------------ 命令行覆盖 ------------------
if ($PSBoundParameters.ContainsKey("Audio")) { $Config.Audio = $Audio }
if ($PSBoundParameters.ContainsKey("OutDir")) { $Config.OutDir = $OutDir }
if ($PSBoundParameters.ContainsKey("DatasetFormat")) { $Config.DatasetFormat = $DatasetFormat }
if ($PSBoundParameters.ContainsKey("RefAudio")) { $Config.RefAudio = $RefAudio }
if ($PSBoundParameters.ContainsKey("HotwordFile")) { $Config.HotwordFile = $HotwordFile }
if ($PSBoundParameters.ContainsKey("HotwordLibrary")) { $Config.HotwordLibrary = $HotwordLibrary }
if ($PSBoundParameters.ContainsKey("AsrCkpt")) { $Config.AsrCkpt = $AsrCkpt }
if ($PSBoundParameters.ContainsKey("AlignerCkpt")) { $Config.AlignerCkpt = $AlignerCkpt }
if ($PSBoundParameters.ContainsKey("Language")) { $Config.Language = $Language }
if ($PSBoundParameters.ContainsKey("PuncModel")) { $Config.PuncModel = $PuncModel }
if ($PSBoundParameters.ContainsKey("BatchSize")) { $Config.BatchSize = $BatchSize }
if ($PSBoundParameters.ContainsKey("MaxNewTokens")) { $Config.MaxNewTokens = $MaxNewTokens }
if ($PSBoundParameters.ContainsKey("PauseThreshold")) { $Config.PauseThreshold = $PauseThreshold }
if ($PSBoundParameters.ContainsKey("MinDur")) { $Config.MinDur = $MinDur }
if ($PSBoundParameters.ContainsKey("MaxDur")) { $Config.MaxDur = $MaxDur }
if ($PSBoundParameters.ContainsKey("PadLeft")) { $Config.PadLeft = $PadLeft }
if ($PSBoundParameters.ContainsKey("PadRight")) { $Config.PadRight = $PadRight }
if ($PSBoundParameters.ContainsKey("EtaRTF")) { $Config.EtaRTF = $EtaRTF }
if ($PSBoundParameters.ContainsKey("ScanSubfolders")) { $Config.ScanSubfolders = $true }

# ------------------ 路径归一化 ------------------
$Config.Audio = Resolve-ProjectPath -PathValue $Config.Audio
$Config.OutDir = Resolve-ProjectPath -PathValue $Config.OutDir
$Config.DatasetFormat = Normalize-DatasetFormat -Value $Config.DatasetFormat
$Config.RefAudio = Resolve-ProjectPath -PathValue $Config.RefAudio
if (-not [string]::IsNullOrWhiteSpace($Config.HotwordFile)) {
    $Config.HotwordFile = Resolve-ProjectPath -PathValue $Config.HotwordFile
}
if (-not [string]::IsNullOrWhiteSpace($Config.HotwordLibrary)) {
    $hwLibPath = Join-Path $ProjectRoot ("configs\hotwords\" + $Config.HotwordLibrary)
    if (Test-Path $hwLibPath -PathType Leaf) {
        if ([string]::IsNullOrWhiteSpace($Config.HotwordFile)) {
            $Config.HotwordFile = $hwLibPath
        }
        else {
            Write-Host "[run] 已填写 HotwordFile，优先使用临时热词；HotwordLibrary 不会覆盖当前任务。"
        }
    } else {
        Write-Warning "热词库文件不存在：$hwLibPath。该热词库本次会被忽略；你可以把文件放进 configs\hotwords，或者直接填写 HotwordFile。"
    }
}
$Config.AsrCkpt = Resolve-CkptValue -Value $Config.AsrCkpt
$Config.AlignerCkpt = Resolve-CkptValue -Value $Config.AlignerCkpt

if ($ShowConfig) {
    Write-Host "[run] 当前生效配置："
    foreach ($item in $Config.GetEnumerator()) {
        $v = $item.Value
        if ($v -is [System.Array]) {
            $v = ($v -join ", ")
        }
        Write-Host ("  {0} = {1}" -f $item.Key, $v)
    }
    exit 0
}

# ------------------ 前置校验 ------------------
if (-not (Test-Path -LiteralPath $PythonExe)) {
    throw (New-ActionableError -Problem "未找到虚拟环境。" -Cause "通常是还没有执行初始化，或者 `.venv` 被误删了。" -NextStep "先运行 `./bootstrap.ps1`，完成后再重新执行 `./run.ps1`。")
}

if (-not (Test-Path -LiteralPath $ScriptPath)) {
    throw (New-ActionableError -Problem "未找到主脚本。" -Cause "通常是项目文件不完整，或者当前目录不是 Qwen3-ASR 根目录。" -NextStep "请确认当前就在项目根目录，必要时重新解压完整项目后再试。")
}

# 检查 ffmpeg / ffprobe。
# env.ps1 在脚本启动阶段已加载，所以如果 .tools\ffmpeg\bin 里有 ffmpeg.exe，Get-Command 就能找到。
# 如果 PATH 中找不到，就会尝试调用 bootstrap.ps1 自动下载便携版 ffmpeg 到项目内目录。
$ffmpegMissing = -not (Get-Command ffmpeg -ErrorAction SilentlyContinue)
$ffprobeMissing = -not (Get-Command ffprobe -ErrorAction SilentlyContinue)

if ($ffmpegMissing -or $ffprobeMissing) {
    Write-Host "[run] ffmpeg / ffprobe 在当前 PATH 中缺失，准备项目内自动安装。"
    Write-Host "[run] 说明：ffmpeg 负责音频转码和提取时长，是语音识别流程的必需工具。"
    Write-Host "[run] 安装位置：.tools\ffmpeg（约 80 MB），只在当前项目内生效，不会修改你电脑的系统 PATH。"

    $bootstrapScript = Join-Path $ProjectRoot "bootstrap.ps1"
    if (-not (Test-Path -LiteralPath $bootstrapScript -PathType Leaf)) {
        throw (New-ActionableError -Problem "自动安装 ffmpeg 失败：未找到 bootstrap.ps1。" -Cause "项目文件可能不完整，缺少环境初始化脚本。" -NextStep "请重新解压或重新拉取完整项目，确保 bootstrap.ps1 存在。")
    }

    # 以子进程方式调用 bootstrap.ps1，避免错误传播影响当前脚本的控制流。
    # 注意：bootstrap.ps1 内部也设置了 $ErrorActionPreference="Stop" 和 try/catch，
    # 即使下载失败也会优雅退出，所以这里不需要额外的 try/catch。
    Write-Host "[run] 正在调用 bootstrap.ps1 -InstallFfmpegOnly（下载可能需要几十秒到几分钟）..."
    & powershell -NoProfile -ExecutionPolicy Bypass -File $bootstrapScript -InstallFfmpegOnly

    # 重新加载 env.ps1，让当前进程的 PATH 包含刚安装的 .tools\ffmpeg\bin
    if (Test-Path -LiteralPath (Join-Path $ProjectRoot "env.ps1")) {
        . (Join-Path $ProjectRoot "env.ps1")
    }

    # 再次检查
    if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue)) {
        throw (New-ActionableError -Problem "未找到 ffmpeg。自动安装后 PATH 中仍未找到。" -Cause "通常是因为自动下载失败（如网络问题），或 .tools\ffmpeg\bin 目录中的文件不完整。" -NextStep "你可以手动从 https://www.gyan.dev/ffmpeg/builds/ 下载 Windows 版 ffmpeg，解压到 .tools\ffmpeg 目录；或再次运行 .\\run.ps1 自动重试。")
    }

    if (-not (Get-Command ffprobe -ErrorAction SilentlyContinue)) {
        throw (New-ActionableError -Problem "未找到 ffprobe。ffmpeg 已可用但 ffprobe 缺失。" -Cause "ffprobe 通常和 ffmpeg 一起打包，解压不完整可能导致后者缺失。" -NextStep "请检查 .tools\ffmpeg\bin 目录下是否存在 ffprobe.exe，如缺失请重新解压或重新运行 .\\run.ps1。")
    }
}

if ([string]::IsNullOrWhiteSpace($Config.Audio)) {
    throw (New-ActionableError -Problem "Audio 为空。" -Cause "通常是把输入路径留空了，或者命令行覆盖参数没有传值。" -NextStep "直接保留默认的 `.\inputs`，或者填写一个具体的音频文件 / 文件夹路径后再运行。")
}

if (-not (Test-Path -LiteralPath $Config.Audio)) {
    throw (New-ActionableError -Problem "输入路径不存在。" -Cause "最常见原因是盘符写错、相对路径基准不对，或者文件还没放到项目里。" -NextStep "先检查 `Audio` 的路径，再重新运行；新手最稳妥的做法是先把音频放进 `.\inputs`。")
}

if (-not [string]::IsNullOrWhiteSpace($Config.RefAudio)) {
    if (-not (Test-Path -LiteralPath $Config.RefAudio -PathType Leaf)) {
        throw (New-ActionableError -Problem "参考音频不存在或不是文件。" -Cause "最常见原因是路径写错，或者你其实并不需要填写这个字段。" -NextStep "如果你不是在导出 Qwen3-TTS 清单，就把 `RefAudio` 留空；如果需要导出，请改成真实存在的音频文件路径。")
    }
}

if ([int]$Config.BatchSize -lt 1) {
    throw (New-ActionableError -Problem "BatchSize 非法。" -Cause "批大小至少要是 1；填成 0、负数，或者不小心传了空值都会失败。" -NextStep "先保持 `BatchSize = 1`，跑通后再慢慢调大。")
}

if ([int]$Config.MaxNewTokens -lt 1) {
    throw (New-ActionableError -Problem "MaxNewTokens 非法。" -Cause "最大 token 数至少要是 1；填成 0、负数，或者不小心传了空值都会失败。" -NextStep "先保持 `MaxNewTokens = 2048`，如果爆显存可以再降低到 1024。")
}

if (-not (Test-Path -LiteralPath $Config.AsrCkpt)) {
    throw (New-ActionableError -Problem "ASR 模型目录不存在。" -Cause "最常见原因是模型还没下载到本地，或者路径改错了。" -NextStep "先运行 `./bootstrap.ps1 -DownloadModels`，或者把 `AsrCkpt` 改成真实存在的本地模型目录。")
}

if (-not (Test-Path -LiteralPath $Config.AlignerCkpt)) {
    throw (New-ActionableError -Problem "对齐模型目录不存在。" -Cause "通常是对齐模型还没下载，或者路径没有指向项目内的本地目录。" -NextStep "先运行 `./bootstrap.ps1 -DownloadModels`，或者把 `AlignerCkpt` 改成真实存在的本地模型目录。")
}

if (-not [string]::IsNullOrWhiteSpace($Config.PuncModel)) {
    try {
        & $PythonExe -c "import funasr" | Out-Null
        if ($LASTEXITCODE -ne 0) {
            throw "funasr import failed"
        }
    }
    catch {
        throw (New-ActionableError -Problem "你启用了标点恢复，但当前环境缺少 funasr。" -Cause "这不是模型坏了，而是少了标点恢复依赖。" -NextStep "先运行 `./bootstrap.ps1 -InstallFunASR`，安装完成后再重新执行 `./run.ps1`。")
    }
}

# 输出根目录
if ([string]::IsNullOrWhiteSpace($Config.OutDir)) {
    $stamp = Get-Date -Format "yyyyMMdd_HHmmss"
    $Config.OutDir = Join-Path $ProjectRoot "outputs\run_$stamp"
}
New-Item -ItemType Directory -Force -Path $Config.OutDir | Out-Null

# ------------------ 收集待处理音频 ------------------
$audioFiles = @()
$audioInputType = "file"

if (Test-Path $Config.Audio -PathType Leaf) {
    $audioFiles = @(Get-Item -LiteralPath $Config.Audio)
}
elseif (Test-Path $Config.Audio -PathType Container) {
    $audioInputType = "directory"
    if ($Config.ScanSubfolders) {
        $candidates = Get-ChildItem -LiteralPath $Config.Audio -File -Recurse
    }
    else {
        $candidates = Get-ChildItem -LiteralPath $Config.Audio -File
    }

    $extSet = @($Config.AudioExtensions | ForEach-Object { $_.ToLowerInvariant() })
    $audioFiles = @(
        $candidates |
        Where-Object {
            $ext = $_.Extension.ToLowerInvariant()
            $extSet -contains $ext
        } |
        Sort-Object FullName
    )

    if ($audioFiles.Count -eq 0) {
        throw (New-ActionableError -Problem "输入目录里没有找到可处理音频。" -Cause "最常见原因是 `inputs` 里还没有放文件，或者文件后缀不在白名单中。" -NextStep "请把音频放进 `.\inputs`，或把 `Audio` 改成正确的音频目录后再试。当前支持的后缀：$($extSet -join ', ')")
    }
}
else {
    throw (New-ActionableError -Problem "输入路径既不是文件也不是目录。" -Cause "通常是路径写错，或者复制路径时漏了盘符 / 文件名。" -NextStep "请重新检查 `Audio`，确保它指向一个真实存在的文件或文件夹。")
}

if ($audioInputType -eq "directory" -and $Config.DatasetFormat -eq "qwen3_tts") {
    [System.IO.File]::WriteAllText(
        (Join-Path $Config.OutDir "qwen3_tts.jsonl"),
        "",
        (Get-Utf8NoBomEncoding)
    )
}

# ------------------ 执行处理 ------------------
$total = $audioFiles.Count
Write-Host "[run] 输出根目录: $($Config.OutDir)"
Write-Host "[run] 待处理音频数量: $total"
$batchStart = Get-Date
$completed = 0

for ($i = 0; $i -lt $total; $i++) {
    $f = $audioFiles[$i]
    $idx = $i + 1
    $relativePrefix = ""

    if ($audioInputType -eq "file") {
        $oneOutDir = $Config.OutDir
    }
    else {
        $stem = [System.IO.Path]::GetFileNameWithoutExtension($f.Name)
        $safeStem = Get-SafeName -Name $stem
        $sub = ("{0:D4}_{1}" -f $idx, $safeStem)
        $relativePrefix = $sub
        $oneOutDir = Join-Path $Config.OutDir $sub
    }

    Write-Host "[run] [$idx/$total] 开始: $($f.FullName)"
    Write-Host "[run] [$idx/$total] 输出: $oneOutDir"
    if ($completed -gt 0) {
        $elapsedBatch = ((Get-Date) - $batchStart).TotalSeconds
        $avgPerFile = $elapsedBatch / $completed
        $remainFiles = $total - $completed
        $etaSec = $avgPerFile * $remainFiles
        Write-Host "[run] [$idx/$total] 批量剩余 ETA ~ $(Format-Duration $etaSec)"
    }

    $fileStart = Get-Date
    Invoke-OneAudio -AudioPath $f.FullName -OutputPath $oneOutDir -Cfg $Config
    if ($audioInputType -eq "directory" -and $Config.DatasetFormat -eq "qwen3_tts") {
        Append-Qwen3TtsManifest -RunDir $oneOutDir -RootOutDir $Config.OutDir -Prefix $relativePrefix
    }
    $fileElapsed = ((Get-Date) - $fileStart).TotalSeconds
    $completed += 1

    $elapsedBatch = ((Get-Date) - $batchStart).TotalSeconds
    $avgPerFile = $elapsedBatch / $completed
    $remainFiles = $total - $completed
    $etaSec = $avgPerFile * $remainFiles
    Write-Host "[run] [$idx/$total] 完成，用时 $(Format-Duration $fileElapsed)；批量剩余 ETA ~ $(Format-Duration $etaSec)"
}

Write-Host "[run] 全部完成。处理数量: $total"
Write-Host "[run] 结果根目录: $($Config.OutDir)"
if ($Config.DatasetFormat -eq "qwen3_tts") {
    Write-Host "[run] Qwen3-TTS 清单: $(Join-Path $Config.OutDir 'qwen3_tts.jsonl')"
    if ([string]::IsNullOrWhiteSpace($Config.RefAudio)) {
        Write-Host "[run] Qwen3-TTS 清单未写入 ref_audio 字段（因为 RefAudio 留空）。"
    } else {
        Write-Host "[run] Qwen3-TTS 清单已写入参考音频: $($Config.RefAudio)"
    }
}

if (-not [string]::IsNullOrWhiteSpace($Config.PuncModel)) {
    Write-Host "[run] 本次已启用标点恢复。以后如果提示缺少 funasr，请先运行 ./bootstrap.ps1 -InstallFunASR。"
}
