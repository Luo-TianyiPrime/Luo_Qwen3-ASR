"""WebUI 前后端契约与后台稳定性回归测试。

这些测试使用临时运行目录，不读取或修改用户真实的 `.cache/webui` 任务历史与偏好。
"""

from __future__ import annotations

import json
import os
import queue
import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def webui_modules(tmp_path_factory):
    """在导入全局 manager 前切换运行目录，隔离 jobs.json 和后台日志。"""
    runtime_root = tmp_path_factory.mktemp("webui-runtime")
    old_value = os.environ.get("QWEN3_ASR_WEBUI_RUNTIME_ROOT")
    os.environ["QWEN3_ASR_WEBUI_RUNTIME_ROOT"] = str(runtime_root)

    from webui import app as app_module
    from webui import service as service_module

    yield app_module, service_module

    if old_value is None:
        os.environ.pop("QWEN3_ASR_WEBUI_RUNTIME_ROOT", None)
    else:
        os.environ["QWEN3_ASR_WEBUI_RUNTIME_ROOT"] = old_value


def test_runtime_fields_are_not_silently_dropped(webui_modules):
    app_module, service_module = webui_modules
    expected = {
        "max_new_tokens": 2048,
        "chunk_seconds": 30.0,
        "min_cuda_free_gb": 8.5,
        "force_cpu": True,
    }

    job = app_module.AsrJobPayload(
        audio=r".\inputs",
        asr_ckpt=r".\models\Qwen3-ASR-1.7B",
        aligner_ckpt=r".\models\Qwen3-ForcedAligner-0.6B",
        **expected,
    )
    preferences = app_module.PreferencesPayload(**expected)

    for key, value in expected.items():
        assert job.model_dump()[key] == value
        assert preferences.model_dump()[key] == value

    command = service_module.manager._build_asr_command(
        {**service_module.manager.get_base_defaults(), **job.model_dump()},
        service_module.RUNTIME_ROOT / "command-test-output",
    )
    command_text = "\n".join(command)
    assert "-MaxNewTokens\n2048" in command_text
    assert "-ChunkSeconds\n30.0" in command_text
    assert "-MinCudaFreeGB\n8.5" in command_text
    assert "-ForceCpu" in command


def test_open_system_path_accepts_frontend_json_contract(webui_modules, monkeypatch):
    app_module, _ = webui_modules
    opened: list[str] = []
    monkeypatch.setattr(app_module.manager, "open_path_in_explorer", opened.append)

    with TestClient(app_module.app) as client:
        response = client.post("/api/system/open", json={"target": "inputs"})

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert opened and Path(opened[0]).name == "inputs"


def test_atomic_json_write_retries_windows_sharing_violation(webui_modules, monkeypatch, tmp_path):
    _, service_module = webui_modules
    target = tmp_path / "jobs.json"
    original_replace = Path.replace
    attempts = 0

    def flaky_replace(source: Path, destination: Path):
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise PermissionError("simulated Windows file sharing violation")
        return original_replace(source, destination)

    monkeypatch.setattr(Path, "replace", flaky_replace)
    service_module.write_json_file(target, {"status": "ok"})

    assert attempts == 3
    assert json.loads(target.read_text(encoding="utf-8")) == {"status": "ok"}


def test_saved_webui_config_keeps_chinese_guide(webui_modules, monkeypatch, tmp_path):
    _, service_module = webui_modules
    monkeypatch.setattr(service_module, "CONFIG_ROOT", tmp_path)

    service_module.manager.save_config_file("portable.json", {"audio": r".\inputs"})
    payload = json.loads((tmp_path / "portable.json").read_text(encoding="utf-8"))

    assert payload["audio"] == r".\inputs"
    assert "fields" in payload["_guide"]
    assert "min_cuda_free_gb" in payload["_guide"]["fields"]


def test_worker_continues_after_one_unhandled_job_error(webui_modules):
    _, service_module = webui_modules
    test_manager = object.__new__(service_module.JobManager)
    test_manager._queue = queue.Queue()
    processed: list[str] = []
    recorded: list[tuple[str, str]] = []

    def fake_run(job_id: str) -> None:
        processed.append(job_id)
        if job_id == "broken":
            raise RuntimeError("simulated failure before normal job cleanup")

    test_manager._run_job = fake_run
    test_manager._record_unhandled_worker_error = lambda job_id, exc: recorded.append((job_id, str(exc)))
    worker = threading.Thread(target=test_manager._worker_loop, daemon=True)
    worker.start()
    test_manager._queue.put("broken")
    test_manager._queue.put("healthy")

    deadline = time.monotonic() + 2
    while test_manager._queue.unfinished_tasks and time.monotonic() < deadline:
        time.sleep(0.01)

    assert test_manager._queue.unfinished_tasks == 0
    assert processed == ["broken", "healthy"]
    assert recorded == [("broken", "simulated failure before normal job cleanup")]
