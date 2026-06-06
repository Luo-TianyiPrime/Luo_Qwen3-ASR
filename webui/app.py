from __future__ import annotations

from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .service import PROJECT_ROOT, guess_media_type, manager, resolve_project_path


STATIC_ROOT = Path(__file__).resolve().parent / "static"


class PreferencesPayload(BaseModel):
    audio: str | None = None
    output_mode: Literal["auto", "custom"] | None = None
    output_dir: str | None = None
    dataset_format: Literal["standard", "qwen3_tts"] | None = None
    ref_audio: str | None = None
    hotword_library: str | None = None
    hotword_text: str | None = None
    asr_ckpt: str | None = None
    aligner_ckpt: str | None = None
    language: str | None = None
    punc_model: str | None = None
    pause_threshold: float | None = None
    min_dur: float | None = None
    max_dur: float | None = None
    pad_left: float | None = None
    pad_right: float | None = None
    batch_size: int | None = None
    eta_rtf: float | None = None
    long_audio_warning_minutes: int | None = None
    scan_subfolders: bool | None = None


class AsrJobPayload(BaseModel):
    title: str = Field(default="")
    audio: str
    output_mode: Literal["auto", "custom"] = "auto"
    output_dir: str = ""
    dataset_format: Literal["standard", "qwen3_tts"] = "standard"
    ref_audio: str = ""
    hotword_library: str = ""
    hotword_text: str = ""
    asr_ckpt: str
    aligner_ckpt: str
    language: str = "None"
    # 标点恢复模型：这是识别后的文本后处理模型，用来补逗号、句号、问号；不是负责听音频的 ASR 主模型。
    punc_model: str = "iic/punc_ct-transformer_cn-en-common-vocab471067-large"
    pause_threshold: float = 0.60
    min_dur: float = 0.80
    max_dur: float = 8.00
    pad_left: float = 0.05
    pad_right: float = 0.10
    batch_size: int = 1
    eta_rtf: float = 2.0
    long_audio_warning_minutes: int = 120
    scan_subfolders: bool = False


class ExportQwen3TtsPayload(BaseModel):
    ref_audio: str | None = None
    output_dir: str | None = None


class OpenPathPayload(BaseModel):
    path: str


class ConfigFileLoadPayload(BaseModel):
    name: str


class ConfigFileSavePayload(BaseModel):
    name: str
    config: dict[str, object] = Field(default_factory=dict)
    set_as_default: bool = False


class ConfigFileRenamePayload(BaseModel):
    name: str
    new_name: str


class HotwordLibraryLoadPayload(BaseModel):
    name: str


class HotwordLibrarySavePayload(BaseModel):
    name: str
    content: str = ""


app = FastAPI(
    title="Qwen3-ASR 本地识别入口",
    description="用于本地任务执行、任务历史和结果管理的单机 Web 工具。",
    version="1.0.0",
)

app.mount("/static", StaticFiles(directory=str(STATIC_ROOT)), name="static")


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_ROOT / "index.html")


@app.get("/favicon.ico")
def favicon() -> FileResponse:
    return FileResponse(STATIC_ROOT / "favicon.svg", media_type="image/svg+xml")


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/meta")
def meta() -> dict[str, object]:
    return {
        "project_root": str(PROJECT_ROOT.resolve()),
        "environment": manager.get_environment_snapshot(),
        "defaults": manager.get_defaults(),
        "preferences": manager.get_preferences(),
        "config_files": manager.list_config_files(),
        "default_config_name": manager.get_default_config_name(),
        "hotword_libraries": manager.list_hotword_libraries(),
    }


@app.get("/api/preferences")
def get_preferences() -> dict[str, object]:
    return {"preferences": manager.get_preferences()}


@app.put("/api/preferences")
def put_preferences(payload: PreferencesPayload) -> dict[str, object]:
    data = payload.model_dump(exclude_none=True)
    return {"preferences": manager.save_preferences(data)}


@app.get("/api/config-files")
def list_config_files() -> dict[str, object]:
    return {
        "configs": manager.list_config_files(),
        "default_config_name": manager.get_default_config_name(),
    }


@app.post("/api/config-files/load")
def load_config_file(payload: ConfigFileLoadPayload) -> dict[str, object]:
    try:
        config = manager.load_config_file(payload.name)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"config_file": config}


@app.post("/api/config-files/save")
def save_config_file(payload: ConfigFileSavePayload) -> dict[str, object]:
    try:
        config = manager.save_config_file(
            name=payload.name,
            payload=payload.config,
            set_as_default=payload.set_as_default,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"config_file": config, "default_config_name": manager.get_default_config_name()}


@app.post("/api/config-files/set-default")
def set_default_config_file(payload: ConfigFileLoadPayload) -> dict[str, object]:
    try:
        data = manager.set_default_config_file(payload.name)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return data


@app.post("/api/config-files/rename")
def rename_config_file(payload: ConfigFileRenamePayload) -> dict[str, object]:
    try:
        data = manager.rename_config_file(name=payload.name, new_name=payload.new_name)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return data


@app.post("/api/config-files/delete")
def delete_config_file(payload: ConfigFileLoadPayload) -> dict[str, object]:
    try:
        data = manager.delete_config_file(payload.name)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return data


@app.get("/api/hotwords")
def list_hotword_libraries() -> dict[str, object]:
    return {"libraries": manager.list_hotword_libraries()}


@app.post("/api/hotwords/load")
def load_hotword_library(payload: HotwordLibraryLoadPayload) -> dict[str, object]:
    try:
        library = manager.load_hotword_library(payload.name)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"library": library}


@app.post("/api/hotwords/save")
def save_hotword_library(payload: HotwordLibrarySavePayload) -> dict[str, object]:
    try:
        library = manager.save_hotword_library(payload.name, payload.content)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"library": library}


@app.get("/api/jobs")
def list_jobs() -> dict[str, object]:
    return {"jobs": manager.list_jobs()}


@app.post("/api/jobs/asr")
def create_asr_job(payload: AsrJobPayload) -> dict[str, object]:
    data = payload.model_dump()
    try:
        job = manager.create_asr_job(data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"job": job}


@app.post("/api/jobs/actions/{kind}")
def create_action_job(kind: Literal["bootstrap", "download_models", "bootstrap_funasr", "self_check"]) -> dict[str, object]:
    try:
        job = manager.create_maintenance_job(kind)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"job": job}


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str) -> dict[str, object]:
    try:
        job = manager.get_job(job_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="任务不存在") from exc
    return {"job": job}


@app.post("/api/jobs/{job_id}/retry")
def retry_job(job_id: str) -> dict[str, object]:
    try:
        job = manager.clone_job(job_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="任务不存在") from exc
    return {"job": job}


@app.post("/api/jobs/{job_id}/cancel")
def cancel_job(job_id: str) -> dict[str, object]:
    try:
        payload = manager.cancel_job(job_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="任务不存在") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return payload


@app.post("/api/jobs/{job_id}/open-output")
def open_job_output(job_id: str) -> dict[str, bool]:
    try:
        output_dir = manager.get_job(job_id)["output_dir"]
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="任务不存在") from exc

    if not output_dir:
        raise HTTPException(status_code=400, detail="该任务没有输出目录")

    try:
        manager.open_path_in_explorer(output_dir)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"ok": True}


@app.get("/api/results")
def list_results(refresh: bool = Query(False, description="是否强制刷新结果缓存")) -> dict[str, object]:
    return {"results": manager.list_results(refresh=refresh)}


@app.get("/api/results/{result_id}")
def get_result(result_id: str) -> dict[str, object]:
    try:
        result = manager.get_result(result_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="结果不存在") from exc
    return {"result": result}


@app.post("/api/results/{result_id}/open")
def open_result(result_id: str) -> dict[str, bool]:
    try:
        result = manager.get_result(result_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="结果不存在") from exc

    try:
        manager.open_path_in_explorer(result["run_dir"])
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"ok": True}


@app.get("/api/results/{result_id}/artifact")
def get_result_artifact(
    result_id: str,
    relative: str = Query(..., description="相对于结果目录的文件路径"),
) -> FileResponse:
    try:
        target = manager.resolve_result_artifact(result_id=result_id, relative_path=relative)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="结果不存在") from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc

    return FileResponse(path=target, media_type=guess_media_type(target), filename=target.name)


@app.post("/api/results/{result_id}/export-qwen3-tts")
def export_result_qwen3_tts(result_id: str, payload: ExportQwen3TtsPayload) -> dict[str, object]:
    data = payload.model_dump(exclude_none=True)
    try:
        export = manager.export_qwen3_tts_dataset(
            result_id=result_id,
            ref_audio=data.get("ref_audio"),
            output_dir=data.get("output_dir"),
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="结果不存在") from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"export": export}


@app.post("/api/system/open")
def open_system_path(target: Literal["project", "inputs", "outputs", "webui_outputs"]) -> dict[str, bool]:
    mapping = {
        "project": PROJECT_ROOT,
        "inputs": PROJECT_ROOT / "inputs",
        "outputs": PROJECT_ROOT / "outputs",
        "webui_outputs": PROJECT_ROOT / "outputs" / "webui_runs",
    }

    try:
        manager.open_path_in_explorer(str(mapping[target]))
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return {"ok": True}


@app.post("/api/system/open-path")
def open_any_path(payload: OpenPathPayload) -> dict[str, bool]:
    target = resolve_project_path(payload.path)
    try:
        manager.open_path_in_explorer(str(target))
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"ok": True}
