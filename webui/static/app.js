// ── 常量定义 ──
const TOAST_DURATION_MS = 3000;
const JOBS_POLL_INTERVAL_MS = 2500;
const RESULTS_POLL_INTERVAL_MS = 5000;
// 普通 API 请求 15 秒仍未响应时主动中止。ASR 长任务本身在后台运行，不依赖这个 HTTP 请求一直保持连接。
// 这样后端意外退出时，按钮不会永久停在“提交中”；轮询也能在下一轮自动恢复。
const REQUEST_TIMEOUT_MS = 15000;
const AUDIO_PREVIEW_LIMIT = 12;
const ARTIFACT_LIST_LIMIT = 80;
const RESULT_PREVIEW_CHARS = 300;

const state = {
  meta: null,
  form: {},
  jobs: [],
  selectedJobId: null,
  results: [],
  selectedResultId: null,
  resultDetailCache: {},
  // ----------------------------------------------------------
  // 热词库编辑器状态
  // hotwordLibraryLoaded：当前加载到 textarea 的热词库文件名（如 "Nikki.txt"）
  //   为 null 表示尚未从热词库加载过内容（可能是手动输入的临时热词）
  // hotwordLibraryOriginalText：加载热词库时 textarea 的原始内容
  //   用于比较 textarea 当前值是否被修改（脏数据检测）
  // ----------------------------------------------------------
  hotwordLibraryLoaded: null,
  hotwordLibraryOriginalText: "",
  submitting: false,
  jobsRefreshing: false,
  resultsRefreshing: false,
};

const el = {
  statusStrip: document.getElementById("statusStrip"),
  startupHint: document.getElementById("startupHint"),
  environmentBoard: document.getElementById("environmentBoard"),
  quickActions: document.getElementById("quickActions"),
  guideSections: document.getElementById("guideSections"),
  formGroups: document.getElementById("formGroups"),
  taskTitle: document.getElementById("taskTitle"),
  submitTaskBtn: document.getElementById("submitTaskBtn"),
  saveDefaultsBtn: document.getElementById("saveDefaultsBtn"),
  saveHotwordBtn: document.getElementById("saveHotwordBtn"),
  openInputsBtn: document.getElementById("openInputsBtn"),
  openProjectBtn: document.getElementById("openProjectBtn"),
  openOutputsBtn: document.getElementById("openOutputsBtn"),
  historyList: document.getElementById("historyList"),
  jobNotice: document.getElementById("jobNotice"),
  retryJobBtn: document.getElementById("retryJobBtn"),
  cancelJobBtn: document.getElementById("cancelJobBtn"),
  openJobOutputBtn: document.getElementById("openJobOutputBtn"),
  progressLabel: document.getElementById("progressLabel"),
  progressBar: document.getElementById("progressBar"),
  logShell: document.getElementById("logShell"),
  refreshResultsBtn: document.getElementById("refreshResultsBtn"),
  resultList: document.getElementById("resultList"),
  resultDetail: document.getElementById("resultDetail"),
  toastStack: document.getElementById("toastStack"),
  // 热词库修改确认对话框相关元素
  hotwordModal: document.getElementById("hotwordModal"),
  hotwordModalTitle: document.getElementById("hotwordModalTitle"),
  hotwordModalBody: document.getElementById("hotwordModalBody"),
  hotwordModalActions: document.getElementById("hotwordModalActions"),
};

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function formatBytes(value) {
  const bytes = Number(value) || 0;
  const units = ["B", "KB", "MB", "GB"];
  let size = Math.max(0, bytes);
  let unitIndex = 0;
  while (size >= 1024 && unitIndex < units.length - 1) {
    size /= 1024;
    unitIndex += 1;
  }
  const decimals = size >= 10 || unitIndex === 0 ? 0 : 1;
  return `${size.toFixed(decimals)} ${units[unitIndex]}`;
}

function buildResultArtifactUrl(resultId, relativePath) {
  const query = new URLSearchParams({ relative: relativePath || "" });
  return `/api/results/${encodeURIComponent(resultId)}/artifact?${query.toString()}`;
}

function isAudioArtifact(artifact) {
  const mediaType = String(artifact?.media_type || "").toLowerCase();
  if (mediaType.startsWith("audio/")) return true;
  const relativePath = String(artifact?.relative_path || artifact?.name || "").toLowerCase();
  return [".wav", ".mp3", ".m4a", ".aac", ".flac", ".ogg", ".opus", ".webm"].some((ext) => relativePath.endsWith(ext));
}

function audioArtifactRank(artifact) {
  const path = String(artifact?.relative_path || "").toLowerCase();
  if (path.startsWith("segments/")) return 0;
  if (path.startsWith("data/audio/")) return 1;
  if (path.startsWith("data/ref/")) return 2;
  if (path.startsWith("_tmp/")) return 3;
  return 4;
}

function audioArtifactLabel(artifact) {
  const relativePath = String(artifact?.relative_path || artifact?.name || "");
  const baseName = relativePath.split("/").pop() || relativePath;
  return baseName.replace(/\.[^.]+$/, "") || baseName;
}

function collectAudioArtifacts(result) {
  return [...(result?.artifacts || [])]
    .filter(isAudioArtifact)
    .sort((left, right) => {
      const rankDelta = audioArtifactRank(left) - audioArtifactRank(right);
      if (rankDelta !== 0) return rankDelta;
      return String(left.relative_path || "").localeCompare(String(right.relative_path || ""), "zh-CN");
    });
}

function toast(message, type = "") {
  const node = document.createElement("div");
  node.className = `toast ${type}`.trim();
  node.textContent = message;
  el.toastStack.appendChild(node);
  setTimeout(() => node.remove(), TOAST_DURATION_MS);
}

async function request(url, options = {}) {
  const { timeoutMs = REQUEST_TIMEOUT_MS, ...fetchOptions } = options;
  const controller = new AbortController();
  const externalSignal = fetchOptions.signal;
  const abortFromCaller = () => controller.abort(externalSignal?.reason);
  if (externalSignal) externalSignal.addEventListener("abort", abortFromCaller, { once: true });
  const timeoutId = setTimeout(() => controller.abort("timeout"), timeoutMs);

  try {
    const response = await fetch(url, {
      ...fetchOptions,
      headers: { "Content-Type": "application/json", ...(fetchOptions.headers || {}) },
      signal: controller.signal,
    });
    if (!response.ok) {
      let detail = `请求失败（${response.status}）`;
      try {
        const payload = await response.json();
        if (payload.detail) detail = payload.detail;
      } catch {
        // 响应不是 JSON 时保留包含 HTTP 状态码的通用提示。
      }
      throw new Error(detail);
    }
    const contentType = response.headers.get("Content-Type") || "";
    return contentType.includes("application/json") ? response.json() : response.text();
  } catch (error) {
    if (controller.signal.aborted && !externalSignal?.aborted) {
      throw new Error(`请求超过 ${Math.round(timeoutMs / 1000)} 秒仍未响应，请确认 WebUI 后端仍在运行。`);
    }
    throw error;
  } finally {
    clearTimeout(timeoutId);
    if (externalSignal) externalSignal.removeEventListener("abort", abortFromCaller);
  }
}

function statusLabel(status) {
  return { queued: "排队中", running: "运行中", success: "成功", failed: "失败", cancelled: "已取消", canceled: "已取消" }[status] || status;
}

function deriveStartupHint(env) {
  if (!env) return "";
  if (!env.venv_exists) return "还没有创建虚拟环境，先点“安装基础依赖”，或者先运行 bootstrap.ps1。";
  if (!env.ffmpeg_path || !env.ffprobe_path) return "还没找到 ffmpeg / ffprobe，先安装 ffmpeg 再提交任务。";
  if ((env.inputs_audio_count || 0) === 0) return "输入目录里还没有音频，先把文件放进输入目录，再来提交任务。";
  if (!(env.models?.asr_default_exists && env.models?.aligner_default_exists)) return "本地模型还没准备好，先点“下载模型”把模型补齐。";
  return "环境已就绪，可以直接提交任务。";
}

function renderEnvironmentBoard() {
  const env = state.meta?.environment;
  if (!env) return;
  const cards = [
    {
      title: "虚拟环境",
      ok: Boolean(env.venv_exists),
      detail: env.venv_exists ? "已就绪" : "未创建，先运行 bootstrap.ps1",
    },
    {
      title: "音频工具",
      ok: Boolean(env.ffmpeg_path && env.ffprobe_path),
      detail: env.ffmpeg_path && env.ffprobe_path ? "已找到" : "未找到，先安装 ffmpeg",
    },
    {
      title: "输入音频",
      ok: (env.inputs_audio_count || 0) > 0,
      detail: (env.inputs_audio_count || 0) > 0 ? `已找到 ${env.inputs_audio_count} 个音频` : "还没有音频，先放进输入目录",
    },
    {
      title: "本地模型",
      ok: Boolean(env.models?.asr_default_exists && env.models?.aligner_default_exists),
      detail:
        env.models?.asr_default_exists && env.models?.aligner_default_exists
          ? "ASR 和对齐模型都已到位"
          : "还没下载本地模型，先运行下载模型",
    },
  ];

  el.environmentBoard.innerHTML = "";
  for (const card of cards) {
    const node = document.createElement("div");
    node.className = `status-card ${card.ok ? "ok" : "warn"}`.trim();
    node.innerHTML = `<strong>${escapeHtml(card.title)}</strong><span>${escapeHtml(card.detail)}</span>`;
    el.environmentBoard.appendChild(node);
  }
}

function renderQuickActions() {
  const env = state.meta?.environment;
  const actions = env?.quick_actions || [];
  el.quickActions.innerHTML = "";
  for (const action of actions) {
    const node = document.createElement("button");
    node.type = "button";
    node.className = "action-card";
    node.innerHTML = `<strong>${escapeHtml(action.label || action.kind)}</strong><span>${escapeHtml(action.description || "")}</span>`;
    node.addEventListener("click", () => runQuickAction(action.kind).catch((e) => toast(e.message, "error")));
    el.quickActions.appendChild(node);
  }
}

function renderGuideSections() {
  const env = state.meta?.environment;
  const sections = env?.guide_sections || [];
  el.guideSections.innerHTML = "";
  for (const section of sections) {
    const node = document.createElement("article");
    node.className = "guide-card";
    const items = (section.items || []).map((item) => `<li>${escapeHtml(item)}</li>`).join("");
    node.innerHTML = `<h3>${escapeHtml(section.title || "使用说明")}</h3><ul>${items}</ul>`;
    el.guideSections.appendChild(node);
  }
}

function renderStatus() {
  if (!state.meta) return;
  const env = state.meta.environment || {};
  const root = state.meta.project_root || "";
  const jobs = state.jobs.reduce(
    (acc, job) => {
      acc[job.status] = (acc[job.status] || 0) + 1;
      return acc;
    },
    { queued: 0, running: 0, failed: 0 },
  );
  const parts = [`项目目录：${root}`];
  parts.push(env.venv_exists ? "虚拟环境已就绪" : "虚拟环境未创建");
  parts.push(env.ffmpeg_path && env.ffprobe_path ? "音频工具已就绪" : "音频工具未就绪");
  parts.push((env.inputs_audio_count || 0) > 0 ? `输入音频：${env.inputs_audio_count} 个` : "输入音频：还没有放文件");
  parts.push(`任务：${jobs.queued || 0} 排队 / ${jobs.running || 0} 运行 / ${jobs.failed || 0} 失败`);
  el.statusStrip.textContent = parts.join(" · ");
  el.startupHint.textContent = deriveStartupHint(env);
}

function setFormValue(key, value) {
  state.form[key] = value;
  if (key === "output_mode") renderForm();
}

function getFieldLayoutClass(field) {
  const wideKeys = new Set(["audio", "output_dir", "ref_audio", "asr_ckpt", "aligner_ckpt", "punc_model", "hotword_text"]);
  const classes = ["field"];
  if (wideKeys.has(field.key)) classes.push("field--wide");
  if (field.type === "checkbox") classes.push("field--checkbox");
  return classes.join(" ");
}

function renderField(field) {
  const value = state.form[field.key] ?? "";
  const wrap = document.createElement("div");
  wrap.className = getFieldLayoutClass(field);
  const label = document.createElement("label");
  label.textContent = field.label || field.key;
  wrap.appendChild(label);

  let control = null;
  if (field.type === "select") {
    control = document.createElement("select");
    control.id = `field-${field.key}`;
    const options = field.options || [];
    for (const option of options) {
      const item = document.createElement("option");
      item.value = String(option.value ?? "");
      item.textContent = option.label || String(option.value ?? "");
      if (String(value) === item.value) item.selected = true;
      control.appendChild(item);
    }
    if (field.key === "hotword_library") {
      // 热词库下拉框：切换时自动加载库内容到 textarea，并处理未保存修改的提示
      control.addEventListener("change", async (event) => {
        const success = await handleHotwordLibraryChange(event.target.value);
        if (success) {
          setFormValue(field.key, event.target.value);
        } else {
          // 用户取消切换：把下拉框恢复为切换前的值
          control.value = String(state.form[field.key] ?? "");
        }
      });
    } else {
      control.addEventListener("change", (event) => setFormValue(field.key, event.target.value));
    }
  } else if (field.type === "checkbox") {
    control = document.createElement("input");
    control.id = `field-${field.key}`;
    control.type = "checkbox";
    control.checked = Boolean(value);
    control.addEventListener("change", (event) => setFormValue(field.key, event.target.checked));
  } else if (field.key === "hotword_text") {
    control = document.createElement("textarea");
    control.id = `field-${field.key}`;
    control.rows = 5;
    control.value = String(value ?? "");
    if (field.placeholder) control.placeholder = field.placeholder;
    control.addEventListener("input", (event) => setFormValue(field.key, event.target.value));
  } else {
    control = document.createElement("input");
    control.id = `field-${field.key}`;
    control.type = field.type === "number" ? "number" : "text";
    control.value = String(value ?? "");
    if (field.step !== undefined) control.step = String(field.step);
    if (field.min !== undefined) control.min = String(field.min);
    if (field.placeholder) control.placeholder = field.placeholder;
    if (field.key === "output_dir" && state.form.output_mode !== "custom") {
      control.disabled = true;
    }
    control.addEventListener("change", (event) => {
      if (field.type === "number") {
        const raw = event.target.value.trim();
        setFormValue(field.key, raw === "" ? "" : Number(raw));
      } else {
        setFormValue(field.key, event.target.value);
      }
    });
  }

  wrap.appendChild(control);
  const d1 = document.createElement("small");
  d1.textContent = field.description || "";
  wrap.appendChild(d1);
  const d2 = document.createElement("small");
  d2.textContent = field.long_help || "";
  wrap.appendChild(d2);

  // 热词编辑区专属：「保存到当前热词库」按钮
  // 放在 textarea 下方右侧，方便用户在编辑热词后直接保存
  // 点击后先弹出确认对话框，用户确认后才真正写入热词库 txt 文件
  // 这样可以避免用户误操作，把临时修改误保存为长期内容
  if (field.key === "hotword_text") {
    const actionRow = document.createElement("div");
    actionRow.className = "field-action-row";
    const saveBtn = document.createElement("button");
    saveBtn.type = "button";
    saveBtn.id = "saveCurrentHotwordBtn";
    saveBtn.textContent = "保存到当前热词库";
    saveBtn.addEventListener("click", () => saveToCurrentHotwordLibrary().catch((e) => toast(e.message, "error")));
    actionRow.appendChild(saveBtn);
    wrap.appendChild(actionRow);
  }

  return wrap;
}

function renderForm() {
  const env = state.meta?.environment;
  if (!env) return;
  const fields = env.form_fields || [];
  const groups = env.form_groups || [];
  const fieldsByGroup = new Map();
  for (const field of fields) {
    const groupId = field.group || "other";
    if (!fieldsByGroup.has(groupId)) fieldsByGroup.set(groupId, []);
    fieldsByGroup.get(groupId).push(field);
  }

  el.formGroups.innerHTML = "";
  if (!groups.length) {
    for (const field of fields) {
      el.formGroups.appendChild(renderField(field));
    }
    return;
  }

  for (const group of groups) {
    const groupFields = fieldsByGroup.get(group.id) || [];
    if (!groupFields.length) continue;

    const section = document.createElement("section");
    section.className = "form-section";

    const header = document.createElement("div");
    header.className = "form-section-header";
    const title = document.createElement("h3");
    title.textContent = group.title || "配置分组";
    const description = document.createElement("p");
    description.textContent = group.description || "";
    header.appendChild(title);
    header.appendChild(description);

    const grid = document.createElement("div");
    grid.className = "form-section-grid";
    for (const field of groupFields) {
      grid.appendChild(renderField(field));
    }

    section.appendChild(header);
    section.appendChild(grid);
    el.formGroups.appendChild(section);
  }

  const groupedKeys = new Set(groups.flatMap((group) => (fieldsByGroup.get(group.id) || []).map((field) => field.key)));
  const ungroupedFields = fields.filter((field) => !groupedKeys.has(field.key));
  if (ungroupedFields.length) {
    const fallback = document.createElement("section");
    fallback.className = "form-section";
    const grid = document.createElement("div");
    grid.className = "form-section-grid";
    for (const field of ungroupedFields) {
      grid.appendChild(renderField(field));
    }
    fallback.appendChild(grid);
    el.formGroups.appendChild(fallback);
  }
}

function selectedJob() {
  return state.jobs.find((x) => x.id === state.selectedJobId) || null;
}

function renderJobs() {
  el.historyList.innerHTML = "";
  for (const job of state.jobs) {
    const node = document.createElement("div");
    node.className = `item ${job.id === state.selectedJobId ? "active" : ""}`.trim();
    const warning = job.warning ? ` | [警告] ${job.warning}` : "";
    const isCanceled =
      job.status === "cancelled" ||
      job.status === "canceled" ||
      job.progress_label === "任务已取消" ||
      job.error === "用户手动取消";
    const statusText = isCanceled ? "已取消" : statusLabel(job.status);
    node.textContent = `${job.title} | ${statusText} | ${job.progress_value?.toFixed?.(1) ?? 0}%${warning}`;
    node.addEventListener("click", () => {
      state.selectedJobId = job.id;
      renderJobs();
      renderSelectedJob();
    });
    el.historyList.appendChild(node);
  }
  renderSelectedJob();
  renderStatus();
}

function renderSelectedJob() {
  const job = selectedJob();
  if (!job) {
    el.progressLabel.textContent = "暂无运行中的任务";
    el.progressBar.style.width = "0%";
    el.logShell.textContent = "";
    el.jobNotice.innerHTML = "";
    el.retryJobBtn.disabled = true;
    el.cancelJobBtn.disabled = true;
    el.openJobOutputBtn.disabled = true;
    return;
  }
  el.progressLabel.textContent = `${job.progress_label || ""}（${(job.progress_value || 0).toFixed(1)}%）`;
  el.progressBar.style.width = `${Math.max(0, Math.min(100, job.progress_value || 0))}%`;
  el.logShell.textContent = (job.log_tail || []).join("\n");
  const notices = [];
  if (job.warning) notices.push(`<div class="warning">提醒：${escapeHtml(job.warning)}</div>`);
  if (job.status === "failed" && job.error) notices.push(`<div class="error-box">失败原因：${escapeHtml(job.error)}</div>`);
  el.jobNotice.innerHTML = notices.join("");
  el.retryJobBtn.disabled = false;
  el.cancelJobBtn.disabled = !["queued", "running"].includes(job.status);
  el.openJobOutputBtn.disabled = !job.output_dir;
}

async function runQuickAction(kind) {
  const result = await request(`/api/jobs/actions/${kind}`, { method: "POST" });
  const job = result.job;
  state.selectedJobId = job.id;
  toast(`${job.title} 已加入队列`);
  await refreshJobs();
}

async function refreshJobs() {
  if (state.jobsRefreshing) return;
  state.jobsRefreshing = true;
  try {
    const payload = await request("/api/jobs");
    state.jobs = payload.jobs || [];
    if (!state.selectedJobId && state.jobs.length) state.selectedJobId = state.jobs[0].id;
    if (state.selectedJobId && !state.jobs.some((x) => x.id === state.selectedJobId)) {
      state.selectedJobId = state.jobs[0]?.id || null;
    }
    renderJobs();
  } finally {
    // setInterval 不会等待上一次 Promise。用标志位禁止慢请求重叠，避免旧响应覆盖较新的页面状态。
    state.jobsRefreshing = false;
  }
}

async function submitTask() {
  if (state.submitting) return;
  state.submitting = true;
  el.submitTaskBtn.disabled = true;
  el.submitTaskBtn.textContent = "提交中...";
  try {
    const payload = { ...state.form, title: el.taskTitle.value.trim() };
    const result = await request("/api/jobs/asr", { method: "POST", body: JSON.stringify(payload) });
    const job = result.job;
    if (job.warning) toast(job.warning);
    state.selectedJobId = job.id;
    await refreshJobs();
  } finally {
    state.submitting = false;
    el.submitTaskBtn.disabled = false;
    el.submitTaskBtn.textContent = "提交识别任务";
  }
}

async function savePreferences() {
  await request("/api/preferences", { method: "PUT", body: JSON.stringify(state.form) });
  toast("偏好已保存");
}

async function retrySelectedJob() {
  const job = selectedJob();
  if (!job) return;
  const result = await request(`/api/jobs/${job.id}/retry`, { method: "POST" });
  state.selectedJobId = result.job.id;
  await refreshJobs();
}

async function cancelSelectedJob() {
  const job = selectedJob();
  if (!job || !["queued", "running"].includes(job.status)) return;
  await request(`/api/jobs/${job.id}/cancel`, { method: "POST" });
  await refreshJobs();
  toast(`${job.title} 已取消`);
}

async function openSelectedOutput() {
  const job = selectedJob();
  if (!job) return;
  await request(`/api/jobs/${job.id}/open-output`, { method: "POST" });
}

async function refreshResults(force = false) {
  if (state.resultsRefreshing) return;
  state.resultsRefreshing = true;
  try {
    const previousSelectedId = state.selectedResultId;
    const previousSelected = state.results.find((x) => x.id === previousSelectedId) || null;
    const query = force ? "?refresh=1" : "";
    const payload = await request(`/api/results${query}`);
    state.results = payload.results || [];
    if (!state.selectedResultId && state.results.length) state.selectedResultId = state.results[0].id;
    if (state.selectedResultId && !state.results.some((x) => x.id === state.selectedResultId)) {
      state.selectedResultId = state.results[0]?.id || null;
    }
    const selectionChanged = previousSelectedId !== state.selectedResultId;
    const currentSelected = state.results.find((x) => x.id === state.selectedResultId) || null;
    const selectedUpdated = Boolean(previousSelected && currentSelected && previousSelected.updated_at !== currentSelected.updated_at);
    renderResults();
    if (!state.selectedResultId) {
      renderResultDetail(false).catch((e) => toast(e.message, "error"));
      return;
    }
    if (force || selectionChanged || selectedUpdated || !state.resultDetailCache[state.selectedResultId]) {
      await renderResultDetail(force || selectionChanged || selectedUpdated);
    }
  } finally {
    state.resultsRefreshing = false;
  }
}

async function loadResultDetail(resultId, force = false) {
  if (!force && state.resultDetailCache[resultId]) {
    return state.resultDetailCache[resultId];
  }
  const payload = await request(`/api/results/${resultId}`);
  state.resultDetailCache[resultId] = payload.result;
  return payload.result;
}

function renderResults() {
  el.resultList.innerHTML = "";
  for (const row of state.results) {
    const node = document.createElement("div");
    node.className = `item ${row.id === state.selectedResultId ? "active" : ""}`.trim();
    node.textContent = `${row.title || row.relative_run_dir} | ${new Date(row.updated_at).toLocaleString()}`;
    node.addEventListener("click", async () => {
      state.selectedResultId = row.id;
      renderResults();
      await renderResultDetail(true);
    });
    el.resultList.appendChild(node);
  }
}

async function renderResultDetail(force = false) {
  if (!state.selectedResultId) {
    el.resultDetail.textContent = "请选择一条结果查看详情";
    return;
  }
  const result = await loadResultDetail(state.selectedResultId, force);
  const lines = [];
  const warning = result.meta?.warning || result.warning || "";
  const audioArtifacts = collectAudioArtifacts(result);
  const previewArtifacts = audioArtifacts.slice(0, AUDIO_PREVIEW_LIMIT);
  if (warning) {
    lines.push(`<div class="warning">[警告] ${escapeHtml(warning)}</div>`);
  }
  lines.push('<div class="result-meta">');
  lines.push(`<div><b>目录：</b>${escapeHtml(result.run_dir)}</div>`);
  lines.push(`<div><b>更新时间：</b>${escapeHtml(new Date(result.updated_at).toLocaleString())}</div>`);
  if (result.meta?.segments !== undefined) {
    lines.push(`<div><b>分句数量：</b>${escapeHtml(result.meta.segments)}</div>`);
  }
  lines.push(`<div><b>预览：</b>${escapeHtml(result.preview || "（无）")}</div>`);
  lines.push('</div>');
  if (previewArtifacts.length) {
    lines.push("<hr>");
    lines.push(`<div class="section-title"><b>片段试听：</b>共 ${previewArtifacts.length} / ${audioArtifacts.length} 个音频预览</div>`);
    lines.push('<div class="audio-preview-grid">');
    for (const art of previewArtifacts) {
      const url = buildResultArtifactUrl(result.id, art.relative_path);
      const label = audioArtifactLabel(art);
      lines.push(`
        <article class="audio-preview-card">
          <div class="audio-preview-title" title="${escapeHtml(label)}">${escapeHtml(label)}</div>
          <div class="audio-preview-meta" title="${escapeHtml(art.relative_path)}">${escapeHtml(art.relative_path)}</div>
          <audio controls preload="none" src="${escapeHtml(url)}"></audio>
        </article>
      `);
    }
    lines.push("</div>");
    if (audioArtifacts.length > previewArtifacts.length) {
      lines.push(`<div class="muted">结果内共有 ${audioArtifacts.length} 个音频文件，当前优先展示前 ${previewArtifacts.length} 个片段，避免页面一次性加载过重。</div>`);
    }
  }
  if (result.artifacts?.length) {
    lines.push("<hr>");
    lines.push(`<details class="artifact-block"><summary>产物文件（展示前 ${Math.min(result.artifacts.length, ARTIFACT_LIST_LIMIT)} / ${result.artifacts.length}）</summary>`);
    lines.push('<ul class="artifact-list">');
    for (const art of result.artifacts.slice(0, ARTIFACT_LIST_LIMIT)) {
      const url = buildResultArtifactUrl(result.id, art.relative_path);
      lines.push(`<li><a href="${escapeHtml(url)}" target="_blank" rel="noreferrer">${escapeHtml(art.relative_path)}</a> (${escapeHtml(formatBytes(art.size))})</li>`);
    }
    lines.push("</ul></details>");
  }
  el.resultDetail.innerHTML = lines.join("");
}

async function openSystemPath(target) {
  await request("/api/system/open", { method: "POST", body: JSON.stringify({ target }) });
}

// ----------------------------------------------------------
// 热词库编辑器：检查 textarea 是否有未保存修改
// 比较 textarea 当前值 与 上次从热词库文件加载的原始内容
// 如果 hotwordLibraryLoaded 为 null（未从热词库加载过），则不算脏数据
// ----------------------------------------------------------
function isHotwordDirty() {
  if (!state.hotwordLibraryLoaded) return false;
  const textarea = document.getElementById("field-hotword_text");
  if (!textarea) return false;
  return textarea.value !== state.hotwordLibraryOriginalText;
}

// ----------------------------------------------------------
// 自定义确认对话框：基于 Promise，返回用户点击的按钮值
//
// 为什么不用浏览器原生 window.confirm()：
//   window.confirm() 只能显示「确定/取消」两个按钮，无法满足
//   "仅临时使用 / 保存到热词库 / 取消"三个选项的需求。
//   所以这里自己实现了一个简单 modal，复用项目现有深色主题样式。
//
// 参数 options：
//   title  - 对话框标题
//   body   - 对话框正文（支持 \n 换行）
//   buttons - 按钮数组，每项 { label, value, cssClass }
//             点击按钮后，Promise resolve(value)；
//             点击遮罩或按 ESC resolve('cancel')
//
// 使用示例：
//   const choice = await showHotwordDialog({
//     title: "确认如何处理热词修改？",
//     body: "你已经修改了当前热词内容。...",
//     buttons: [
//       { label: "仅临时使用", value: "temp", cssClass: "hotword-modal-btn-temp" },
//       { label: "保存到热词库", value: "save", cssClass: "hotword-modal-btn-save" },
//       { label: "取消", value: "cancel", cssClass: "hotword-modal-btn-cancel" },
//     ],
//   });
//   if (choice === "save") { ... }
// ----------------------------------------------------------
function showHotwordDialog(options) {
  return new Promise((resolve) => {
    // 填充标题和正文
    el.hotwordModalTitle.textContent = options.title || "";
    el.hotwordModalBody.textContent = options.body || "";

    // 创建按钮
    el.hotwordModalActions.innerHTML = "";
    for (const btn of (options.buttons || [])) {
      const node = document.createElement("button");
      node.type = "button";
      node.textContent = btn.label;
      node.className = btn.cssClass || "";
      node.addEventListener("click", () => closeHotwordDialog(btn.value));
      el.hotwordModalActions.appendChild(node);
    }

    // 显示对话框
    el.hotwordModal.hidden = false;

    // 把 resolve 暂存，关闭时调用
    el.hotwordModal._resolve = resolve;

    // ESC 键关闭（视为取消）
    el.hotwordModal._onKey = (e) => {
      if (e.key === "Escape") closeHotwordDialog("cancel");
    };
    document.addEventListener("keydown", el.hotwordModal._onKey);

    // 点击遮罩关闭（视为取消）
    el.hotwordModal._onBackdrop = (e) => {
      if (e.target === el.hotwordModal.querySelector(".hotword-modal-backdrop")) {
        closeHotwordDialog("cancel");
      }
    };
    el.hotwordModal.addEventListener("click", el.hotwordModal._onBackdrop);
  });
}

// ----------------------------------------------------------
// 关闭确认对话框
// value: 传给 Promise resolve 的值，表示用户的选择
// ----------------------------------------------------------
function closeHotwordDialog(value) {
  el.hotwordModal.hidden = true;

  // 移除事件监听，避免内存泄漏
  if (el.hotwordModal._onKey) {
    document.removeEventListener("keydown", el.hotwordModal._onKey);
    el.hotwordModal._onKey = null;
  }
  if (el.hotwordModal._onBackdrop) {
    el.hotwordModal.removeEventListener("click", el.hotwordModal._onBackdrop);
    el.hotwordModal._onBackdrop = null;
  }

  // 触发 Promise resolve
  if (typeof el.hotwordModal._resolve === "function") {
    const resolve = el.hotwordModal._resolve;
    el.hotwordModal._resolve = null;
    resolve(value);
  }
}

// ----------------------------------------------------------
// 从服务器加载指定热词库的全部内容，并写入 textarea
// libraryName: 热词库文件名（如 "Nikki.txt"）
// textarea: 可选，如果已传入则直接更新 DOM；否则通过 id 查找
// ----------------------------------------------------------
async function loadHotwordLibraryContent(libraryName, textarea) {
  try {
    const result = await request("/api/hotwords/load", {
      method: "POST",
      body: JSON.stringify({ name: libraryName }),
    });
    const content = result.library.content;
    // 更新状态：记录加载的库名和原始内容（作为脏数据检测的基准）
    state.form.hotword_text = content;
    state.hotwordLibraryLoaded = libraryName;
    state.hotwordLibraryOriginalText = content;
    // 更新 textarea DOM 显示
    const ta = textarea || document.getElementById("field-hotword_text");
    if (ta) ta.value = content;
    return true;
  } catch (e) {
    toast(e.message, "error");
    return false;
  }
}

// ----------------------------------------------------------
// 热词库下拉框切换时的处理函数
//
// 行为说明：
//   - 切换到"不使用"：先检查脏数据，提示用户确认后清空 textarea
//   - 切换到有内容的热词库：检查脏数据，弹出对话框让用户选择：
//       1. 不保存并切换 → 丢弃当前修改，加载新库
//       2. 保存后切换   → 先保存到当前库，再加载新库
//       3. 取消切换     → 什么都不做，恢复下拉框旧值
//   - 如果 textarea 没有修改（不脏），直接加载新库，不弹对话框
//
// 注意：
//   原生 window.confirm() 只能做 OK/Cancel 两个按钮，
//   这里改用自定义 showHotwordDialog() 实现三按钮确认。
// ----------------------------------------------------------
async function handleHotwordLibraryChange(newValue) {
  const textarea = document.getElementById("field-hotword_text");

  // ── 切换到"不使用"（value 为空字符串）──
  if (!newValue) {
    if (isHotwordDirty()) {
      const choice = await showHotwordDialog({
        title: "当前热词内容有未保存修改",
        body:
          "切换到「不使用」会清空下方热词编辑区。\n" +
          "当前未保存的修改不会写入任何热词库文件。\n\n" +
          "你可以选择仅临时使用这些热词（本次任务有效），或直接放弃修改。",
        buttons: [
          { label: "仅临时使用", value: "temp", cssClass: "hotword-modal-btn-temp" },
          { label: "放弃修改并切换", value: "discard", cssClass: "hotword-modal-btn-save" },
          { label: "取消切换", value: "cancel", cssClass: "hotword-modal-btn-cancel" },
        ],
      });
      if (choice === "cancel") return false;
      // temp 和 discard 都允许切换，但不保留修改（切换后 textarea 清空）
      if (choice === "temp") {
        // 「仅临时使用」：保留 textarea 内容不清空，但不关联任何热词库
        // 用户提交任务时这些热词仍然有效
        state.hotwordLibraryLoaded = null;
        state.hotwordLibraryOriginalText = "";
        toast("当前热词已作为临时热词保留，本次任务有效，不会保存到热词库。");
        return true;
      }
    }
    // 清空 textarea 和关联状态
    state.form.hotword_text = "";
    state.hotwordLibraryLoaded = null;
    state.hotwordLibraryOriginalText = "";
    if (textarea) textarea.value = "";
    return true;
  }

  // ── 切换到有内容的热词库 ──
  if (isHotwordDirty()) {
    const choice = await showHotwordDialog({
      title: "当前热词内容有未保存修改",
      body:
        `你正在从「${state.hotwordLibraryLoaded || "(无)"}」切换到「${newValue}」。\n` +
        "下方热词编辑区有未保存的修改。\n\n" +
        "你可以选择：\n" +
        "· 仅临时使用：保留当前编辑内容，但不保存到文件，切换后清空编辑区\n" +
        "· 保存后切换：先把修改写回当前热词库文件，再加载新库\n" +
        "· 取消切换：不做任何操作",
      buttons: [
        { label: "不保存并切换", value: "discard", cssClass: "hotword-modal-btn-temp" },
        { label: "保存后切换", value: "saveAndSwitch", cssClass: "hotword-modal-btn-save" },
        { label: "取消切换", value: "cancel", cssClass: "hotword-modal-btn-cancel" },
      ],
    });

    if (choice === "cancel") return false;

    if (choice === "saveAndSwitch") {
      // 先保存到当前库，再加载新库
      try {
        await saveHotwordContent();
      } catch (e) {
        toast(`保存失败：${e.message}，已取消切换。`, "error");
        return false;
      }
    }
    // discard 和 saveAndSwitch 都继续：加载新库
  }

  // 加载新热词库内容到 textarea
  return loadHotwordLibraryContent(newValue, textarea);
}

// ----------------------------------------------------------
// 纯保存函数：不弹对话框，直接把 textarea 内容写入当前热词库文件
//
// 这个函数是保存的底层实现，被以下两个入口调用：
//   1. saveToHotwordLibrary()    → 先弹确认框，用户点"保存到热词库"后调用
//   2. handleHotwordLibraryChange() → 用户选"保存后切换"时调用
//
// 保存成功后会自动更新 hotwordLibraryOriginalText，
// 这样后续 isHotwordDirty() 会返回 false，表示内容已与文件同步。
// ----------------------------------------------------------
async function saveHotwordContent() {
  const textarea = document.getElementById("field-hotword_text");
  if (!textarea) throw new Error("找不到热词编辑区");

  const result = await request("/api/hotwords/save", {
    method: "POST",
    body: JSON.stringify({
      name: state.hotwordLibraryLoaded,
      content: textarea.value,
    }),
  });
  // 保存成功后同步状态：更新原始内容基准，后续不再提示脏数据
  // 服务端会清理空行和重复词，必须用服务端实际写入的规范化文本作为新基准，
  // 否则保存后 textarea 仍会被误判为“有未保存修改”。
  const savedContent = result.library.content;
  textarea.value = savedContent;
  state.hotwordLibraryOriginalText = savedContent;
  state.form.hotword_text = savedContent;
  return result;
}

// ----------------------------------------------------------
// 保存到热词库按钮的点击处理
//
// 这是用户点击「保存到热词库」按钮时触发的入口函数。
// 它不会直接保存，而是先弹出确认对话框，让用户明确选择：
//   A. 仅临时使用：修改只用于本次 ASR 任务，不写文件
//   B. 保存到热词库：真正修改 configs/hotwords/*.txt 文件
//   C. 取消：什么都不做
//
// 为什么要弹确认框？
//   因为修改 configs/hotwords/*.txt 是持久化操作，
//   会影响以后每次选中该热词库时的内容。
//   用户需要明确知道这次点击会修改文件，而不是临时生效。
// ----------------------------------------------------------
async function saveToHotwordLibrary() {
  // 没有选中热词库：不允许保存（因为没有目标文件可写）
  if (!state.hotwordLibraryLoaded) {
    toast("请先选择热词库。未选择热词库时，当前内容只能作为临时热词用于本次任务。", "warn");
    return;
  }

  // textarea 内容没有变化：没必要保存
  if (!isHotwordDirty()) {
    toast("当前内容没有变化，无需保存。", "warn");
    return;
  }

  // 弹出确认对话框
  const choice = await showHotwordDialog({
    title: "确认如何处理热词修改？",
    body:
      `你已经修改了当前热词内容（热词库：${state.hotwordLibraryLoaded}）。\n\n` +
      "如果选择「仅临时使用」：\n" +
      "  这些修改只会用于本次识别任务，不会保存到长期热词库文件。\n" +
      "  下次选择该热词库时，看到的仍然是修改前的内容。\n\n" +
      "如果选择「保存到热词库」：\n" +
      "  当前内容会写入已选择的热词库文件（位于 configs/hotwords 目录），\n" +
      "  之后无论哪次任务选择该热词库，都会看到修改后的内容。",
    buttons: [
      { label: "仅临时使用", value: "temp", cssClass: "hotword-modal-btn-temp" },
      { label: "保存到热词库", value: "save", cssClass: "hotword-modal-btn-save" },
      { label: "取消", value: "cancel", cssClass: "hotword-modal-btn-cancel" },
    ],
  });

  if (choice === "cancel") return;

  if (choice === "temp") {
    // 「仅临时使用」：不调保存 API，保留 textarea 内容用于本次任务
    // 注意：不更新 hotwordLibraryOriginalText，所以下次切换/保存时仍会提示脏数据
    toast("已作为临时热词使用，本次任务有效，不会保存到热词库。");
    return;
  }

  if (choice === "save") {
    // 「保存到热词库」：调用 API 写回文件
    try {
      const result = await saveHotwordContent();
      toast(`已保存到热词库「${result.library.stem}」（${result.library.entries} 条）。`);
    } catch (e) {
      toast(`保存失败：${e.message}`, "error");
      // 保存失败时不修改 textarea，也不更新 hotwordLibraryOriginalText
    }
  }
}

// ----------------------------------------------------------
// 保存到当前热词库按钮的点击处理
//
// 这个按钮位于热词编辑区（textarea）下方右侧，文案为「保存到当前热词库」。
//
// 和底部「保存到热词库」按钮的区别：
//   底部按钮提供三选一（仅临时使用/保存到热词库/取消），
//   而这个按钮定位更明确——用户就是想保存，只需确认是否真的写入文件。
//   因此这里使用两按钮确认框（保存到热词库/取消），流程更短。
//
// 行为说明：
//   1. 未选热词库 → toast 提示"请先选择热词库"，不弹对话框
//   2. textarea 无修改 → toast 提示"无需保存"，不弹对话框
//   3. textarea 有修改 → 弹出确认对话框
//      - 确认 → 调用 saveHotwordContent() 真正写入 .txt 文件
//      - 取消 → 不保存，textarea 内容保留
// ----------------------------------------------------------
async function saveToCurrentHotwordLibrary() {
  // 没有选中热词库：不允许保存（没有目标文件可写）
  // textarea 中的热词仍然有效，提交任务时会使用，只是无法保存回库文件
  if (!state.hotwordLibraryLoaded) {
    toast("请先选择热词库。未选择热词库时，当前内容只能作为临时热词用于本次任务。", "warn");
    return;
  }

  // textarea 内容没有变化：没必要写文件，避免无意义的 API 调用
  if (!isHotwordDirty()) {
    toast("当前热词内容没有变化，无需保存。", "warn");
    return;
  }

  // 弹出两按钮确认对话框
  // 这里不需要"仅临时使用"选项，因为用户点击这个按钮的意图就是保存
  const choice = await showHotwordDialog({
    title: "确认保存热词库？",
    body:
      `当前编辑框中的热词内容将写入已选择的长期热词库文件（${state.hotwordLibraryLoaded}）。\n\n` +
      "保存后，以后再次选择这个热词库时，也会看到这些修改。\n\n" +
      "如果你只是想让这些热词用于本次识别任务，请不要保存，直接提交任务即可。",
    buttons: [
      { label: "保存到热词库", value: "save", cssClass: "hotword-modal-btn-save" },
      { label: "取消", value: "cancel", cssClass: "hotword-modal-btn-cancel" },
    ],
  });

  if (choice === "cancel") return;

  // 用户确认保存：调用底层 saveHotwordContent() 写回热词库文件
  try {
    await saveHotwordContent();
    toast("已保存到当前热词库。");
  } catch (e) {
    // 保存失败时：保留 textarea 内容，不更新 hotwordLibraryOriginalText
    // 这样下次仍然可以尝试保存，不会丢失用户的修改
    toast(`保存失败：${e.message}`, "error");
  }
}

async function init() {
  try {
    const meta = await request("/api/meta");
    state.meta = meta;
    state.form = { ...(meta.preferences || {}) };
    renderStatus();
    renderEnvironmentBoard();
    renderQuickActions();
    renderForm();
    renderGuideSections();
    await refreshJobs();
    await refreshResults(false);

    el.submitTaskBtn.addEventListener("click", () => submitTask().catch((e) => toast(e.message, "error")));
    el.saveDefaultsBtn.addEventListener("click", () => savePreferences().catch((e) => toast(e.message, "error")));
    el.saveHotwordBtn.addEventListener("click", () => saveToHotwordLibrary().catch((e) => toast(e.message, "error")));
    el.openInputsBtn.addEventListener("click", () => openSystemPath("inputs").catch((e) => toast(e.message, "error")));
    el.retryJobBtn.addEventListener("click", () => retrySelectedJob().catch((e) => toast(e.message, "error")));
    el.cancelJobBtn.addEventListener("click", () => cancelSelectedJob().catch((e) => toast(e.message, "error")));
    el.openJobOutputBtn.addEventListener("click", () => openSelectedOutput().catch((e) => toast(e.message, "error")));
    el.refreshResultsBtn.addEventListener("click", () => refreshResults(true).catch((e) => toast(e.message, "error")));
    el.openProjectBtn.addEventListener("click", () => openSystemPath("project").catch((e) => toast(e.message, "error")));
    el.openOutputsBtn.addEventListener("click", () => openSystemPath("outputs").catch((e) => toast(e.message, "error")));

    setInterval(() => refreshJobs().catch(() => {}), JOBS_POLL_INTERVAL_MS);
    setInterval(() => refreshResults(false).catch(() => {}), RESULTS_POLL_INTERVAL_MS);
  } catch (error) {
    toast(error.message || String(error), "error");
  }
}

init();
