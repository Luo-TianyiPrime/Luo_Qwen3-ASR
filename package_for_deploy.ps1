<#
.SYNOPSIS
    Qwen3-ASR 离线打包脚本 — 一键生成"开箱即用"的部署包
.DESCRIPTION
    在隔离的临时文件夹中组装项目，剔除缓存/产出物，
    附带离线依赖包（.whl）+ 便携 Python 下载指引，
    最终输出标准 ZIP 压缩包。
.NOTES
    绝不修改原始工作区任何文件。所有操作均在独立临时文件夹中完成。
#>

param(
    # 原始项目根目录（默认当前脚本所在目录的上级，即 E:\models\Qwen3-ASR）
    [string]$SourceRoot = "",

    # 输出 ZIP 路径（留空则放在 %TEMP%\Qwen3-ASR_Package_时间戳.zip）
    [string]$OutputZip = "",

    # 是否跳过离线 whl 包下载（目标设备网络可用时可跳过）
    [switch]$SkipWheelDownload,

    # 便携 Python 版本（仅记录到 README，不自动下载）
    [string]$PortablePythonVersion = "3.11.9",

    # PyTorch 变体：auto / cpu / cu121 / cu124
    [ValidateSet("auto", "cpu", "cu121", "cu124")]
    [string]$TorchVariant = "auto"
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

# ============================================================
# 1. 确定源目录
# ============================================================
if ([string]::IsNullOrWhiteSpace($SourceRoot)) {
    $SourceRoot = (Get-Item $PSScriptRoot).Parent.FullName
}
$SourceRoot = [System.IO.Path]::GetFullPath($SourceRoot)

if (-not (Test-Path $SourceRoot)) {
    throw "源目录不存在：$SourceRoot"
}

Log "源目录：$SourceRoot"

# ============================================================
# 2. 创建隔离打包工作目录
# ============================================================
$Timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$StagingDir = Join-Path $env:TEMP "Qwen3ASR_Staging_$Timestamp"
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
    ".playwright-cli",
    "outputs",
    "asr_output",
    "inputs",
    ".git",
    ".github"
)

# 排除的文件扩展名
$ExcludeExtensions = @(
    ".pyc", ".pyo", ".pyd",
    ".log", ".tmp", ".temp",
    ".bak", ".swp",
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

# ============================================================
# 5. 创建离线依赖包（wheels）
# ============================================================
$OfflineDir = Join-Path $StagingDir "_offline_deps"
New-Item -ItemType Directory -Force -Path $OfflineDir | Out-Null

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
        # 核心依赖列表
        $Packages = @(
            "qwen-asr",
            "soundfile",
            "modelscope",
            "fastapi",
            "uvicorn",
            "huggingface_hub",
            "funasr"
        )

        Log "开始下载离线依赖包（.whl）到 _offline_deps/ ..."
        Log "目标包：$($Packages -join ', ')"

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

        # 先下载 torch + torchaudio（指定 index）
        if ($WheelIndex) {
            Log "下载 PyTorch ($ResolvedTorch) ..."
            & $PipExe download torch torchaudio -d $OfflineDir --no-deps --index-url $WheelIndex 2>&1 | ForEach-Object { Log "  $_" }
        }

        # 下载其余依赖
        foreach ($pkg in $Packages) {
            if ($pkg -in @("torch", "torchaudio")) { continue }
            Log "下载 $pkg ..."
            & $PipExe download $pkg -d $OfflineDir 2>&1 | ForEach-Object { Log "  $_" }
        }

        # 生成 requirements.txt
        $ReqFile = Join-Path $OfflineDir "requirements.txt"
        $WheelFiles = Get-ChildItem -Path $OfflineDir -File -Filter "*.whl"
        $Reqs = @()
        foreach ($w in $WheelFiles) {
            # 从 wheel 文件名提取包名和版本
            # 格式：{name}-{version}(-{build})?-{python}-{abi}-{platform}.whl
            $Parts = $w.BaseName -split "-"
            if ($Parts.Count -ge 2) {
                $Name = $Parts[0]
                $Version = $Parts[1]
                $Reqs += "$Name==$Version"
            }
        }
        [System.IO.File]::WriteAllLines($ReqFile, $Reqs, (New-Object System.Text.UTF8Encoding $false))

        $WheelSize = (Get-ChildItem -Path $OfflineDir -File | Measure-Object -Property Length -Sum).Sum
        Log "离线依赖包下载完成：$($WheelFiles.Count) 个文件，$(Format-Size $WheelSize)"
    }
} else {
    Log "跳过离线依赖包下载（-SkipWheelDownload 已启用）"
}

# ============================================================
# 6. 生成部署指引 README
# ============================================================
$DeployReadme = @"
# Qwen3-ASR 部署包

## 快速开始

### 前置条件
- Windows 10/11
- Python $PortablePythonVersion（推荐使用便携版或官方安装包）
  - 便携版下载：https://www.python.org/ftp/python/$PortablePythonVersion/python-$PortablePythonVersion-embed-amd64.zip
  - 或使用 conda / 系统安装的 Python 3.11+

### 方式一：使用便携 Python（推荐离线部署）

1. 下载便携 Python 并解压到本目录的 \`_portable_python\` 文件夹
   - 下载地址：https://www.python.org/ftp/python/$PortablePythonVersion/python-$PortablePythonVersion-embed-amd64.zip
2. 解压 \`python$($PortablePythonVersion.Split('.')[0..1] -join '')_zip.zip\`（在便携 Python 压缩包内）
   - 这一步是为了启用 pip
3. 打开 PowerShell，执行：

   \`\`\`powershell
   # 创建虚拟环境
   .\_portable_python\python.exe -m venv .venv

   # 安装离线依赖
   .\.venv\Scripts\pip.exe install --no-index --find-links=./_offline_deps -r ./_offline_deps/requirements.txt

   # 启动 WebUI
   .\run_webui.bat
   \`\`\`

### 方式二：使用系统已安装的 Python

\`\`\`powershell
# 创建虚拟环境
python -m venv .venv

# 激活
.\\.venv\\Scripts\\Activate.ps1

# 如果有离线包，优先使用
if (Test-Path ./_offline_deps) {
    pip install --no-index --find-links=./_offline_deps -r ./_offline_deps/requirements.txt
} else {
    # 在线安装
    pip install qwen-asr soundfile modelscope fastapi uvicorn huggingface_hub funasr
    pip install torch torchaudio   # 根据 GPU 情况选择 CPU 或 CUDA 版本
}

# 启动 WebUI
.\\run_webui.bat
\`\`\`

### 方式三：一键初始化（如果有网络）

\`\`\`powershell
.\\bootstrap.ps1
\`\`\`

## 目录说明

| 路径 | 说明 |
|------|------|
| \`models/\` | AI 模型文件（已包含，无需下载） |
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

- 首次运行时，\`outputs/\` 和 \`inputs/\` 目录会自动创建
- 如果有 NVIDIA GPU，确保安装了对应 CUDA 版本的 PyTorch
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
if ([string]::IsNullOrWhiteSpace($OutputZip)) {
    $OutputZip = Join-Path $env:TEMP "Qwen3-ASR_Package_$Timestamp.zip"
}

# 确保 .zip 后缀
if (-not $OutputZip.EndsWith(".zip", [System.StringComparison]::OrdinalIgnoreCase)) {
    $OutputZip = "$OutputZip.zip"
}

$OutputZip = [System.IO.Path]::GetFullPath($OutputZip)

Log "开始压缩为 ZIP：$OutputZip"
$CompressStart = Get-Date

# 使用 .NET 原生压缩（无需额外依赖）
Add-Type -AssemblyName System.IO.Compression.FileSystem

# 获取父目录名（Qwen3-ASR_Package_时间戳）作为 ZIP 内根文件夹
$ZipRootName = [System.IO.Path]::GetFileName($StagingDir)
[System.IO.Compression.ZipFile]::CreateFromDirectory($StagingDir, $OutputZip)

$CompressElapsed = ((Get-Date) - $CompressStart).TotalSeconds
$ZipSize = (Get-Item $OutputZip).Length

Log "压缩完成！"
Log "  ZIP 路径：$OutputZip"
Log "  ZIP 大小：$(Format-Size $ZipSize)"
Log "  压缩耗时：$([math]::Round($CompressElapsed, 1)) 秒"

# ============================================================
# 10. 清理临时打包目录（可选，默认保留以便调试）
# ============================================================
$question = Read-Host "是否删除临时打包目录 ($StagingDir)？(y/n)"
if ($question -eq "y") {
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
