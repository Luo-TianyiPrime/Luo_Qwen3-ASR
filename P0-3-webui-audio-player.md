# P0-3: WebUI 结果库嵌入音频试听播放器

## 上下文

项目 Qwen3-ASR 是一个本地语音识别+分句切分工具，包含 CLI 和 WebUI 两种使用方式。WebUI 由以下文件构成：

- `webui/app.py` — FastAPI 后端（402 行）
- `webui/service.py` — 业务逻辑与任务管理（1454 行）
- `webui/static/index.html` — 页面结构（82 行）
- `webui/static/app.js` — 前端逻辑（439 行）
- `webui/static/styles.css` — 样式（228 行）

当前结果库页面可以列出任务输出的产物文件，但所有产物一律渲染为纯文本 `<li>relative_path (size bytes)</li>`，没有音频播放能力。用户评估切句效果必须离开浏览器去文件管理器找 wav 文件播放，体验断裂。

后端已有完整 API：`GET /api/results/{result_id}/artifact?relative=segments/xxx.wav` 返回文件流，可直接作为 `<audio src>` 使用。无需新增任何后端接口。

## 目标

在结果详情面板中，对每个音频产物（.wav/.mp3/.flac 等）渲染一个 `<audio>` 播放器，实现「识别完成 → 浏览器内试听切句片段 → 调参 → 重新识别」的闭环工作流。

## 涉及文件

| 文件 | 改动类型 |
|------|----------|
| `webui/static/app.js` | 修改 |
| `webui/static/styles.css` | 修改 |
| `webui/app.py` | **不改** |
| `webui/service.py` | **不改** |

## 完整规格

### 1. app.js — 新增辅助函数

在 `app.js` 中 `renderResultDetail` 函数（约第 379 行）**之前**，新增两个辅助函数：

```javascript
function isAudioArtifact(art) {
  if ((art.media_type || "").startsWith("audio/")) return true;
  const audioExts = [".wav", ".mp3", ".flac", ".ogg", ".m4a", ".aac", ".opus", ".wma", ".webm"];
  const path = (art.relative_path || "").toLowerCase();
  return audioExts.some(ext => path.endsWith(ext));
}

function formatFileSize(bytes) {
  if (bytes < 1024) return bytes + " B";
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + " KB";
  return (bytes / (1024 * 1024)).toFixed(1) + " MB";
}
```

说明：
- `isAudioArtifact` 通过 MIME 前缀和文件后缀双重判断，因为 `guess_media_type` 对 `.wav` 在不同操作系统可能返回 `audio/wav`、`audio/x-wav` 或空值
- `formatFileSize` 将字节数转为人类可读单位

### 2. app.js — 重写 renderResultDetail

替换当前 `renderResultDetail` 函数（约第 379-403 行）完整函数体为：

```javascript
async function renderResultDetail() {
  if (!state.selectedResultId) {
    el.resultDetail.textContent = "请选择一条结果查看详情";
    return;
  }
  const result = await loadResultDetail(state.selectedResultId);
  const lines = [];
  const warning = result.meta?.warning || result.warning || "";
  if (warning) {
    lines.push(`<div class="warning">[警告] ${escapeHtml(warning)}</div>`);
  }
  lines.push(`<div><b>目录：</b>${escapeHtml(result.run_dir)}</div>`);
  lines.push(`<div><b>更新时间：</b>${new Date(result.updated_at).toLocaleString()}</div>`);
  lines.push(`<div><b>预览：</b>${escapeHtml(result.preview || "（无）")}</div>`);

  if (result.artifacts?.length) {
    const audioItems = [];
    const otherItems = [];
    for (const art of result.artifacts) {
      if (isAudioArtifact(art)) {
        audioItems.push(art);
      } else {
        otherItems.push(art);
      }
    }

    if (audioItems.length > 0) {
      lines.push("<hr>");
      lines.push(`<h3>音频片段（${audioItems.length}）</h3>`);
      const displayAudios = audioItems.slice(0, 50);
      for (const art of displayAudios) {
        const src = `/api/results/${encodeURIComponent(state.selectedResultId)}/artifact?relative=${encodeURIComponent(art.relative_path)}`;
        lines.push(`<div class="audio-item">`);
        lines.push(`  <div class="audio-item-header">`);
        lines.push(`    <span class="audio-item-name">${escapeHtml(art.relative_path)}</span>`);
        lines.push(`    <span class="audio-item-size">${formatFileSize(art.size)}</span>`);
        lines.push(`  </div>`);
        lines.push(`  <audio controls preload="metadata" src="${src}" style="width:100%;max-width:480px"></audio>`);
        lines.push(`</div>`);
      }
      if (audioItems.length > 50) {
        lines.push(`<div class="section-note">仅展示前 50 个音频片段，完整列表请在文件管理器中查看。</div>`);
      }
    }

    if (otherItems.length > 0) {
      lines.push("<hr>");
      lines.push(`<h3>其他产物（${otherItems.length}）</h3>`);
      lines.push("<ul>");
      const displayOthers = otherItems.slice(0, 100);
      for (const art of displayOthers) {
        lines.push(`<li>${escapeHtml(art.relative_path)} (${formatFileSize(art.size)})</li>`);
      }
      if (otherItems.length > 100) {
        lines.push(`<li>…还有 ${otherItems.length - 100} 个文件未展示</li>`);
      }
      lines.push("</ul>");
    }
  }

  el.resultDetail.innerHTML = lines.join("\n");
}
```

与原函数的关键差异：

| 行为 | 原实现 | 新实现 |
|------|--------|--------|
| 产物展示 | 全部混为 `<li>` 列表，最多 80 条 | 音频与非音频分区展示 |
| 音频文件 | 与 json/txt 同等渲染 | 独立区块 + `<audio>` 播放器 |
| 文件大小 | 原始字节数 | 人类可读单位（KB/MB） |
| 音频上限 | 无 | 50 个播放器，超出提示 |
| 非音频上限 | 80 条 | 100 条，超出提示 |

### 3. styles.css — 新增样式

在 `styles.css` 末尾追加：

```css
.audio-item {
  margin-bottom: 10px;
  padding: 8px;
  border: 1px solid #d9e3ef;
  border-radius: 8px;
  background: #f8fafd;
}
.audio-item-header {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  margin-bottom: 4px;
  gap: 8px;
}
.audio-item-name {
  font-family: monospace;
  font-size: 12px;
  color: #334155;
  word-break: break-all;
}
.audio-item-size {
  font-size: 11px;
  color: #6b7e8f;
  white-space: nowrap;
}
.audio-item audio {
  display: block;
}
.detail h3 {
  margin: 4px 0 8px 0;
  font-size: 14px;
  color: #1a2b3c;
}
```

色彩与间距全部沿用现有变量（`#d9e3ef`、`#f8fafd`、`#334155` 等），不引入新设计语言。

## 硬性约束

1. **不改后端** — `app.py` 和 `service.py` 零改动，完全复用 `GET /api/results/{result_id}/artifact`
2. **不引入前端依赖** — 禁止 React/Vue/jQuery/Axios，保持原生 JS 风格
3. **XSS 防护** — 所有用户数据通过 `escapeHtml()` 转义，`art.relative_path` 和 `state.selectedResultId` 在拼入 URL 时用 `encodeURIComponent` 编码
4. **`<audio>` 必须加 `preload="metadata"`** — 避免同时加载几十个 wav 全量数据导致浏览器卡死
5. **原生 `controls` 属性** — 使用浏览器内置播放控件，不自己实现播放逻辑
6. **编码风格一致** — 变量命名、函数结构、错误处理方式与现有 `app.js` 保持一致

## 验证步骤

1. 启动 WebUI：`run_webui.bat` 或 `.\start_webui.ps1`
2. 提交一个 ASR 任务并等待完成
3. 进入"结果库"，选择一条有 segments 输出的结果
4. 确认结果详情顶部出现"音频片段"区块，每个 wav 文件有一条可点击播放的 `<audio>` 控件
5. 点击播放，确认音频正常播放、进度条可拖动
6. 确认非音频产物（如 `meta.json`、`full_text.txt`、`index.jsonl`）以文本列表展示在"其他产物"区块
7. 打开浏览器 DevTools → Network，确认未点击播放的 wav 文件只有 metadata 级请求（Range header 或很小的传输量），不会全量下载