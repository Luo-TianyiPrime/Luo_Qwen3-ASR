#!/usr/bin/env python
"""
环境自检脚本：
1) Python 版本与 venv
2) ffmpeg
3) torch / CUDA / GPU
4) 关键依赖导入
"""

from __future__ import annotations

import importlib
import platform
import subprocess
import sys


def line(name: str, ok: bool, detail: str) -> None:
    flag = "OK" if ok else "FAIL"
    print(f"[{flag}] {name}: {detail}")


def check_python() -> bool:
    ver = sys.version.split()[0]
    ok = sys.version_info >= (3, 10)
    detail = f"{ver}"
    if ok:
        detail += " (已满足 >= 3.10)"
    else:
        detail += " (需要先升级到 3.10 或更高版本，再运行 bootstrap.ps1)"
    line("Python", ok, detail)
    return ok


def check_venv() -> bool:
    in_venv = getattr(sys, "base_prefix", sys.prefix) != sys.prefix
    detail = sys.prefix
    if not in_venv:
        detail += " (当前不是虚拟环境；请先运行 .\\bootstrap.ps1)"
    line("VirtualEnv", in_venv, detail)
    return in_venv


def check_ffmpeg() -> bool:
    try:
        proc = subprocess.run(
            ["ffmpeg", "-version"],
            capture_output=True,
            text=True,
            check=True,
            # 自检不处理音频，正常只需瞬间打印版本；设置超时可避免损坏的 ffmpeg 进程让安装永久卡住。
            timeout=10,
        )
        first = proc.stdout.splitlines()[0] if proc.stdout else "ffmpeg found"
        line("ffmpeg", True, first)
        return True
    except Exception as exc:
        line(
            "ffmpeg",
            False,
            f"未找到或无法运行 ffmpeg。请先安装 ffmpeg，并确认命令行能直接执行 ffmpeg -version。详情：{exc}",
        )
        return False


def check_import(module_name: str, required: bool = True) -> tuple[bool, str]:
    try:
        importlib.import_module(module_name)
        return True, "import ok"
    except Exception as exc:
        if required:
            if module_name == "qwen_asr":
                return False, f"核心包 qwen_asr 未安装或导入失败。请先运行 .\\bootstrap.ps1。详情：{exc}"
            if module_name == "funasr":
                return (
                    False,
                    f"标点恢复依赖 funasr 未安装或导入失败。请先运行 .\\bootstrap.ps1 -InstallFunASR。详情：{exc}",
                )
            return False, str(exc)
        if module_name == "funasr":
            return True, "未安装 funasr（只有你手动关闭标点恢复时才可忽略；默认带标点输出需要它）"
        if module_name == "modelscope":
            return True, "未安装 modelscope（可忽略；如果你使用 ModelScope 路线，再补装即可）"
        return True, f"optional missing: {exc}"


def check_torch() -> bool:
    try:
        import torch

        cuda = torch.cuda.is_available()
        if cuda:
            name = torch.cuda.get_device_name(0)
            detail = f"torch={torch.__version__}, cuda=True, gpu={name}"
        else:
            detail = f"torch={torch.__version__}, cuda=False"
        line("torch", True, detail)
        return True
    except Exception as exc:
        line("torch", False, f"torch 导入失败。请先运行 .\\bootstrap.ps1。详情：{exc}")
        return False


def main() -> int:
    print(f"[info] OS: {platform.platform()}")
    print(f"[info] Executable: {sys.executable}")
    print(f"[info] Prefix: {sys.prefix}")
    print("")

    checks = []
    checks.append(check_python())
    checks.append(check_venv())
    checks.append(check_ffmpeg())
    checks.append(check_torch())

    deps = [
        ("numpy", True),
        ("soundfile", True),
        ("qwen_asr", True),
        ("funasr", True),
        ("modelscope", False),
    ]
    for mod, required in deps:
        ok, detail = check_import(mod, required=required)
        line(f"import {mod}", ok, detail)
        checks.append(ok)

    all_ok = all(checks)
    print("")
    if all_ok:
        print("[self_check] 通过：环境可运行。")
        return 0
    print("[self_check] 未通过：请先修复 FAIL 项。")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
