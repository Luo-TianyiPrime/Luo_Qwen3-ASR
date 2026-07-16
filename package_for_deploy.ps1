<#
.SYNOPSIS
    Qwen3-ASR 离线打包脚本 — 一键生成"开箱即用"的部署包
.DESCRIPTION
    在隔离的临时文件夹中组装项目，剔除缓存/产出物，
    附带离线依赖包（.whl）+ 完整版 Python 安装指引，
    最终输出标准 ZIP 压缩包。
.NOTES
    绝不修改原始工作区任何文件。所有操作均在独立临时文件夹中完成。
#>

param(
    # 原始项目根目录。留空时就是本脚本所在的 Qwen3-ASR 目录；不要填写它的上级 models 目录。
    [string]$SourceRoot = "",

    # 输出 ZIP 路径（留空则放在 %TEMP%\Qwen3-ASR_Package_时间戳.zip）
    [string]$OutputZip = "",

    # 是否跳过离线 whl 包下载（目标设备网络可用时可跳过）
    [switch]$SkipWheelDownload,

    # 目标 Python 版本（仅用于生成安装指引；脚本不会擅自安装系统软件）
    [string]$PortablePythonVersion = "3.11.9",

    # PyTorch 变体：auto / cpu / cu121 / cu124
    [ValidateSet("auto", "cpu", "cu121", "cu124")]
    [string]$TorchVariant = "auto",

    # 离线 wheel 中 torch/torchaudio 的共同版本。2.6.0 是当前项目已完成真实 CUDA 推理回归的稳定基线。
    [string]$TorchVersion = "2.6.0",

    # 生成“代码包”时跳过数 GB 的 models 目录。目标机必须另行复制模型或联网运行 bootstrap 下载。
    [switch]$SkipModels,

    # 打包成功后删除临时组装目录。默认不删除，方便核对内容，也避免脚本在无人值守时执行递归删除。
    [switch]$RemoveStaging
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# ============================================================
# 0. 辅助函数
# ============================================================
function Format-Size {
    param([long]$Bytes)
    if ($Bytes -gt 1GB) { return ("{0:N2} GB" -f ($Bytes / 1GB)) }
    if ($Bytes -gt 1MB) { return ("{0:N2} MB" -f ($Bytes / 1MB)) }
    if ($Bytes -gt 1KB) { return ("{0:N2} KB" -f ($Bytes / 1KB)) }
    return ("{0} B" -f $Bytes)
}

function Log {
    param([string]$Msg)
    Write-Host "[package] $Msg"
}

function Log-Warn {
    param([string]$Msg)
    Write-Warning "[package] $Msg"
}

function Invoke-NativeChecked {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [Parameter(Mandatory = $true)][object[]]$Arguments,
        [Parameter(Mandatory = $true)][string]$Description
    )

    # PowerShell 5.1 不会自动把 pip 的非零退出码变成异常。必须立即检查 LASTEXITCODE，
    # 否则网络中断时仍可能生成一个“看起来完成、实际缺包”的离线 ZIP。
    & $FilePath @Arguments
    $exitCode = $LASTEXITCODE
    if ($exitCode -ne 0) {
        throw "$Description 失败（exit code=$exitCode）。请查看上方 pip 输出的最后几行。"
    }
}

# ============================================================
# 1. 确定源目录
# ============================================================
if ([string]::IsNullOrWhiteSpace($SourceRoot)) {
    $SourceRoot = $PSScriptRoot
}
$SourceRoot = [System.IO.Path]::GetFullPath($SourceRoot).TrimEnd([char[]]@('\', '/'))

if (-not (Test-Path -LiteralPath $SourceRoot -PathType Container)) {
    throw "源目录不存在：$SourceRoot"
}

# 用几个不会出现在普通模型仓库里的入口文件核验源目录，防止误把 E:\models 整个上级目录打进 ZIP。
$RequiredProjectEntries = @("run.ps1", "bootstrap.ps1", "requirements.txt", "scripts", "webui")
$MissingEntries = @($RequiredProjectEntries | Where-Object { -not (Test-Path -LiteralPath (Join-Path $SourceRoot $_)) })
if ($MissingEntries.Count -gt 0) {
    throw "SourceRoot 不是完整的 Qwen3-ASR 项目根目录：$SourceRoot。缺少：$($MissingEntries -join ', ')"
}

Log "源目录：$SourceRoot"

# ============================================================
# 2. 创建隔离打包工作目录
# ============================================================
$Timestamp = Get-Date -Format "yyyyMMdd_HHmmss"

# 在复制数 GB 模型之前先确定并校验输出位置。若同名 ZIP 已存在，应立即停止，
# 既避免覆盖已有产物，也避免用户等到打包最后一步才收到错误。
if ([string]::IsNullOrWhiteSpace($OutputZip)) {
    $OutputZip = Join-Path $env:TEMP "Qwen3-ASR_Package_$Timestamp.zip"
}
if (-not $OutputZip.EndsWith(".zip", [System.StringComparison]::OrdinalIgnoreCase)) {
    $OutputZip = "$OutputZip.zip"
}
$OutputZip = [System.IO.Path]::GetFullPath($OutputZip)
if (Test-Path -LiteralPath $OutputZip) {
    throw "输出 ZIP 已存在，为避免覆盖已有部署包已停止：$OutputZip。请换一个 -OutputZip 文件名。"
}
$OutputParent = Split-Path -Parent $OutputZip
if (-not (Test-Path -LiteralPath $OutputParent -PathType Container)) {
    # 只创建用户明确指定 ZIP 的父目录，不会删除或覆盖其中任何已有内容。
    New-Item -ItemType Directory -Force -Path $OutputParent | Out-Null
}

$StagingDir = Join-Path $env:TEMP "Qwen3ASR_Staging_${Timestamp}_$([guid]::NewGuid().ToString('N').Substring(0, 8))"
New-Item -ItemType Directory -Force -Path $StagingDir | Out-Null

Log "隔离打包目录：$StagingDir"

# ============================================================
# 3. 定义排除规则
# ============================================================

# 排除的目录名（相对路径片段）
$ExcludeDirs = @(
    "__pycache__",
    ".venv",
    ".cache",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".playwright-cli",
    "outputs",
    "asr_output",
    "inputs",
    ".git",
    ".github"
)

if ($SkipModels) {
    $ExcludeDirs += "models"
    Log "已启用 -SkipModels：部署 ZIP 不包含本地模型，目标机需要另行准备 models 目录。"
}

# 排除的文件扩展名
$ExcludeExtensions = @(
    ".pyc", ".pyo", ".pyd",
    ".log", ".tmp", ".temp",
    ".bak", ".swp",
    # 旧部署 ZIP 如果位于项目根目录，绝不能再次被塞进新 ZIP；同时排除常见归档产物。
    ".zip", ".7z", ".rar",
    ".DS_Store", "Thumbs.db"
)

# 排除的具体文件名
$ExcludeFiles = @(
    "nul"   # Windows null device artifact
)

# ============================================================
# 4. 复制文件（智能过滤）
# ============================================================
function Should-Exclude {
    param([string]$RelativePath)

    $normalized = $RelativePath.Replace("\", "/").ToLowerInvariant()

    # 检查目录排除
    foreach ($dir in $ExcludeDirs) {
        $dirLower = $dir.ToLowerInvariant()
        if ($normalized -eq $dirLower -or $normalized.StartsWith("$dirLower/")) {
            return $true
        }
    }

    # 检查扩展名排除
    foreach ($ext in $ExcludeExtensions) {
        if ($normalized.EndsWith($ext.ToLowerInvariant())) {
            return $true
        }
    }

    # 检查文件名排除
    $fileName = [System.IO.Path]::GetFileName($RelativePath).ToLowerInvariant()
    foreach ($file in $ExcludeFiles) {
        if ($fileName -eq $file.ToLowerInvariant()) {
            return $true
        }
    }

    return $false
}

$CopyCount = 0
$ExcludeCount = 0

$AllFiles = Get-ChildItem -LiteralPath $SourceRoot -File -Recurse -Force

foreach ($file in $AllFiles) {
    $RelativePath = $file.FullName.Substring($SourceRoot.Length + 1)

    if (Should-Exclude -RelativePath $RelativePath) {
        $ExcludeCount++
        continue
    }

    $DestPath = Join-Path $StagingDir $RelativePath
    $DestParent = Split-Path $DestPath -Parent
    if (-not (Test-Path $DestParent)) {
        New-Item -ItemType Directory -Force -Path $DestParent | Out-Null
    }

    Copy-Item -LiteralPath $file.FullName -Destination $DestPath -Force
    $CopyCount++
}

Log "文件复制完成：已复制 $CopyCount 个文件，排除 $ExcludeCount 个文件"

# `.cache` 整体必须排除，因为它还包含任务日志、下载临时文件和个人偏好；但默认标点模型也由
# ModelScope 放在其中。完整部署包只定点复制已完成的标点模型目录，避免离线目标机首次运行时降级为无标点。
$PunctuationModelRelativePath = "models\iic\punc_ct-transformer_cn-en-common-vocab471067-large"
$PunctuationModelSource = Join-Path $SourceRoot ".cache\modelscope\$PunctuationModelRelativePath"
$PunctuationModelIncluded = $false
if (-not $SkipModels -and
    (Test-Path -LiteralPath (Join-Path $PunctuationModelSource "model.pt") -PathType Leaf) -and
    (Test-Path -LiteralPath (Join-Path $PunctuationModelSource "configuration.json") -PathType Leaf)) {
    $PunctuationModelDestination = Join-Path $StagingDir ".cache\modelscope\$PunctuationModelRelativePath"
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $PunctuationModelDestination) | Out-Null
    Copy-Item -LiteralPath $PunctuationModelSource -Destination $PunctuationModelDestination -Recurse -Force
    $PunctuationModelIncluded = $true
    $PunctuationSize = (Get-ChildItem -LiteralPath $PunctuationModelSource -File -Recurse | Measure-Object Length -Sum).Sum
    Log "已加入离线标点模型：$(Format-Size $PunctuationSize)"
} elseif (-not $SkipModels) {
    Log-Warn "本机尚无完整标点模型缓存，部署包不会包含它。目标机首次启用标点恢复时需要联网；核心 ASR 仍可运行并会明确提示降级。"
}

# ============================================================
# 5. 创建离线依赖包（wheels）
# ============================================================
$OfflineDir = Join-Path $StagingDir "_offline_deps"
New-Item -ItemType Directory -Force -Path $OfflineDir | Out-Null

# 离线安装仍使用项目自己的依赖清单；额外加入 torch / torchaudio，因为它们需要按 CPU/CUDA 变体选择。
# 直接从 wheel 文件名反推包名并不可靠（名称中可能含下划线，版本还可能带本地标签），所以不再做字符串猜测。
$ReqFile = Join-Path $OfflineDir "requirements.txt"
$OfflineRequirements = @(
    "# 本文件供部署机离线安装使用；--find-links 会让 pip 从同目录查找 wheel。"
    "# torch 与 torchaudio 必须来自同一 CPU/CUDA 变体，否则可能出现 DLL 加载失败。"
    "torch==$TorchVersion"
    "torchaudio==$TorchVersion"
) + @(Get-Content -LiteralPath (Join-Path $SourceRoot "requirements.txt") -Encoding UTF8)
[System.IO.File]::WriteAllLines($ReqFile, $OfflineRequirements, (New-Object System.Text.UTF8Encoding $false))

if (-not $SkipWheelDownload) {
    # 尝试使用原始项目的 .venv 来下载依赖
    $VenvPip = Join-Path $SourceRoot ".venv\Scripts\pip.exe"
    $SystemPip = "pip"

    $PipExe = $null
    if (Test-Path $VenvPip) {
        $PipExe = $VenvPip
        Log "使用项目 venv 的 pip：$PipExe"
    } elseif (Get-Command pip -ErrorAction SilentlyContinue) {
        $PipExe = $SystemPip
        Log "使用系统 pip"
    } else {
        Log-Warn "未找到 pip，跳过离线依赖包下载。目标设备需要联网安装依赖。"
    }

    if ($PipExe) {
        Log "开始下载离线依赖包（.whl）到 _offline_deps/ ..."
        Log "依赖来源：项目 requirements.txt + torch + torchaudio（包括它们的传递依赖）"

        # 解析 Torch 变体
        $ResolvedTorch = $TorchVariant
        if ($ResolvedTorch -eq "auto") {
            if (Get-Command nvidia-smi -ErrorAction SilentlyContinue) {
                $ResolvedTorch = "cu124"
            } else {
                $ResolvedTorch = "cpu"
            }
        }

        $WheelIndex = ""
        switch ($ResolvedTorch) {
            "cpu"   { $WheelIndex = "https://download.pytorch.org/whl/cpu" }
            "cu121" { $WheelIndex = "https://download.pytorch.org/whl/cu121" }
            "cu124" { $WheelIndex = "https://download.pytorch.org/whl/cu124" }
        }

        # PyPI 仍是普通依赖的主源，PyTorch 官方源作为额外源提供指定 CUDA/CPU 变体。
        # 一次交给 pip 解析整张依赖图，避免逐包下载时混入另一种 torch，或漏掉传递依赖。
        Log "下载完整依赖图，PyTorch 变体：$ResolvedTorch ..."
        Invoke-NativeChecked -FilePath $PipExe -Arguments @(
            "download", "-r", $ReqFile, "-d", $OfflineDir,
            "--extra-index-url", $WheelIndex
        ) -Description "下载离线 Python 依赖"

        $WheelFiles = Get-ChildItem -Path $OfflineDir -File -Filter "*.whl"

        $WheelSize = (Get-ChildItem -Path $OfflineDir -File | Measure-Object -Property Length -Sum).Sum
        Log "离线依赖包下载完成：$($WheelFiles.Count) 个文件，$(Format-Size $WheelSize)"
    }
} else {
    Log "跳过离线依赖包下载（-SkipWheelDownload 已启用）"
}

# ============================================================
# 6. 生成部署指引 README
# ============================================================
$ModelsGuide = if ($SkipModels) {
    "AI 模型文件（本包使用 -SkipModels，未包含；请另行复制或联网运行 bootstrap 下载）"
} else {
    "AI 模型文件（本包已包含，无需重复下载）"
}
$PunctuationGuide = if ($PunctuationModelIncluded) {
    "默认 FunASR 标点模型（已从本机完整缓存加入，可离线恢复标点）"
} else {
    "默认 FunASR 标点模型（本包未包含；首次使用需联网下载，失败时核心 ASR 会保留无标点结果并给出警告）"
}

$DeployReadme = @"
# Qwen3-ASR 部署包

## 快速开始

### 前置条件

- Windows 10/11
- 完整版 64 位 Python $PortablePythonVersion（Python 3.10/3.11 均可，推荐与打包机版本一致）
  - 官方安装器：https://www.python.org/ftp/python/$PortablePythonVersion/python-$PortablePythonVersion-amd64.exe
  - 安装时勾选 **Add Python to PATH**；它表示让 PowerShell 能直接找到 \`python\` 命令

> 不要使用 python.org 的 embeddable ZIP 执行下面步骤。那个包面向应用嵌入，默认没有完整 pip，
> 也不保证支持 \`python -m venv\`；简单解压 \`python311.zip\` 并不能正确“启用 pip”。

### 方式一：完整 Python + 离线 wheel（推荐离线部署）

1. 在联网电脑下载并安装上面的官方 64 位 Python 安装器。
2. 把本 ZIP 解压到目标电脑，在项目目录打开 PowerShell。
3. 确认 \`_offline_deps\` 中除了 requirements.txt 之外还有许多 \`.whl\` 文件，然后执行：

   \`\`\`powershell
   # 创建隔离虚拟环境；它避免本项目依赖污染系统里的其它 Python 项目
   python -m venv .venv

   # --no-index 表示完全不联网；--find-links 指定本地 wheel 所在目录
   .\.venv\Scripts\pip.exe install --no-index --find-links=./_offline_deps -r ./_offline_deps/requirements.txt

   # 启动 WebUI
   .\run_webui.bat
   \`\`\`

### 方式二：联网一键初始化

\`\`\`powershell
# bootstrap 会创建虚拟环境、安装 requirements.txt、自检 ffmpeg，并在失败时给出中文下一步
.\\bootstrap.ps1

# 启动 WebUI
.\\run_webui.bat
\`\`\`

## 目录说明

| 路径 | 说明 |
|------|------|
| \`models/\` | $ModelsGuide |
| \`.cache/modelscope/\` | $PunctuationGuide |
| \`webui/\` | Web 界面源代码 |
| \`scripts/\` | 核心处理脚本 |
| \`configs/\` | 配置文件 |
| \`_offline_deps/\` | 离线 Python 依赖包（.whl） |
| \`inputs/\` | 放入待处理的音频文件（需自行创建） |
| \`outputs/\` | 处理结果输出目录（运行时自动创建） |

## 运行模式

- **CLI 批量处理**：修改 \`run.ps1\` 中的 \`Audio\` 配置后执行 \`./run.ps1\`
- **WebUI 交互界面**：双击 \`run_webui.bat\` 或执行 \`./start_webui.ps1\`

## 注意事项

- 本打包脚本会创建空的 \`inputs/\` 和 \`outputs/\` 目录
- 如果有 NVIDIA GPU，确保安装了对应 CUDA 版本的 PyTorch
- 离线 wheel 与 Python 版本、Windows/CPU 架构有关；请尽量在与部署机相同的 Python 3.11 x64 环境中打包
- 标点恢复是识别后的可选文本处理。标点模型未包含或加载失败时，核心 ASR 不会丢结果，但 `meta.json` 会记录降级原因
- 模型文件较大，ZIP 包可能超过 5GB，解压需要足够磁盘空间
"@

[System.IO.File]::WriteAllText(
    (Join-Path $StagingDir "DEPLOY_GUIDE.md"),
    $DeployReadme,
    (New-Object System.Text.UTF8Encoding $false)
)

Log "部署指引已生成：DEPLOY_GUIDE.md"

# ============================================================
# 7. 创建空的必要目录（inputs/outputs/asr_output）
# ============================================================
foreach ($dir in @("inputs", "outputs", "asr_output")) {
    $DirPath = Join-Path $StagingDir $dir
    if (-not (Test-Path $DirPath)) {
        New-Item -ItemType Directory -Force -Path $DirPath | Out-Null
    }
}

Log "已创建空目录：inputs/, outputs/, asr_output/"

# ============================================================
# 8. 统计打包信息
# ============================================================
$StagingSize = (Get-ChildItem -LiteralPath $StagingDir -Recurse -File | Measure-Object -Property Length -Sum).Sum
$FileCount = (Get-ChildItem -LiteralPath $StagingDir -Recurse -File).Count

Log "========================================"
Log "打包目录统计"
Log "  文件总数：$FileCount"
Log "  总大小：$(Format-Size $StagingSize)"
Log "  位置：$StagingDir"
Log "========================================"

# ============================================================
# 9. 压缩为 ZIP
# ============================================================
Log "开始压缩为 ZIP：$OutputZip"
$CompressStart = Get-Date

# 使用 .NET 原生压缩（无需额外依赖）
Add-Type -AssemblyName System.IO.Compression.FileSystem

# CreateFromDirectory 会把组装目录中的内容直接放到 ZIP 根层，解压后即可看到 run.ps1 和 DEPLOY_GUIDE.md。
[System.IO.Compression.ZipFile]::CreateFromDirectory($StagingDir, $OutputZip)

$CompressElapsed = ((Get-Date) - $CompressStart).TotalSeconds
$ZipSize = (Get-Item $OutputZip).Length

Log "压缩完成！"
Log "  ZIP 路径：$OutputZip"
Log "  ZIP 大小：$(Format-Size $ZipSize)"
Log "  压缩耗时：$([math]::Round($CompressElapsed, 1)) 秒"

# ============================================================
# 10. 清理临时打包目录（仅显式传入 -RemoveStaging 时执行）
# ============================================================
$resolvedTemp = [System.IO.Path]::GetFullPath($env:TEMP).TrimEnd('\') + '\'
$resolvedStaging = [System.IO.Path]::GetFullPath($StagingDir)
if ($RemoveStaging) {
    # 递归删除前再次确认目标确实位于系统临时目录，且名称带本脚本专用前缀。
    if (-not $resolvedStaging.StartsWith($resolvedTemp, [System.StringComparison]::OrdinalIgnoreCase) -or
        -not ([System.IO.Path]::GetFileName($resolvedStaging)).StartsWith("Qwen3ASR_Staging_")) {
        throw "拒绝清理异常路径：$resolvedStaging"
    }
    Remove-Item -LiteralPath $StagingDir -Recurse -Force
    Log "已删除临时打包目录"
} else {
    Log "临时打包目录已保留：$StagingDir"
}

Log "========================================"
Log "打包全部完成！"
Log "  最终产物：$OutputZip"
Log "  大小：$(Format-Size $ZipSize)"
Log "========================================"
