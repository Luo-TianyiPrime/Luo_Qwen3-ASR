<#
.SYNOPSIS
Qwen3-ASR WebUI 总启动脚本。

.DESCRIPTION
这个脚本是 WebUI 的“总管入口”，负责启动前自检、必要依赖修复、可选模型下载、端口处理和最终启动网页服务。

给入门用户的解释：
- run_webui.bat 只是为了方便双击，它会把请求转交给本文件。
- start_webui.ps1 才是真正的启动流程控制脚本。
- bootstrap.ps1 是安装器，start_webui.ps1 发现环境缺失时会自动调用它。
- .venv 是本项目专用 Python 环境，不会污染你的系统 Python。

.EXAMPLE
.\start_webui.ps1

.EXAMPLE
.\start_webui.ps1 -Port 8766

.EXAMPLE
.\start_webui.ps1 -NoBrowser -NoModelDownload

.EXAMPLE
.\start_webui.ps1 -OnlyCheck

.EXAMPLE
.\start_webui.ps1 -SkipFfmpegInstall
#>

param(
    # BindHost 是 WebUI 服务监听地址。
    # 127.0.0.1 表示只允许本机浏览器访问，最安全，适合新手默认使用。
    # 0.0.0.0 表示监听所有网卡，局域网其它电脑也可能访问到；不懂网络安全时不建议改。
    [string]$BindHost = "127.0.0.1",

    # Port 是 WebUI 使用的端口号。
    # 端口可以理解成“同一台电脑上区分不同网络服务的门牌号”。
    # 如果 8765 被占用，本脚本会尝试自动寻找后续可用端口。
    [int]$Port = 8765,

    # NoBrowser 表示只启动服务，不自动打开浏览器。
    # 适合你想手动复制地址，或者在脚本/测试环境中启动 WebUI。
    [switch]$NoBrowser,

    # NoAutoBootstrap 表示关闭自动安装基础依赖。
    # 默认不加这个参数：缺 .venv 或缺核心 Python 包时，会自动调用 bootstrap.ps1 修复。
    # 加上这个参数：只检查不修复，适合你想手动控制安装过程。
    [switch]$NoAutoBootstrap,

    # NoModelDownload 表示关闭启动时自动下载默认模型。
    # 默认不加这个参数：默认模型缺失时会自动调用 bootstrap.ps1 下载。
    # 如果你只想先打开 WebUI 页面，或者磁盘/网络暂时不方便下载大模型，可以加上它。
    [switch]$NoModelDownload,

    # TorchVariant 控制 PyTorch 安装版本。
    # auto：自动判断。有 nvidia-smi 时优先 CUDA 版，否则 CPU 版。
    # cpu：强制 CPU 版，兼容性较好但速度通常更慢。
    # cu121 / cu124：指定 CUDA 12.1 / 12.4 对应的 PyTorch 版本。
    # 专业解释：PyTorch 是模型推理框架；CUDA 版可以调用 NVIDIA 显卡加速。
    [ValidateSet("auto", "cpu", "cu121", "cu124")]
    [string]$TorchVariant = "auto",

    # ModelHub 控制模型下载来源。
    # hf：Hugging Face，国外网络通常更直接。
    # modelscope：ModelScope，国内网络有时更稳定。
    [ValidateSet("hf", "modelscope")]
    [string]$ModelHub = "hf",

    # InstallFunASR 表示初始化基础依赖时额外升级/修复 FunASR。
    # FunASR 在本项目里主要用于“标点恢复”；当前默认识别结果会补标点，所以 requirements.txt 已经包含 funasr。
    # 这个开关主要给旧环境使用：如果以前装过本项目但缺 funasr，可以加上它强制补装/升级。
    [switch]$InstallFunASR,

    # RunFullSelfCheck 表示启动前运行 scripts/self_check.py。
    # 完整自检会检查 Python、虚拟环境、ffmpeg、torch、qwen_asr、funasr 等项，更严格但会稍慢。
    [switch]$RunFullSelfCheck,

    # OnlyCheck 表示只做启动前检测和必要修复，不真正启动 WebUI。
    # 适合排查环境问题，也适合测试自动安装/自动下载逻辑。
    [switch]$OnlyCheck,

    # SkipFfmpegInstall 表示跳过 ffmpeg 自动安装。
    # 默认不加这个参数：启动 WebUI 前如果检测到系统没有 ffmpeg，会自动下载便携版到
    # .tools\ffmpeg，不需要你手动下载解压，也不会改动系统 PATH。
    # 加上这个参数：只检测不安装，适合你已经手动装了 ffmpeg 或者暂时不想联网下载。
    [switch]$SkipFfmpegInstall
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Resolve-ProjectRoot {
    if ($PSScriptRoot) {
        return $PSScriptRoot
    }

    if ($MyInvocation.MyCommand.Path) {
        return (Split-Path -Parent $MyInvocation.MyCommand.Path)
    }

    return (Get-Location).Path
}

function Get-ConfigBool {
    param(
        [string]$Name,
        [bool]$DefaultValue
    )

    # 环境变量适合临时覆盖配置，不需要改脚本文件。
    # 支持的真值：1 / true / yes / on
    # 支持的假值：0 / false / no / off
    $raw = [Environment]::GetEnvironmentVariable($Name)
    if ([string]::IsNullOrWhiteSpace($raw)) {
        return $DefaultValue
    }

    switch ($raw.Trim().ToLowerInvariant()) {
        "1" { return $true }
        "true" { return $true }
        "yes" { return $true }
        "on" { return $true }
        "0" { return $false }
        "false" { return $false }
        "no" { return $false }
        "off" { return $false }
        default {
            Write-Warning "环境变量 $Name=$raw 无法识别，继续使用默认值：$DefaultValue"
            return $DefaultValue
        }
    }
}

function Get-ConfigChoice {
    param(
        [string]$Name,
        [string]$CurrentValue,
        [string[]]$AllowedValues
    )

    $raw = [Environment]::GetEnvironmentVariable($Name)
    if ([string]::IsNullOrWhiteSpace($raw)) {
        return $CurrentValue
    }

    $value = $raw.Trim().ToLowerInvariant()
    if ($AllowedValues -contains $value) {
        return $value
    }

    Write-Warning "环境变量 $Name=$raw 不在允许范围：$($AllowedValues -join ', ')；继续使用：$CurrentValue"
    return $CurrentValue
}

function Get-BrowserHost {
    param([string]$HostName)

    # 0.0.0.0 / :: 表示“绑定所有网卡”，适合服务监听，但不适合作为浏览器访问地址。
    # 对入门用户来说最容易理解的做法，是在自动打开浏览器时统一回落到本机回环地址。
    if ($HostName -in @("0.0.0.0", "::", "[::]")) {
        return "127.0.0.1"
    }

    return $HostName
}

function Invoke-WebUiJson {
    param([string]$Url)

    try {
        return Invoke-RestMethod -Uri $Url -Method Get -TimeoutSec 2
    }
    catch {
        return $null
    }
}

function Get-PortOwnerSummary {
    param([int]$PortNumber)

    try {
        $connection = Get-NetTCPConnection -LocalPort $PortNumber -State Listen -ErrorAction Stop |
            Select-Object -First 1
        if (-not $connection) {
            return ""
        }

        $process = Get-Process -Id $connection.OwningProcess -ErrorAction Stop
        return "$($process.ProcessName) (PID $($process.Id))"
    }
    catch {
        return ""
    }
}

function Find-AvailablePort {
    param(
        [int]$StartPort,
        [int]$MaxAttempts = 30
    )

    $begin = [math]::Max(1, $StartPort)
    $end = [math]::Min(65535, $begin + [math]::Max(0, $MaxAttempts))

    for ($candidate = $begin; $candidate -le $end; $candidate++) {
        if (-not (Get-PortOwnerSummary -PortNumber $candidate)) {
            return $candidate
        }
    }

    throw "从端口 $StartPort 开始，连续 $MaxAttempts 个端口都被占用，无法自动找到可用端口。请手动指定一个更大的 -Port。"
}

function Assert-RequiredFile {
    param(
        [string]$Path,
        [string]$Description
    )

    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "未找到 $Description：$Path。请确认项目文件完整，并在项目根目录重新运行。"
    }
}

function Invoke-NativeCommandOutput {
    param(
        [string]$FilePath,
        [string[]]$Arguments
    )

    # Windows PowerShell 有一个容易坑新手的细节：
    # 外部程序即使退出码是 0，只要往 stderr 写了 warning，在 ErrorActionPreference=Stop 时也可能中断脚本。
    # Python / Transformers 很常见地会输出 FutureWarning；这不是启动失败，所以这里临时关闭 Stop，
    # 手动读取 LASTEXITCODE 来判断命令是否真正失败。
    $oldErrorActionPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $output = @(& $FilePath @Arguments 2>&1)
        $exitCode = $LASTEXITCODE
        return [pscustomobject]@{
            ExitCode = $exitCode
            Output = $output
        }
    }
    finally {
        $ErrorActionPreference = $oldErrorActionPreference
    }
}

function Test-CorePythonPackages {
    param([string]$PythonPath)

    $result = [ordered]@{
        Ok = $false
        ImportOk = $false
        PipCheckOk = $true
        ImportOutput = @()
        PipCheckOutput = @()
    }

    if (-not (Test-Path -LiteralPath $PythonPath -PathType Leaf)) {
        $result.ImportOutput = @("未找到虚拟环境 Python：$PythonPath")
        return [pscustomobject]$result
    }

    # 这里只检查 WebUI 启动和后续 ASR 任务最关键的 Python 包。
    # fastapi / uvicorn：负责网页服务。
    # qwen_asr / torch / soundfile：负责语音识别、模型推理和音频读取。
    # funasr：负责默认开启的标点恢复；缺少它时，识别本身能跑，但带标点输出会失败或被迫降级。
    # huggingface_hub / modelscope：负责模型下载能力。
    $importScript = @"
import fastapi, uvicorn, qwen_asr, torch, soundfile, funasr, huggingface_hub, modelscope
print('import_ok')
"@
    $importResult = Invoke-NativeCommandOutput -FilePath $PythonPath -Arguments @("-c", $importScript)
    if ($importResult.ExitCode -ne 0) {
        $result.ImportOutput = $importResult.Output
        return [pscustomobject]$result
    }

    $result.ImportOk = $true
    $result.Ok = $true

    # pip check 会检查“包声明的版本依赖关系”。
    # 它很有用，但某些非核心包的版本提示不一定影响 WebUI 启动，所以这里只作为警告，不作为硬失败。
    $pipCheckResult = Invoke-NativeCommandOutput -FilePath $PythonPath -Arguments @("-m", "pip", "check")
    if ($pipCheckResult.ExitCode -ne 0) {
        $result.PipCheckOk = $false
        $result.PipCheckOutput = $pipCheckResult.Output
    }

    return [pscustomobject]$result
}

function Invoke-BaseBootstrap {
    param(
        [string]$BootstrapScriptPath,
        [string]$TorchVariantValue,
        [bool]$InstallFunASRValue
    )

    $bootstrapParams = @{
        TorchVariant = $TorchVariantValue
    }
    $displayArgs = @("-TorchVariant", $TorchVariantValue)
    if ($InstallFunASRValue) {
        $bootstrapParams.InstallFunASR = $true
        $displayArgs += "-InstallFunASR"
    }

    Write-Host "[修复] 正在自动安装 / 修复基础依赖。"
    Write-Host "[说明] 首次运行需要下载 PyTorch 和项目依赖，可能需要几分钟到更久。"
    Write-Host "[命令] powershell -NoProfile -ExecutionPolicy Bypass -File `"$BootstrapScriptPath`" $($displayArgs -join ' ')"
    & $BootstrapScriptPath @bootstrapParams
    return $LASTEXITCODE
}

function Ensure-CoreEnvironment {
    param(
        [string]$PythonPath,
        [string]$BootstrapScriptPath,
        [bool]$AutoBootstrapValue,
        [string]$TorchVariantValue,
        [bool]$InstallFunASRValue
    )

    $check = Test-CorePythonPackages -PythonPath $PythonPath
    if (-not $check.Ok) {
        Write-Host "[检测] 未找到可用的虚拟环境，或 WebUI 核心 Python 依赖不完整。"
        if ($check.ImportOutput.Count -gt 0) {
            Write-Host "[检测] 导入检查提示："
            $check.ImportOutput | Select-Object -First 8 | ForEach-Object { Write-Host "  $_" }
        }

        if (-not $AutoBootstrapValue) {
            throw "AUTO_BOOTSTRAP 已关闭，无法自动修复依赖。请手动运行 .\bootstrap.ps1，完成后再启动 WebUI。"
        }

        $bootstrapExit = Invoke-BaseBootstrap -BootstrapScriptPath $BootstrapScriptPath -TorchVariantValue $TorchVariantValue -InstallFunASRValue $InstallFunASRValue
        if ($bootstrapExit -ne 0) {
            Write-Warning "bootstrap.ps1 返回了非零退出码：$bootstrapExit。将重新检查核心 Python 包；如果核心包可用，仍会继续启动 WebUI。"
        }

        $check = Test-CorePythonPackages -PythonPath $PythonPath
        if (-not $check.Ok) {
            if ($check.ImportOutput.Count -gt 0) {
                Write-Host "[检测] 自动修复后仍失败，最后的导入提示："
                $check.ImportOutput | Select-Object -First 12 | ForEach-Object { Write-Host "  $_" }
            }
            throw "自动安装后，核心 Python 依赖仍然不可用。常见原因是网络中断、Python 版本过低，或磁盘空间不足。"
        }
    }
    else {
        Write-Host "[检测] 虚拟环境与 WebUI 核心 Python 依赖已就绪。"
    }

    if (-not $check.PipCheckOk) {
        Write-Warning "pip check 发现了依赖版本提示，但核心包可以导入，WebUI 会继续启动。"
        $check.PipCheckOutput | Select-Object -First 8 | ForEach-Object { Write-Host "  $_" }
    }
}

function Test-DefaultModels {
    param([string]$ProjectRootPath)

    $asrDir = Join-Path $ProjectRootPath "models\Qwen3-ASR-1.7B"
    $alignerDir = Join-Path $ProjectRootPath "models\Qwen3-ForcedAligner-0.6B"

    $needAsr = $false
    $needAligner = $false
    $missing = @()

    foreach ($fileName in @("config.json", "model-00001-of-00002.safetensors", "model-00002-of-00002.safetensors", "model.safetensors.index.json")) {
        $path = Join-Path $asrDir $fileName
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
            $needAsr = $true
            $missing += $path
        }
    }

    foreach ($fileName in @("config.json", "model.safetensors")) {
        $path = Join-Path $alignerDir $fileName
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
            $needAligner = $true
            $missing += $path
        }
    }

    return [pscustomobject]@{
        Ok = (-not $needAsr -and -not $needAligner)
        NeedAsr = $needAsr
        NeedAligner = $needAligner
        Missing = $missing
    }
}

function Invoke-ModelDownload {
    param(
        [string]$BootstrapScriptPath,
        [string]$ModelHubValue,
        [bool]$NeedAsr,
        [bool]$NeedAligner
    )

    $modelParams = @{
        ModelHub = $ModelHubValue
    }
    $displayArgs = @("-ModelHub", $ModelHubValue)
    if ($NeedAsr) {
        $modelParams.DownloadAsrModel = $true
        $displayArgs += "-DownloadAsrModel"
    }
    if ($NeedAligner) {
        $modelParams.DownloadAlignerModel = $true
        $displayArgs += "-DownloadAlignerModel"
    }

    Write-Host "[下载] 正在下载缺失模型。"
    Write-Host "[说明] 模型文件较大，下载时间取决于网络速度；中途失败后可以重新运行，本地已有文件通常会复用。"
    Write-Host "[命令] powershell -NoProfile -ExecutionPolicy Bypass -File `"$BootstrapScriptPath`" $($displayArgs -join ' ')"
    & $BootstrapScriptPath @modelParams
    return $LASTEXITCODE
}

function Ensure-DefaultModels {
    param(
        [string]$ProjectRootPath,
        [string]$BootstrapScriptPath,
        [bool]$AutoDownloadModelsValue,
        [string]$ModelHubValue
    )

    $modelCheck = Test-DefaultModels -ProjectRootPath $ProjectRootPath
    if ($modelCheck.Ok) {
        Write-Host "[检测] 默认本地模型目录已就绪。"
        return
    }

    Write-Host "[检测] 默认本地模型目录缺失或不完整。"
    Write-Host "[说明] WebUI 可以先打开，但真正识别音频前需要 ASR 模型和对齐模型。"
    $modelCheck.Missing | Select-Object -First 8 | ForEach-Object { Write-Host "  缺少：$_" }

    if (-not $AutoDownloadModelsValue) {
        Write-Host "[跳过] 已关闭启动时自动下载模型。"
        Write-Host "[下一步] 打开 WebUI 后可以点击“下载模型”，也可以手动运行 .\bootstrap.ps1 -DownloadModels。"
        return
    }

    $downloadExit = Invoke-ModelDownload -BootstrapScriptPath $BootstrapScriptPath -ModelHubValue $ModelHubValue -NeedAsr $modelCheck.NeedAsr -NeedAligner $modelCheck.NeedAligner
    if ($downloadExit -ne 0) {
        Write-Warning "模型自动下载失败，退出码：$downloadExit。WebUI 仍会尝试启动；你可以稍后在网页里点“下载模型”。"
        return
    }

    $modelCheck = Test-DefaultModels -ProjectRootPath $ProjectRootPath
    if ($modelCheck.Ok) {
        Write-Host "[检测] 模型下载完成，默认本地模型目录已就绪。"
    }
    else {
        Write-Warning "下载命令已结束，但模型目录仍不完整。请查看上方下载日志，确认是否有网络中断或磁盘空间不足。"
    }
}

function Ensure-FfmpegTools {
    param(
        [string]$BootstrapScriptPath,
        [string]$EnvScriptPath,
        [bool]$SkipFfmpegInstallValue
    )

    # env.ps1 在脚本启动阶段已经加载过，它会把项目内 .tools\ffmpeg\bin 加入当前进程 PATH。
    # 所以如果系统或项目本地已经有 ffmpeg，到这里时 Get-Command 就能找到。
    $ffmpegFound = $null -ne (Get-Command ffmpeg -ErrorAction SilentlyContinue)
    $ffprobeFound = $null -ne (Get-Command ffprobe -ErrorAction SilentlyContinue)

    if ($ffmpegFound -and $ffprobeFound) {
        Write-Host "[检测] ffmpeg / ffprobe 已可用。"
        return
    }

    # 走到这里说明 ffmpeg 和 ffprobe 至少缺一个。
    # 常见情况：新 clone 的项目，.tools\ffmpeg 还是空的。
    if ($SkipFfmpegInstallValue) {
        Write-Host "[跳过] 已设置跳过 ffmpeg 自动安装。"
        if (-not $ffmpegFound) {
            Write-Warning "当前命令行找不到 ffmpeg。WebUI 可以打开，但提交音频任务时大概率会失败。"
        }
        if (-not $ffprobeFound) {
            Write-Warning "当前命令行找不到 ffprobe。ffprobe 通常和 ffmpeg 在同一个 bin 目录里。"
        }
        Write-Host "[下一步] 请安装 ffmpeg，并确认命令行能运行 ffmpeg -version；或者重新启动 WebUI（不加 -SkipFfmpegInstall）让项目自动安装。"
        return
    }

    Write-Host "[检测] ffmpeg / ffprobe 在当前 PATH 中缺失，准备项目内自动安装。"
    Write-Host "[说明] ffmpeg 是音频转码和时长提取的必需工具。"
    Write-Host "[说明] 项目会自动下载便携版 ffmpeg 到 .tools\ffmpeg（约 80 MB），约需几十秒到几分钟，取决于网速。"
    Write-Host "[说明] 安装位置只在当前项目内，不需要管理员权限，也不会修改你电脑的系统 PATH。"

    # 检查 bootstrap.ps1 是否存在（里面包含完整的下载/解压/校验逻辑）
    if (-not (Test-Path -LiteralPath $BootstrapScriptPath -PathType Leaf)) {
        Write-Warning "未找到 bootstrap.ps1，无法自动安装 ffmpeg。"
        Write-Warning "请确认项目文件完整，然后手动安装 ffmpeg。"
        return
    }

    # 调用 bootstrap.ps1 的 -InstallFfmpegOnly 模式：
    # - 如果系统 PATH 已有 ffmpeg：直接复用，不重复下载
    # - 如果 .tools\ffmpeg 已有：启用目录，不重复下载
    # - 如果都没有：下载 → 解压 → 校验 → 放入 .tools\ffmpeg → 加入当前进程 PATH
    Write-Host "[安装] 正在调用 bootstrap.ps1 -InstallFfmpegOnly ..."
    $oldErrorAction = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        & powershell -NoProfile -ExecutionPolicy Bypass -File $BootstrapScriptPath -InstallFfmpegOnly
        $installExit = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $oldErrorAction
    }

    # 无论 bootstrap.ps1 是否成功，都重新加载 env.ps1，让当前进程 PATH 包含可能新安装的 .tools\ffmpeg\bin
    if (Test-Path -LiteralPath $EnvScriptPath -PathType Leaf) {
        . $EnvScriptPath
    }

    # 再次检查
    $ffmpegFound = $null -ne (Get-Command ffmpeg -ErrorAction SilentlyContinue)
    $ffprobeFound = $null -ne (Get-Command ffprobe -ErrorAction SilentlyContinue)

    if ($ffmpegFound -and $ffprobeFound) {
        Write-Host "[检测] ffmpeg 自动安装完成，已可用。"
        return
    }

    # 安装失败时的友好提示
    Write-Warning "ffmpeg 自动安装未成功。"
    if ($installExit -ne 0) {
        Write-Warning "bootstrap.ps1 退出码：$installExit。请查看上方的错误日志。"
    }
    if (-not $ffmpegFound) {
        Write-Warning "当前命令行找不到 ffmpeg。"
    }
    if (-not $ffprobeFound) {
        Write-Warning "当前命令行找不到 ffprobe。"
    }
    Write-Host "[下一步] 你可以手动安装 ffmpeg："
    Write-Host "  1. 打开浏览器访问 https://www.gyan.dev/ffmpeg/builds/"
    Write-Host "  2. 下载 ffmpeg-release-essentials.zip"
    Write-Host "  3. 解压后把 bin 目录（里面有 ffmpeg.exe）的路径加入系统 PATH"
    Write-Host "  4. 重新打开命令行，确认 ffmpeg -version 能正常输出"
    Write-Host "  或者再次运行 .\\start_webui.ps1 自动重试。"
}

$ProjectRoot = Resolve-ProjectRoot
$ProjectRoot = [System.IO.Path]::GetFullPath($ProjectRoot)
$ProjectPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$BootstrapScript = Join-Path $ProjectRoot "bootstrap.ps1"
$RequirementsFile = Join-Path $ProjectRoot "requirements.txt"
$SelfCheckScript = Join-Path $ProjectRoot "scripts\self_check.py"
$EnvScript = Join-Path $ProjectRoot "env.ps1"

Assert-RequiredFile -Path $BootstrapScript -Description "环境初始化脚本 bootstrap.ps1"
Assert-RequiredFile -Path $RequirementsFile -Description "Python 依赖清单 requirements.txt"

if (Test-Path -LiteralPath $EnvScript -PathType Leaf) {
    # env.ps1 通常用来设置 Hugging Face / Transformers 等缓存目录。
    # 先加载它，可以让依赖下载和模型加载都使用项目内缓存，减少系统盘占用。
    . $EnvScript
}

# 环境变量覆盖说明：
# QWEN3_ASR_AUTO_BOOTSTRAP=0      关闭自动安装基础依赖
# QWEN3_ASR_AUTO_DOWNLOAD_MODELS=0 关闭启动时自动下载模型
# QWEN3_ASR_TORCH_VARIANT=cpu    临时指定 PyTorch 版本策略
# QWEN3_ASR_MODEL_HUB=modelscope 临时指定模型下载来源
# QWEN3_ASR_INSTALL_FUNASR=1     初始化时额外升级/修复 FunASR；旧环境缺标点依赖时可用
# QWEN3_ASR_RUN_FULL_SELF_CHECK=1 启动前运行完整自检
# QWEN3_ASR_ONLY_CHECK=1         只检查和修复，不启动 WebUI
# QWEN3_ASR_SKIP_FFMPEG_INSTALL=1 跳过 ffmpeg 自动安装；适合已手动装好 ffmpeg 的情况
$autoBootstrap = Get-ConfigBool -Name "QWEN3_ASR_AUTO_BOOTSTRAP" -DefaultValue $true
$autoDownloadModels = Get-ConfigBool -Name "QWEN3_ASR_AUTO_DOWNLOAD_MODELS" -DefaultValue $true
$TorchVariant = Get-ConfigChoice -Name "QWEN3_ASR_TORCH_VARIANT" -CurrentValue $TorchVariant -AllowedValues @("auto", "cpu", "cu121", "cu124")
$ModelHub = Get-ConfigChoice -Name "QWEN3_ASR_MODEL_HUB" -CurrentValue $ModelHub -AllowedValues @("hf", "modelscope")
$installFunASRValue = [bool]$InstallFunASR -or (Get-ConfigBool -Name "QWEN3_ASR_INSTALL_FUNASR" -DefaultValue $false)
$runFullSelfCheckValue = [bool]$RunFullSelfCheck -or (Get-ConfigBool -Name "QWEN3_ASR_RUN_FULL_SELF_CHECK" -DefaultValue $false)
$onlyCheckValue = [bool]$OnlyCheck -or (Get-ConfigBool -Name "QWEN3_ASR_ONLY_CHECK" -DefaultValue $false)
$skipFfmpegInstall = [bool]$SkipFfmpegInstall -or (Get-ConfigBool -Name "QWEN3_ASR_SKIP_FFMPEG_INSTALL" -DefaultValue $false)

if ($NoAutoBootstrap) {
    $autoBootstrap = $false
}
if ($NoModelDownload) {
    $autoDownloadModels = $false
}
if ($SkipFfmpegInstall) {
    $skipFfmpegInstall = $true
}

$BrowserHost = Get-BrowserHost -HostName $BindHost
$RequestedAppUrl = "http://${BrowserHost}:${Port}"
$RequestedProbeUrl = "$RequestedAppUrl/api/health"
$RequestedMetaUrl = "http://${BrowserHost}:${Port}/api/meta"
$ResolvedPort = $Port

Write-Host "[状态] 项目根目录：$ProjectRoot"
Write-Host "[状态] Python：$ProjectPython"
Write-Host "[状态] 自动安装基础依赖：$autoBootstrap"
Write-Host "[状态] 自动下载默认模型：$autoDownloadModels"
Write-Host "[状态] 跳过 ffmpeg 自动安装：$skipFfmpegInstall"
Write-Host "[状态] PyTorch 安装策略：$TorchVariant"
Write-Host "[状态] 模型下载来源：$ModelHub"

# 先探测目标端口上是否已经有可用的 WebUI。
# 很多新手会重复双击 run_webui.bat；如果同一个项目已经在运行，最友好的行为是复用现有实例。
$health = Invoke-WebUiJson -Url $RequestedProbeUrl
if ($health -and $health.status -eq "ok") {
    $meta = Invoke-WebUiJson -Url $RequestedMetaUrl
    $runningProjectRoot = ""
    if ($meta -and $meta.project_root) {
        $runningProjectRoot = [System.IO.Path]::GetFullPath([string]$meta.project_root)
    }

    if ($runningProjectRoot -eq $ProjectRoot) {
        Write-Host "[状态] 已发现当前项目的 WebUI 正在运行，直接复用。"
        if (-not $NoBrowser) {
            Start-Process $RequestedAppUrl
        }
        return
    }

    if ($runningProjectRoot) {
        $ResolvedPort = Find-AvailablePort -StartPort ($Port + 1)
        Write-Host "[状态] 端口 $Port 已被另一个 Qwen3-ASR WebUI 占用：$runningProjectRoot。自动切换到端口 $ResolvedPort。"
    }
}

Ensure-CoreEnvironment -PythonPath $ProjectPython -BootstrapScriptPath $BootstrapScript -AutoBootstrapValue $autoBootstrap -TorchVariantValue $TorchVariant -InstallFunASRValue $installFunASRValue
Ensure-FfmpegTools -BootstrapScriptPath $BootstrapScript -EnvScriptPath $EnvScript -SkipFfmpegInstallValue $skipFfmpegInstall
Ensure-DefaultModels -ProjectRootPath $ProjectRoot -BootstrapScriptPath $BootstrapScript -AutoDownloadModelsValue $autoDownloadModels -ModelHubValue $ModelHub

if ($runFullSelfCheckValue) {
    if (Test-Path -LiteralPath $SelfCheckScript -PathType Leaf) {
        Write-Host "[自检] 正在运行完整环境自检：$SelfCheckScript"
        & $ProjectPython $SelfCheckScript
        if ($LASTEXITCODE -ne 0) {
            Write-Warning "完整自检没有全部通过。WebUI 可以尝试启动，但 FAIL 项可能影响后续任务。"
        }
    }
    else {
        Write-Host "[跳过] 未找到完整自检脚本：$SelfCheckScript"
    }
}

if ($onlyCheckValue) {
    Write-Host "[完成] OnlyCheck 已启用，本次只执行检测与必要依赖修复，不启动 WebUI。"
    return
}

if ($ResolvedPort -eq $Port) {
    $portOwner = Get-PortOwnerSummary -PortNumber $Port
    if ($portOwner) {
        $ResolvedPort = Find-AvailablePort -StartPort ($Port + 1)
        Write-Host "[状态] 端口 $Port 已被其他程序占用：$portOwner。自动切换到端口 $ResolvedPort。"
    }
}

$AppUrl = "http://${BrowserHost}:${ResolvedPort}"

Write-Host "[状态] 浏览器地址：$AppUrl"

if (-not $NoBrowser) {
    Start-Job -ScriptBlock {
        param($Url)
        Start-Sleep -Seconds 2
        Start-Process $Url
    } -ArgumentList $AppUrl | Out-Null
}

Write-Host "[启动] 正在启动 WebUI，首次打开可能需要几秒。"
Push-Location $ProjectRoot
try {
    & $ProjectPython -m uvicorn webui.app:app --host $BindHost --port $ResolvedPort
    $exitCode = $LASTEXITCODE
    if ($exitCode -ne 0) {
        throw "[错误] WebUI 启动失败，退出码 $exitCode。请先看上面的报错提示；如果是端口问题，换一个 -Port 再试。"
    }
}
finally {
    Pop-Location
}
