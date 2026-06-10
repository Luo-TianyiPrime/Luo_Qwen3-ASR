@echo off
setlocal EnableExtensions

REM ============================================================================
REM Qwen3-ASR WebUI 双击入口
REM ============================================================================
REM 这个 bat 文件只负责一件事：帮不熟悉 PowerShell 的用户双击启动 WebUI。
REM
REM 真正的启动流程在 start_webui.ps1 中，包括：
REM   - 检查 .venv 虚拟环境
REM   - 自动调用 bootstrap.ps1 安装缺失依赖
REM   - 检查 / 下载默认模型
REM   - 检查 ffmpeg / ffprobe
REM   - 处理端口占用
REM   - 启动 WebUI 服务
REM
REM 为什么不把所有逻辑写在 bat 里：
REM   - bat 适合做 Windows 双击入口，但复杂逻辑很难维护。
REM   - PowerShell 更适合写路径判断、命令调用、错误处理和中文提示。
REM   - 这样无论你双击 run_webui.bat，还是直接运行 .\start_webui.ps1，行为都是一致的。
REM ============================================================================

REM 使用 UTF-8 代码页，尽量避免中文提示乱码。
chcp 65001 >nul

REM 切换到本 bat 所在目录。
REM 双击 bat 时，系统给的当前目录不一定是项目根目录；这里强制切回来。
cd /d "%~dp0"

REM ENTRY_SCRIPT 是真正的 WebUI 总启动脚本。
set "ENTRY_SCRIPT=start_webui.ps1"

if not exist "%ENTRY_SCRIPT%" (
  echo [fatal] 未找到 %ENTRY_SCRIPT%。
  echo [说明] 项目文件可能不完整，或者你没有在项目根目录运行。
  echo [下一步] 请重新解压或重新拉取完整项目，然后再运行 run_webui.bat。
  pause
  exit /b 1
)

REM 优先使用系统自带 Windows PowerShell；如果找不到，再尝试 powershell.exe / pwsh.exe。
set "PS_EXE=%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe"
if not exist "%PS_EXE%" (
  set "PS_EXE="
  for /f "delims=" %%P in ('where powershell.exe 2^>nul') do (
    set "PS_EXE=%%P"
    goto :FoundPowerShell
  )
  for /f "delims=" %%P in ('where pwsh.exe 2^>nul') do (
    set "PS_EXE=%%P"
    goto :FoundPowerShell
  )
)

:FoundPowerShell
if not defined PS_EXE (
  echo [fatal] 未找到可用的 PowerShell。
  echo [说明] 本项目的启动脚本是 .ps1 文件，所以需要 PowerShell 执行。
  echo [下一步] 请安装 Windows PowerShell 或 PowerShell 7，然后重新运行。
  pause
  exit /b 1
)

echo [启动] %PS_EXE% -NoProfile -ExecutionPolicy Bypass -File %ENTRY_SCRIPT% %*
"%PS_EXE%" -NoProfile -ExecutionPolicy Bypass -File "%ENTRY_SCRIPT%" %*
set "EXIT_CODE=%ERRORLEVEL%"

if not "%EXIT_CODE%"=="0" (
  echo [错误] WebUI 启动失败，退出码 %EXIT_CODE%。
  echo [下一步] 请先查看上方提示；如果是端口占用，可以尝试：run_webui.bat -Port 8766
  pause
  exit /b %EXIT_CODE%
)

exit /b 0
