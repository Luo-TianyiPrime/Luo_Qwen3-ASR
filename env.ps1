Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# 项目根目录（固定为当前脚本所在目录）
$ProjectRoot = $PSScriptRoot
$CacheRoot = Join-Path $ProjectRoot ".cache"
$ToolsRoot = Join-Path $ProjectRoot ".tools"
$FfmpegRoot = Join-Path $ToolsRoot "ffmpeg"
$FfmpegBin = Join-Path $FfmpegRoot "bin"

# 统一创建本项目内的缓存/输入/输出目录
$Dirs = @(
    $CacheRoot,
    (Join-Path $CacheRoot "hf"),
    (Join-Path $CacheRoot "hf\hub"),
    (Join-Path $CacheRoot "torch"),
    (Join-Path $CacheRoot "modelscope"),
    (Join-Path $CacheRoot "xdg"),
    (Join-Path $CacheRoot "pip"),
    (Join-Path $CacheRoot "tmp"),
    (Join-Path $CacheRoot "qwen_asr"),
    $ToolsRoot,
    (Join-Path $ProjectRoot "models"),
    (Join-Path $ProjectRoot "outputs"),
    (Join-Path $ProjectRoot "inputs")
)

foreach ($Dir in $Dirs) {
    New-Item -ItemType Directory -Force -Path $Dir | Out-Null
}

# 常用缓存环境变量全部指向项目目录。
# HF_HOME 是 Hugging Face 现在推荐的总缓存根目录，HUGGINGFACE_HUB_CACHE 进一步指定模型快照位置。
# 旧的 TRANSFORMERS_CACHE 已被 Transformers 标记为弃用并计划在 v5 移除，所以这里不再设置它；
# 如果父 PowerShell 以前设置过该变量，也主动清除，避免每次运行都出现弃用警告。
$env:HF_HOME = Join-Path $CacheRoot "hf"
$env:HUGGINGFACE_HUB_CACHE = Join-Path $CacheRoot "hf\hub"
Remove-Item Env:TRANSFORMERS_CACHE -ErrorAction SilentlyContinue
$env:TORCH_HOME = Join-Path $CacheRoot "torch"
$env:MODELSCOPE_CACHE = Join-Path $CacheRoot "modelscope"
$env:XDG_CACHE_HOME = Join-Path $CacheRoot "xdg"
$env:PIP_CACHE_DIR = Join-Path $CacheRoot "pip"
$env:TEMP = Join-Path $CacheRoot "tmp"
$env:TMP = Join-Path $CacheRoot "tmp"
$env:QWEN_ASR_CACHE = Join-Path $CacheRoot "qwen_asr"

# 如果本项目已经自动安装过 ffmpeg，就把它的 bin 目录加入“当前进程”的 PATH。
# 这里故意不改 Windows 系统全局 PATH，原因有三个：
# 1. 不需要管理员权限，新设备上双击脚本也能生效。
# 2. 不污染其它项目，避免别的软件误用本项目内的 ffmpeg。
# 3. Git clone 到不同目录后，路径会自动跟着项目根目录变化，更适合可迁移部署。
#
# PATH 可以理解为“系统查找命令的位置清单”。当脚本运行 ffmpeg 时，Windows 会按 PATH
# 从前往后找 ffmpeg.exe。把项目内 ffmpeg 放在前面，表示本项目优先使用自己的工具版本。
# 多行 if 条件在 Windows PowerShell 5.1 下可能触发解析错误，
# 这里用单行条件 + 逗号换行（数组风格），避免跨行 if 条件块的语法歧义。
$ffmpegExe = Join-Path $FfmpegBin "ffmpeg.exe"
$ffprobeExe = Join-Path $FfmpegBin "ffprobe.exe"
if ((Test-Path -LiteralPath $ffmpegExe -PathType Leaf) -and (Test-Path -LiteralPath $ffprobeExe -PathType Leaf)) {
    $pathItems = @($env:PATH -split ';' | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })
    if ($pathItems -notcontains $FfmpegBin) {
        $env:PATH = ($FfmpegBin + ";" + $env:PATH)
        Write-Host "[env] 已启用项目内 ffmpeg：$FfmpegBin"
    }
}

# 部分工具会读取这些变量，统一到项目目录
$env:HF_HUB_DISABLE_SYMLINKS_WARNING = "1"
$env:PYTHONUTF8 = "1"

Write-Host "[env] 已设置项目内缓存目录：$CacheRoot"
