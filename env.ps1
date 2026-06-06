Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# 项目根目录（固定为当前脚本所在目录）
$ProjectRoot = $PSScriptRoot
$CacheRoot = Join-Path $ProjectRoot ".cache"

# 统一创建本项目内的缓存/输入/输出目录
$Dirs = @(
    $CacheRoot,
    (Join-Path $CacheRoot "hf"),
    (Join-Path $CacheRoot "hf\hub"),
    (Join-Path $CacheRoot "transformers"),
    (Join-Path $CacheRoot "torch"),
    (Join-Path $CacheRoot "modelscope"),
    (Join-Path $CacheRoot "xdg"),
    (Join-Path $CacheRoot "pip"),
    (Join-Path $CacheRoot "tmp"),
    (Join-Path $CacheRoot "qwen_asr"),
    (Join-Path $ProjectRoot "models"),
    (Join-Path $ProjectRoot "outputs"),
    (Join-Path $ProjectRoot "inputs")
)

foreach ($Dir in $Dirs) {
    New-Item -ItemType Directory -Force -Path $Dir | Out-Null
}

# 常用缓存环境变量全部指向项目目录
$env:HF_HOME = Join-Path $CacheRoot "hf"
$env:HUGGINGFACE_HUB_CACHE = Join-Path $CacheRoot "hf\hub"
$env:TRANSFORMERS_CACHE = Join-Path $CacheRoot "transformers"
$env:TORCH_HOME = Join-Path $CacheRoot "torch"
$env:MODELSCOPE_CACHE = Join-Path $CacheRoot "modelscope"
$env:XDG_CACHE_HOME = Join-Path $CacheRoot "xdg"
$env:PIP_CACHE_DIR = Join-Path $CacheRoot "pip"
$env:TEMP = Join-Path $CacheRoot "tmp"
$env:TMP = Join-Path $CacheRoot "tmp"
$env:QWEN_ASR_CACHE = Join-Path $CacheRoot "qwen_asr"

# 部分工具会读取这些变量，统一到项目目录
$env:HF_HUB_DISABLE_SYMLINKS_WARNING = "1"
$env:PYTHONUTF8 = "1"

Write-Host "[env] 已设置项目内缓存目录：$CacheRoot"

