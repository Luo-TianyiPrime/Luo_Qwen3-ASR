const state = {
  meta: null,
  form: {},
  jobs: [],
  selectedJobId: null,
  results: [],
  selectedResultId: null,
  resultDetailCache: {},
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
  setTimeout(() => node.remove(), 3000);
}

async function request(url, options = {}) {
  const response = await fetch(url, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  if (!response.ok) {
    let detail = `请求失败（${response.status}）`;
    try {
      const payload = await response.json();
      if (payload.detail) detail = payload.detail;
    } catch {
      // ignore
    }
    throw new Error(detail);
  }
  const contentType = response.headers.get("Content-Type") || "";
  return contentType.includes("application/json") ? response.json() : response.text();
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
    const options = field.options || [];
    for (const option of options) {
      const item = document.createElement("option");
      item.value = String(option.value ?? "");
      item.textContent = option.label || String(option.value ?? "");
      if (String(value) === item.value) item.selected = true;
      control.appendChild(item);
    }
    control.addEventListener("change", (event) => setFormValue(field.key, event.target.value));
  } else if (field.type === "checkbox") {
    control = document.createElement("input");
    control.type = "checkbox";
    control.checked = Boolean(value);
    control.addEventListener("change", (event) => setFormValue(field.key, event.target.checked));
  } else if (field.key === "hotword_text") {
    control = document.createElement("textarea");
    control.rows = 5;
    control.value = String(value ?? "");
    if (field.placeholder) control.placeholder = field.placeholder;
    control.addEventListener("change", (event) => setFormValue(field.key, event.target.value));
  } else {
    control = document.createElement("input");
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
  const payload = await request("/api/jobs");
  state.jobs = payload.jobs || [];
  if (!state.selectedJobId && state.jobs.length) state.selectedJobId = state.jobs[0].id;
  if (state.selectedJobId && !state.jobs.some((x) => x.id === state.selectedJobId)) {
    state.selectedJobId = state.jobs[0]?.id || null;
  }
  renderJobs();
}

async function submitTask() {
  const payload = { ...state.form, title: el.taskTitle.value.trim() };
  const result = await request("/api/jobs/asr", { method: "POST", body: JSON.stringify(payload) });
  const job = result.job;
  if (job.warning) toast(job.warning);
  state.selectedJobId = job.id;
  await refreshJobs();
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
  const previewArtifacts = audioArtifacts.slice(0, 12);
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
    lines.push(`<details class="artifact-block"><summary>产物文件（展示前 ${Math.min(result.artifacts.length, 80)} / ${result.artifacts.length}）</summary>`);
    lines.push('<ul class="artifact-list">');
    for (const art of result.artifacts.slice(0, 80)) {
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
    el.openInputsBtn.addEventListener("click", () => openSystemPath("inputs").catch((e) => toast(e.message, "error")));
    el.retryJobBtn.addEventListener("click", () => retrySelectedJob().catch((e) => toast(e.message, "error")));
    el.cancelJobBtn.addEventListener("click", () => cancelSelectedJob().catch((e) => toast(e.message, "error")));
    el.openJobOutputBtn.addEventListener("click", () => openSelectedOutput().catch((e) => toast(e.message, "error")));
    el.refreshResultsBtn.addEventListener("click", () => refreshResults(true).catch((e) => toast(e.message, "error")));
    el.openProjectBtn.addEventListener("click", () => openSystemPath("project").catch((e) => toast(e.message, "error")));
    el.openOutputsBtn.addEventListener("click", () => openSystemPath("outputs").catch((e) => toast(e.message, "error")));

    setInterval(() => refreshJobs().catch(() => {}), 2500);
    setInterval(() => refreshResults(false).catch(() => {}), 5000);
  } catch (error) {
    toast(error.message || String(error), "error");
  }
}

init();
