@echo off
chcp 65001 >nul
REM Switch the console to UTF-8 before cmd.exe reads the Chinese messages below.
setlocal
cd /d "%~dp0"

set "ENTRY_SCRIPT=bootstrap.ps1"

if not exist "%ENTRY_SCRIPT%" (
  echo [fatal] 未找到 %ENTRY_SCRIPT%。请确认项目文件完整，并在项目根目录重新运行。
  pause
  exit /b 1
)

set "PS_EXE=%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe"
if not exist "%PS_EXE%" (
  set "PS_EXE=powershell"
  where powershell >nul 2>nul
  if errorlevel 1 (
    set "PS_EXE=pwsh"
    where pwsh >nul 2>nul
    if errorlevel 1 (
      echo [fatal] 未找到 powershell.exe、powershell 或 pwsh。请先安装 PowerShell，再重新启动初始化脚本。
      pause
      exit /b 1
    )
  )
)

echo [启动] %PS_EXE% -NoProfile -ExecutionPolicy Bypass -File %ENTRY_SCRIPT% %*
%PS_EXE% -NoProfile -ExecutionPolicy Bypass -File "%ENTRY_SCRIPT%" %*
set "EXIT_CODE=%ERRORLEVEL%"

if not "%EXIT_CODE%"=="0" (
  echo [错误] 初始化失败，退出码 %EXIT_CODE%。请先查看上方提示，再重试。
  pause
  exit /b %EXIT_CODE%
)

exit /b 0
