param(
    [string]$PythonExe = "python",
    [ValidateSet("auto", "cpu", "cu121", "cu124")]
    [string]$TorchVariant = "auto",
    [switch]$InstallFunASR,
    [switch]$DownloadModels,
    [switch]$DownloadAsrModel,
    [switch]$DownloadAlignerModel,
    [switch]$InstallFfmpegOnly,
    [switch]$SkipFfmpegInstall,
    [ValidateSet("hf", "modelscope")]
    [string]$ModelHub = "hf",
    [string]$AsrCkpt = "Qwen/Qwen3-ASR-1.7B",
    [string]$AlignerCkpt = "Qwen/Qwen3-ForcedAligner-0.6B"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ProjectRoot = $PSScriptRoot
$VenvPath = Join-Path $ProjectRoot ".venv"
$VenvPython = Join-Path $VenvPath "Scripts\python.exe"
$VenvPip = Join-Path $VenvPath "Scripts\pip.exe"
$ModelDownloadVenvPath = Join-Path $ProjectRoot ".cache\model_download_venv"
$ModelDownloadPython = Join-Path $ModelDownloadVenvPath "Scripts\python.exe"
$RequirementsPath = Join-Path $ProjectRoot "requirements.txt"
$ToolsRoot = Join-Path $ProjectRoot ".tools"
$FfmpegRoot = Join-Path $ToolsRoot "ffmpeg"
$FfmpegBin = Join-Path $FfmpegRoot "bin"
$DownloadCacheRoot = Join-Path $ProjectRoot ".cache\downloads"

# Windows 版 ffmpeg 的项目内自动安装源。
# 说明：
# - 这里使用 gyan.dev 提供的 release essentials 静态构建包，里面包含 ffmpeg.exe 和 ffprobe.exe。
# - “静态构建”可以理解为：运行所需的大部分组件已经一起打包好，不需要额外安装一堆 DLL。
# - 本脚本只把它解压到 .tools\ffmpeg，不写入系统目录，也不永久修改系统 PATH。
# - 如果以后你想换下载源，只需要改这个 URL；其它安装逻辑不需要动。
$FfmpegDownloadUrl = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"

if (Test-Path (Join-Path $ProjectRoot "env.ps1")) {
    . (Join-Path $ProjectRoot "env.ps1")
}

function Invoke-Step {
    param(
        [string]$Message,
        [scriptblock]$Script
    )
    Write-Host "[bootstrap] $Message"
    & $Script
}

function Get-PythonVersion {
    param([string]$Exe)

    try {
        $text = & $Exe -c "import sys; print('.'.join(map(str, sys.version_info[:3])))"
        if ($LASTEXITCODE -ne 0) {
            throw "python invoke failed"
        }
        return [version](($text | Select-Object -First 1).Trim())
    }
    catch {
        throw "未找到可用的 Python。请先安装 Python 3.10 或更高版本，并勾选 Add Python to PATH，然后重新运行 .\bootstrap.ps1。"
    }
}

function Write-BootstrapFailure {
    param([string]$Message)

    Write-Host "[bootstrap] 安装失败：$Message"
    switch -Regex ($Message) {
        'Python|python' {
            Write-Host "[bootstrap] 常见原因：电脑还没有安装 Python，或者 Python 没有加入 PATH。"
            Write-Host "[bootstrap] 下一步：先安装 Python 3.10+，勾选 Add Python to PATH，然后重新运行 .\bootstrap.ps1。"
        }
        'ffmpeg|ffprobe' {
            Write-Host "[bootstrap] 常见原因：ffmpeg 没装好，或者命令行找不到 ffmpeg / ffprobe。"
            Write-Host "[bootstrap] 下一步：先安装 ffmpeg，并确认命令行能直接运行 ffmpeg -version。"
        }
        'funasr' {
            Write-Host "[bootstrap] 常见原因：标点恢复依赖下载失败，或者网络中断。"
            Write-Host "[bootstrap] 下一步：确认网络后重新运行 .\bootstrap.ps1 -InstallFunASR。"
        }
        'huggingface_hub|modelscope|snapshot_download|model download' {
            Write-Host "[bootstrap] 常见原因：模型下载依赖未安装，或者网络不稳定。"
            Write-Host "[bootstrap] 下一步：确认网络后重试；如果你只想下载单个模型，可以用 .\bootstrap.ps1 -DownloadAsrModel 或 .\bootstrap.ps1 -DownloadAlignerModel。"
        }
        'requirements\.txt' {
            Write-Host "[bootstrap] 常见原因：项目文件不完整，缺少 requirements.txt。"
            Write-Host "[bootstrap] 下一步：重新解压或重新拉取完整项目后，再运行 .\bootstrap.ps1。"
        }
        'pip|wheel|setuptools' {
            Write-Host "[bootstrap] 常见原因：核心依赖下载失败，或者网络 / 镜像源不稳定。"
            Write-Host "[bootstrap] 下一步：重试一次；如果还失败，检查网络后再运行 .\bootstrap.ps1。"
        }
        default {
            Write-Host "[bootstrap] 下一步：先看上面最后几行报错。若是网络问题，重试通常就能恢复；若是 Python 相关问题，先确认 Python 3.10+ 可用。"
        }
    }
}

function Test-FfmpegCommands {
    # 同时检查 ffmpeg 和 ffprobe。
    # ffmpeg 负责转码、截取、导出音频；ffprobe 负责读取音频时长、编码等元信息。
    # 只找到其中一个都不算完整可用，因为后续音频处理链路两者都会用到。
    $ffmpeg = Get-Command ffmpeg -ErrorAction SilentlyContinue
    $ffprobe = Get-Command ffprobe -ErrorAction SilentlyContinue
    return [bool]($ffmpeg -and $ffprobe)
}

function Add-ProjectFfmpegToProcessPath {
    # 把项目内 ffmpeg 加入当前 PowerShell 进程的 PATH。
    # 注意：子进程无法反向修改父进程 PATH，所以 start_webui.ps1 调用本脚本安装完后，
    # 还会重新加载 env.ps1，让 WebUI 那个父进程也能立刻找到 ffmpeg。
    if (
        (Test-Path -LiteralPath (Join-Path $FfmpegBin "ffmpeg.exe") -PathType Leaf) -and
        (Test-Path -LiteralPath (Join-Path $FfmpegBin "ffprobe.exe") -PathType Leaf)
    ) {
        $pathItems = @($env:PATH -split ';' | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })
        if ($pathItems -notcontains $FfmpegBin) {
            $env:PATH = ($FfmpegBin + ";" + $env:PATH)
        }
    }
}

function Test-ProjectFfmpeg {
    return [bool](
        (Test-Path -LiteralPath (Join-Path $FfmpegBin "ffmpeg.exe") -PathType Leaf) -and
        (Test-Path -LiteralPath (Join-Path $FfmpegBin "ffprobe.exe") -PathType Leaf)
    )
}

function Assert-PathUnderProject {
    param([string]$Path)

    # 这是删除临时目录 / 旧工具目录前的安全检查。
    # 只有目标路径明确位于当前项目目录之内，才允许递归删除，避免路径变量异常时误删系统目录。
    $projectFull = [System.IO.Path]::GetFullPath($ProjectRoot).TrimEnd('\')
    $targetFull = [System.IO.Path]::GetFullPath($Path).TrimEnd('\')
    if (-not $targetFull.StartsWith($projectFull, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "安全检查失败：拒绝操作项目目录外的路径：$targetFull"
    }
}

function Test-FileSha256 {
    param(
        [string]$FilePath,
        [string]$ExpectedHash
    )

    if ([string]::IsNullOrWhiteSpace($ExpectedHash)) {
        return $true
    }

    $actual = (Get-FileHash -Algorithm SHA256 -LiteralPath $FilePath).Hash.ToLowerInvariant()
    return ($actual -eq $ExpectedHash.Trim().ToLowerInvariant())
}

function Get-RemoteSha256OrEmpty {
    param([string]$Sha256Url)

    try {
        # 有些下载站会提供 .sha256 文件。能拿到就校验，拿不到不阻断安装。
        # 原因是这里的主要目标是“新手一键跑通”；完整供应链安全还可以后续用固定版本+固定哈希进一步增强。
        $text = (Invoke-WebRequest -Uri $Sha256Url -UseBasicParsing -TimeoutSec 30).Content
        $match = [regex]::Match([string]$text, '(?i)[a-f0-9]{64}')
        if ($match.Success) {
            return $match.Value
        }
    }
    catch {
        Write-Warning "未能获取 ffmpeg SHA256 校验文件，将继续下载但跳过哈希校验。详情：$($_.Exception.Message)"
    }

    return ""
}

function Install-ProjectFfmpeg {
    # 项目内安装 ffmpeg 的完整流程：
    # 1. 如果系统或项目里已经能找到 ffmpeg/ffprobe，直接复用，不重复下载。
    # 2. 如果找不到，就下载 Windows 静态构建 zip。
    # 3. 解压到 .tools\ffmpeg。
    # 4. 把 .tools\ffmpeg\bin 加入当前进程 PATH，并做最终命令检查。
    Add-ProjectFfmpegToProcessPath

    if (Test-FfmpegCommands) {
        Write-Host "[bootstrap] ffmpeg / ffprobe 已可用，跳过自动安装。"
        return
    }

    if (Test-ProjectFfmpeg) {
        Add-ProjectFfmpegToProcessPath
        if (Test-FfmpegCommands) {
            Write-Host "[bootstrap] 已启用项目内 ffmpeg：$FfmpegBin"
            return
        }
    }

    Write-Host "[bootstrap] 当前找不到 ffmpeg / ffprobe，开始项目内自动安装。"
    Write-Host "[bootstrap] 安装位置：$FfmpegRoot"
    Write-Host "[bootstrap] 下载地址：$FfmpegDownloadUrl"

    New-Item -ItemType Directory -Force -Path $ToolsRoot, $DownloadCacheRoot | Out-Null

    $zipPath = Join-Path $DownloadCacheRoot "ffmpeg-release-essentials.zip"
    $extractRoot = Join-Path $DownloadCacheRoot "ffmpeg_extract"

    if (Test-Path -LiteralPath $extractRoot) {
        Assert-PathUnderProject -Path $extractRoot
        Remove-Item -LiteralPath $extractRoot -Recurse -Force
    }

    $expectedHash = Get-RemoteSha256OrEmpty -Sha256Url ($FfmpegDownloadUrl + ".sha256")

    $shouldDownload = $true
    if (Test-Path -LiteralPath $zipPath -PathType Leaf) {
        if (Test-FileSha256 -FilePath $zipPath -ExpectedHash $expectedHash) {
            Write-Host "[bootstrap] 复用已下载的 ffmpeg 压缩包：$zipPath"
            $shouldDownload = $false
        }
        else {
            Write-Warning "本地 ffmpeg 压缩包哈希不匹配，将重新下载。"
            Remove-Item -LiteralPath $zipPath -Force
        }
    }

    if ($shouldDownload) {
        # PowerShell 5.1 在部分老系统上默认 TLS 设置偏旧，这里显式启用 TLS 1.2，减少 HTTPS 下载失败概率。
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        Invoke-WebRequest -Uri $FfmpegDownloadUrl -OutFile $zipPath -UseBasicParsing
        if (-not (Test-FileSha256 -FilePath $zipPath -ExpectedHash $expectedHash)) {
            throw "ffmpeg 压缩包 SHA256 校验失败。请删除 $zipPath 后重试，或检查网络代理是否篡改下载内容。"
        }
    }

    New-Item -ItemType Directory -Force -Path $extractRoot | Out-Null
    Expand-Archive -LiteralPath $zipPath -DestinationPath $extractRoot -Force

    $ffmpegExe = Get-ChildItem -Path $extractRoot -Recurse -Filter "ffmpeg.exe" -File |
        Where-Object { $_.DirectoryName -like "*\bin" } |
        Select-Object -First 1
    if (-not $ffmpegExe) {
        throw "ffmpeg 压缩包解压后没有找到 bin\ffmpeg.exe，下载包结构可能已变化。"
    }

    $sourceBin = $ffmpegExe.Directory.FullName
    $sourceRoot = Split-Path -Parent $sourceBin
    if (-not (Test-Path -LiteralPath (Join-Path $sourceBin "ffprobe.exe") -PathType Leaf)) {
        throw "ffmpeg 压缩包里没有找到 bin\ffprobe.exe，无法满足音频探测需求。"
    }

    if (Test-Path -LiteralPath $FfmpegRoot) {
        Assert-PathUnderProject -Path $FfmpegRoot
        Remove-Item -LiteralPath $FfmpegRoot -Recurse -Force
    }
    New-Item -ItemType Directory -Force -Path $FfmpegRoot | Out-Null
    Copy-Item -Path (Join-Path $sourceRoot "*") -Destination $FfmpegRoot -Recurse -Force

    Add-ProjectFfmpegToProcessPath
    if (-not (Test-FfmpegCommands)) {
        throw "ffmpeg 已解压，但当前进程仍找不到 ffmpeg / ffprobe。请检查项目路径和权限。"
    }

    Write-Host "[bootstrap] ffmpeg 自动安装完成：$FfmpegBin"
}

function Invoke-FfmpegOnlyMode {
    param([switch]$InstallFfmpegOnly)

    if (-not $InstallFfmpegOnly) {
        return $false
    }

    Write-Host "[bootstrap] 进入 ffmpeg 安装模式：只安装 / 修复项目内 ffmpeg，不安装 Python 依赖。"
    Install-ProjectFfmpeg
    Write-Host "[bootstrap] 完成。"
    return $true
}

function Install-Torch {
    param(
        [string]$PipExe,
        [string]$Variant
    )

    $resolved = $Variant
    if ($resolved -eq "auto") {
        if (Get-Command nvidia-smi -ErrorAction SilentlyContinue) {
            $resolved = "cu124"
        }
        else {
            $resolved = "cpu"
        }
    }

    Write-Host "[bootstrap] 正在安装 PyTorch / torchaudio，目标版本：$resolved"
    try {
        switch ($resolved) {
            "cpu" {
                & $PipExe install -U torch torchaudio --index-url https://download.pytorch.org/whl/cpu
            }
            "cu121" {
                & $PipExe install -U torch torchaudio --index-url https://download.pytorch.org/whl/cu121
            }
            "cu124" {
                & $PipExe install -U torch torchaudio --index-url https://download.pytorch.org/whl/cu124
            }
        }
    }
    catch {
        Write-Warning "安装指定 PyTorch 版本失败，改用默认源重试。错误：$($_.Exception.Message)"
        & $PipExe install -U torch torchaudio
    }
}

function Download-HFModel {
    param(
        [string]$PythonPath,
        [string]$RepoId,
        [string]$LocalDir
    )

    $script = @"
from huggingface_hub import snapshot_download
snapshot_download(repo_id=r'''$RepoId''', local_dir=r'''$LocalDir''')
print('download_ok')
"@
    & $PythonPath -c $script
}

function Download-ModelScopeModel {
    param(
        [string]$PythonPath,
        [string]$ModelId,
        [string]$LocalDir
    )

    $script = @"
from modelscope import snapshot_download
snapshot_download(model_id=r'''$ModelId''', cache_dir=r'''$LocalDir''')
print('download_ok')
"@
    & $PythonPath -c $script
}

function Ensure-ModelDownloadPython {
    param([string]$Hub)

    if (-not (Test-Path -LiteralPath $ModelDownloadPython)) {
        New-Item -ItemType Directory -Force -Path (Join-Path $ProjectRoot ".cache") | Out-Null
        Write-Host "[bootstrap] 创建轻量模型下载环境：$ModelDownloadVenvPath"
        & $PythonExe -m venv $ModelDownloadVenvPath
    }

    Write-Host "[bootstrap] 准备模型下载依赖：$Hub"
    & $ModelDownloadPython -m pip install -U pip setuptools wheel
    switch ($Hub) {
        "hf" {
            & $ModelDownloadPython -m pip install huggingface_hub
        }
        "modelscope" {
            & $ModelDownloadPython -m pip install modelscope
        }
    }
    return $ModelDownloadPython
}

function Invoke-ModelDownloadTargets {
    param(
        [string]$DownloaderPython,
        [bool]$DownloadAsr,
        [bool]$DownloadAligner,
        [string]$Hub
    )

    $asrLocal = Join-Path $ProjectRoot "models\Qwen3-ASR-1.7B"
    $alignLocal = Join-Path $ProjectRoot "models\Qwen3-ForcedAligner-0.6B"
    New-Item -ItemType Directory -Force -Path (Join-Path $ProjectRoot "models") | Out-Null

    if ($DownloadAsr) {
        New-Item -ItemType Directory -Force -Path $asrLocal | Out-Null
        if ($Hub -eq "hf") {
            Download-HFModel -PythonPath $DownloaderPython -RepoId $AsrCkpt -LocalDir $asrLocal
        }
        else {
            Download-ModelScopeModel -PythonPath $DownloaderPython -ModelId $AsrCkpt -LocalDir $asrLocal
        }
        Write-Host "[bootstrap] ASR 模型已下载：$asrLocal"
    }

    if ($DownloadAligner) {
        New-Item -ItemType Directory -Force -Path $alignLocal | Out-Null
        if ($Hub -eq "hf") {
            Download-HFModel -PythonPath $DownloaderPython -RepoId $AlignerCkpt -LocalDir $alignLocal
        }
        else {
            Download-ModelScopeModel -PythonPath $DownloaderPython -ModelId $AlignerCkpt -LocalDir $alignLocal
        }
        Write-Host "[bootstrap] 对齐模型已下载：$alignLocal"
    }
}

function Invoke-ModelDownloadMode {
    param(
        [switch]$DownloadModels,
        [switch]$DownloadAsrModel,
        [switch]$DownloadAlignerModel,
        [string]$Hub
    )

    $downloadAsr = [bool]($DownloadModels -or $DownloadAsrModel)
    $downloadAligner = [bool]($DownloadModels -or $DownloadAlignerModel)

    if (-not $downloadAsr -and -not $downloadAligner) {
        return $false
    }

    Write-Host "[bootstrap] 进入模型下载模式：只下载模型，不执行完整 bootstrap。"
    Write-Host "[bootstrap] 下载目标：ASR=$downloadAsr，对齐=$downloadAligner，Hub=$Hub"

    Invoke-Step "检查 Python 3.10+：$PythonExe" {
        $pythonVersion = Get-PythonVersion -Exe $PythonExe
        if ($pythonVersion -lt [version]"3.10.0") {
            throw "当前 Python 版本过低：$pythonVersion。请先安装 Python 3.10 或更高版本，并勾选 Add Python to PATH。"
        }
        Write-Host "[bootstrap] 已检测到 Python $pythonVersion"
    }

    $downloaderPython = Ensure-ModelDownloadPython -Hub $Hub
    Invoke-Step "下载模型（仅本步骤，不执行完整 bootstrap）" {
        Invoke-ModelDownloadTargets -DownloaderPython $downloaderPython -DownloadAsr:$downloadAsr -DownloadAligner:$downloadAligner -Hub $Hub
    }

    Write-Host "[bootstrap] 完成。"
    Write-Host "[bootstrap] 下一步：如果你还没装好虚拟环境，运行 .\bootstrap.ps1；如果你只想跑任务，直接试 .\run.ps1 或 .\start_webui.ps1"
    return $true
}

try {
    if (Invoke-FfmpegOnlyMode -InstallFfmpegOnly:$InstallFfmpegOnly) {
        exit 0
    }

    if (Invoke-ModelDownloadMode -DownloadModels:$DownloadModels -DownloadAsrModel:$DownloadAsrModel -DownloadAlignerModel:$DownloadAlignerModel -Hub $ModelHub) {
        exit 0
    }

    Write-Host "[bootstrap] 首次安装可能会比较久，因为要下载 PyTorch 和核心依赖。"

    if (-not $SkipFfmpegInstall) {
        Invoke-Step "检查 / 自动安装 ffmpeg" {
            Install-ProjectFfmpeg
        }
    }
    else {
        Write-Host "[bootstrap] 已收到 -SkipFfmpegInstall，跳过 ffmpeg 自动安装。"
    }

    Invoke-Step "检查 Python 3.10+：$PythonExe" {
        $pythonVersion = Get-PythonVersion -Exe $PythonExe
        if ($pythonVersion -lt [version]"3.10.0") {
            throw "当前 Python 版本过低：$pythonVersion。请先安装 Python 3.10 或更高版本，并勾选 Add Python to PATH。"
        }
        Write-Host "[bootstrap] 已检测到 Python $pythonVersion"
    }

    Invoke-Step "创建或复用虚拟环境：$VenvPath" {
        if (-not (Test-Path -LiteralPath $VenvPython)) {
            & $PythonExe -m venv $VenvPath
        }
    }

    Invoke-Step "升级 pip / setuptools / wheel" {
        & $VenvPython -m pip install -U pip setuptools wheel
    }

    Invoke-Step "安装 PyTorch" {
        Install-Torch -PipExe $VenvPip -Variant $TorchVariant
    }

    Invoke-Step "安装项目核心依赖" {
        if (-not (Test-Path -LiteralPath $RequirementsPath -PathType Leaf)) {
            throw "未找到 requirements.txt：$RequirementsPath"
        }
        & $VenvPip install -r $RequirementsPath
        Write-Host "[bootstrap] FunASR 已作为项目依赖安装，用于默认的标点恢复。"
        if ($InstallFunASR) {
            Write-Host "[bootstrap] 已收到 -InstallFunASR，额外执行一次 FunASR 升级/修复安装，适合旧环境补依赖。"
            & $VenvPip install -U funasr
        }
    }

    if ($DownloadModels) {
        Write-Host "[bootstrap] 正在下载 ASR 模型和对齐模型到本地 models/ 目录。首次下载可能需要较久。"
        $asrLocal = Join-Path $ProjectRoot "models\Qwen3-ASR-1.7B"
        $alignLocal = Join-Path $ProjectRoot "models\Qwen3-ForcedAligner-0.6B"
        New-Item -ItemType Directory -Force -Path $asrLocal, $alignLocal | Out-Null

        try {
            if ($ModelHub -eq "hf") {
                Download-HFModel -PythonPath $VenvPython -RepoId $AsrCkpt -LocalDir $asrLocal
                Download-HFModel -PythonPath $VenvPython -RepoId $AlignerCkpt -LocalDir $alignLocal
            }
            else {
                Download-ModelScopeModel -PythonPath $VenvPython -ModelId $AsrCkpt -LocalDir $asrLocal
                Download-ModelScopeModel -PythonPath $VenvPython -ModelId $AlignerCkpt -LocalDir $alignLocal
            }
            Write-Host "[bootstrap] 模型下载完成。"
        }
        catch {
            Write-Warning "模型下载失败：$($_.Exception.Message)"
            Write-Warning "你可以手动把模型放到："
            Write-Warning "  $asrLocal"
            Write-Warning "  $alignLocal"
            Write-Warning "然后再把 `--asr_ckpt` / `--aligner_ckpt` 指向这些本地目录。"
            throw
        }
    }

    if (Test-Path -LiteralPath (Join-Path $ProjectRoot "scripts\self_check.py")) {
        Invoke-Step "运行环境自检" {
            & $VenvPython (Join-Path $ProjectRoot "scripts\self_check.py")
        }
    }
    else {
        Write-Host "[bootstrap] 跳过环境自检：scripts\self_check.py 不存在。"
    }

    Write-Host "[bootstrap] 完成。"
    Write-Host "[bootstrap] 下一步：把音频放进 .\inputs 后，直接试跑 .\run.ps1；或者直接启动 WebUI：.\start_webui.ps1"
    Write-Host "[bootstrap] 标点恢复默认开启；如果旧环境仍提示缺少 funasr，可重新运行 .\bootstrap.ps1 -InstallFunASR 修复。"
}
catch {
    Write-BootstrapFailure -Message $_.Exception.Message
    exit 1
}
