/* Main IDE controller: Monaco editors, project open/upload, Explain/Debug flow. */
(function () {
  const { api, el, toast } = CL;
  const $ = (id) => document.getElementById(id);
  const MONACO_BASE = "https://cdn.jsdelivr.net/npm/monaco-editor@0.52.2/min";
  const SKIP_DIRS = new Set([".git", "node_modules", "venv", ".venv", "env", "__pycache__", "dist", "build", ".idea", ".vscode", ".mypy_cache", ".pytest_cache", ".tox", "site-packages", ".next"]);
  const BINARY_EXT = /\.(png|jpe?g|gif|bmp|ico|webp|pdf|zip|gz|tar|7z|rar|exe|dll|so|dylib|bin|pyc|pyo|class|jar|woff2?|ttf|otf|eot|mp3|mp4|mov|avi|wav|sqlite3|db|pkl|npy|npz|h5|onnx|pt|docx|xlsx|pptx)$/i;
  const MAX_FILE = 200 * 1024;

  const S = {
    session: null,    // null (Home) | "project" | "paste"
    projects: [],     // recent projects for Home
    projectId: null,
    currentPath: null,
    tab: "project",
    models: {},       // path -> monaco model
    dirty: new Set(), // paths edited in the buffer (never saved)
    decos: {},        // model uri -> {static: [], ai: []}
    aiIssues: {},     // model uri -> issues
    last: null,       // context of the last Explain/Debug request
    busy: false,
    kbCount: 0,
    editor: null,
    paste: null,
  };

  /* ── Monaco boot ─────────────────────────────────── */
  window.MonacoEnvironment = {
    getWorkerUrl() {
      return "data:text/javascript;charset=utf-8," + encodeURIComponent(
        `self.MonacoEnvironment={baseUrl:'${MONACO_BASE}/'};importScripts('${MONACO_BASE}/vs/base/worker/workerMain.js');`
      );
    },
  };
  require.config({ paths: { vs: `${MONACO_BASE}/vs` } });
  require(["vs/editor/editor.main"], boot, () => toast("Could not load the Monaco editor from the CDN. Check your internet connection."));

  function boot() {
    const common = {
      theme: "vs-dark",
      automaticLayout: true,
      fontFamily: "JetBrains Mono, Consolas, monospace",
      fontSize: 13,
      minimap: { enabled: false },
      glyphMargin: true,
      scrollBeyondLastLine: false,
      smoothScrolling: true,
      fixedOverflowWidgets: true,
    };
    S.editor = monaco.editor.create($("editorProject"), { ...common, model: null });
    S.paste = monaco.editor.create($("editorPaste"), { ...common, value: "", language: "python" });

    for (const ed of [S.editor, S.paste]) {
      ed.onDidChangeCursorSelection(updateSelectionUI);
      ed.onDidScrollChange(updateSelectionUI);
      ed.addAction({ id: "cl-explain", label: "CodeLens: Explain selection", keybindings: [monaco.KeyMod.CtrlCmd | monaco.KeyMod.Shift | monaco.KeyCode.KeyE], contextMenuGroupId: "navigation", run: () => run("explain") });
      ed.addAction({ id: "cl-debug", label: "CodeLens: Debug selection", keybindings: [monaco.KeyMod.CtrlCmd | monaco.KeyMod.Shift | monaco.KeyCode.KeyD], contextMenuGroupId: "navigation", run: () => run("debug") });
    }
    let pasteTimer;
    S.paste.onDidChangeModelContent(() => {
      $("pastePlaceholder").classList.toggle("d-none", S.tab !== "paste" || S.paste.getModel().getValueLength() > 0);
      if (S.session === "paste") safeSet("cl.pasteDraft", S.paste.getValue().slice(0, 200000));
      clearTimeout(pasteTimer);
      pasteTimer = setTimeout(() => analyzeModel(S.paste.getModel(), $("pasteLang").value), 700);
    });

    S.editor.addAction({ id: "cl-save", label: "CodeLens: Save file to project", keybindings: [monaco.KeyMod.CtrlCmd | monaco.KeyCode.KeyS], run: () => saveCurrent() });

    AIPanel.init($("aiPanel"), { onJump: jumpToLine, onApplyFix: applyFix, onOpenFile: openFile, onRetry: retryAnswer });
    ProjectPanel.init();
    SlashMenu.attach($("problemText"), { chip: $("problemSkill") });
    wireUi();
    withRetry(loadKbCount);
    const saved = safeGet("cl.session") || "";
    withRetry(loadProjects).then(() => {
      const id = Number((saved.match(/^project:(\d+)$/) || [])[1]);
      if (id && S.projects.some((p) => p.id === id)) openProject(id);
      else if (saved === "paste") startPaste();
      else showHome();
    });
    updateSelectionUI();
  }

  function safeGet(k) { try { return localStorage.getItem(k); } catch (e) { return null; } }
  function safeSet(k, v) { try { localStorage.setItem(k, v); } catch (e) { /* storage unavailable */ } }

  /* ── UI wiring ───────────────────────────────────── */
  function wireUi() {
    $("homeFolder").addEventListener("click", () => $("folderInput").click());
    $("homeZip").addEventListener("click", () => $("zipInput").click());
    $("homePaste").addEventListener("click", () => startPaste());
    $("btnExit").addEventListener("click", () => exitSession());
    $("folderInput").addEventListener("change", uploadFolder);
    $("zipInput").addEventListener("change", uploadZip);
    $("btnSave").addEventListener("click", () => saveCurrent());
    $("btnDownload").addEventListener("click", () => download());
    $("btnExplain").addEventListener("click", () => run("explain"));
    $("btnDebug").addEventListener("click", () => run("debug"));
    $("btnStop").addEventListener("click", () => S.controller && S.controller.abort());
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape" && S.controller && !e.target.closest("#aiChat")) S.controller.abort();
    });
    $("selPop").addEventListener("click", (e) => {
      const b = e.target.closest("button[data-action]");
      if (b) run(b.dataset.action);
    });
    $("pasteLang").addEventListener("change", (e) => {
      monaco.editor.setModelLanguage(S.paste.getModel(), e.target.value);
      analyzeModel(S.paste.getModel(), e.target.value);
    });
    const mode = safeGet("cl.mode");
    if (mode) $("modeSelect").value = mode;
    $("modeSelect").addEventListener("change", (e) => safeSet("cl.mode", e.target.value));
    wireResizers();
  }

  function wireResizers() {
    const ide = $("ide");
    for (const key of ["tree", "ai"]) {
      const saved = safeGet(`cl.w.${key}`);
      if (saved) ide.style.setProperty(`--${key}-w`, saved);
    }
    document.querySelectorAll(".resizer").forEach((bar) => {
      bar.addEventListener("mousedown", (e) => {
        e.preventDefault();
        const key = bar.dataset.resize;
        bar.classList.add("dragging");
        const startX = e.clientX;
        const startW = (key === "tree" ? $("paneTree") : $("paneAi")).getBoundingClientRect().width;
        const move = (ev) => {
          const dx = ev.clientX - startX;
          const w = key === "tree" ? startW + dx : startW - dx;
          const max = key === "tree" ? 420 : Math.min(760, window.innerWidth - 600);
          ide.style.setProperty(`--${key}-w`, `${Math.max(key === "tree" ? 150 : 300, Math.min(max, w))}px`);
        };
        const up = () => {
          bar.classList.remove("dragging");
          document.removeEventListener("mousemove", move);
          document.removeEventListener("mouseup", up);
          safeSet(`cl.w.${key}`, ide.style.getPropertyValue(`--${key}-w`));
        };
        document.addEventListener("mousemove", move);
        document.addEventListener("mouseup", up);
      });
    });
  }

  function switchTab(tab) {
    S.tab = tab;
    $("editorPaste").classList.toggle("d-none", tab !== "paste");
    $("editorProject").classList.toggle("d-none", tab !== "project");
    $("pasteLang").classList.toggle("d-none", tab !== "paste");
    $("filePath").classList.toggle("d-none", tab !== "project");
    $("editorEmpty").classList.toggle("d-none", tab === "paste" || !!S.editor.getModel());
    $("pastePlaceholder").classList.toggle("d-none", tab !== "paste" || S.paste.getModel().getValueLength() > 0);
    (tab === "paste" ? S.paste : S.editor).focus();
    updateSelectionUI();
  }

  /* ── Sessions: Home → project session | paste session → Exit ── */
  function setSession(kind, projectId, name) {
    S.session = kind;
    document.body.classList.remove("session-home", "session-project", "session-paste");
    document.body.classList.add(`session-${kind}`);
    safeSet("cl.session", kind === "project" ? `project:${projectId}` : kind);
    $("sessionLabel").replaceChildren(
      CL.icon(kind === "project" ? "folder2-open" : "clipboard"),
      el("span", { text: kind === "project" ? ` Project: ${name}` : " Paste session" })
    );
  }

  function showHome() {
    S.session = null;
    document.body.classList.remove("session-project", "session-paste");
    document.body.classList.add("session-home");
  }

  function startPaste() {
    setSession("paste");
    const draft = safeGet("cl.pasteDraft");
    if (draft && !S.paste.getValue()) S.paste.setValue(draft);
    $("sbProject").replaceChildren(CL.icon("clipboard"), " Paste session");
    ProjectPanel.resetChat();
    ProjectPanel.showView("selection");
    switchTab("paste");
  }

  /* End the session (after confirming unsaved work) and reload into Home. */
  function exitSession() {
    const dirty = [...S.dirty];
    const pasted = S.session === "paste" && S.paste.getValue().trim();
    const warn = dirty.length ? `${dirty.length} file(s) have unsaved changes (${dirty.join(", ")}). They will be lost.`
      : pasted ? "Your pasted code will be cleared." : "";
    if (!confirm(`End this session and go back to Home?${warn ? `\n\n${warn}` : ""}`)) return;
    if (S.controller) S.controller.abort();
    ProjectPanel.resetChat();
    try {
      localStorage.removeItem("cl.session");
      localStorage.removeItem("cl.pasteDraft");
    } catch (e) { /* storage unavailable */ }
    window.location.href = "/";
  }

  /* ── Projects ────────────────────────────────────── */
  /* Retry start-up loads a few times (e.g. the dev server is restarting). */
  async function withRetry(fn, tries = 4) {
    for (let i = 0; i < tries; i++) {
      if (await fn(i === tries - 1)) return true;
      await new Promise((r) => setTimeout(r, 1500 * (i + 1)));
    }
    return false;
  }

  async function loadProjects(reportErrors = true) {
    try {
      const data = await api("/api/projects");
      S.projects = data.projects;
      const list = data.projects.slice(0, 6).map((p) => {
        const row = el("button", { type: "button", class: "home-project" }, [
          CL.icon("folder2"), el("span", { class: "hp-name", text: p.name }), el("span", { class: "muted", text: `${p.files} files` }),
        ]);
        row.addEventListener("click", () => openProject(p.id));
        return row;
      });
      $("homeRecent").replaceChildren(...(list.length ? list : [el("div", { class: "muted small", text: "No projects yet — open a folder or upload a .zip." })]));
      return true;
    } catch (e) {
      if (reportErrors) toast(e.message);
      return false;
    }
  }

  async function loadKbCount() {
    try {
      const data = await api("/api/docs");
      S.kbCount = data.docs.length;
      $("kbCount").textContent = S.kbCount ? String(S.kbCount) : "";
      $("sbDocsN").textContent = String(S.kbCount);
      if (!S.last) AIPanel.showEmpty(S.kbCount);
      return true;
    } catch (e) {
      return false; // non-critical; withRetry tries again
    }
  }

  async function openProject(id) {
    let data;
    try {
      data = await api(`/api/projects/${id}/tree`);
    } catch (e) {
      toast(e.message);
      return;
    }
    Object.values(S.models).forEach((m) => m.dispose());
    S.models = {};
    S.dirty.clear();
    S.projectId = id;
    S.currentPath = null;
    S.editor.setModel(null);
    setSession("project", id, data.name);
    $("projectName").textContent = data.name;
    $("sbProject").replaceChildren(CL.icon("folder2-open"), ` ${data.name}`);
    $("filePath").replaceChildren();
    Tree.render($("tree"), data.tree, (path) => openFile(path));
    $("btnDownload").disabled = false;
    ProjectPanel.resetChat();
    ProjectPanel.showView("overview");
    refreshOverview();
    switchTab("project");
    const first = findFile(data.tree, (n) => /(^|\/)views\.py$/.test(n.path)) || findFile(data.tree, (n) => n.language === "python");
    if (first) openFile(first.path);
  }

  function findFile(node, pred) {
    for (const c of node.children || []) {
      if (c.type === "file" && pred(c)) return c;
      const f = c.type === "dir" ? findFile(c, pred) : null;
      if (f) return f;
    }
    return null;
  }

  function busyTree(text) {
    const overlay = el("div", { class: "busy-overlay" }, [el("span", { class: "spinner-border spinner-border-sm" }), el("span", { text })]);
    (S.session ? $("paneTree") : $("home")).appendChild(overlay);
    return () => overlay.remove();
  }

  function keepFile(file, path) {
    const parts = path.split("/");
    if (parts.slice(0, -1).some((p) => SKIP_DIRS.has(p) || p.endsWith(".egg-info"))) return false;
    return !BINARY_EXT.test(path) && file.size <= MAX_FILE;
  }

  async function uploadFolder(e) {
    const files = [...e.target.files];
    e.target.value = "";
    if (!files.length) return;
    const kept = files.filter((f) => keepFile(f, f.webkitRelativePath || f.name));
    if (!kept.length) return toast("No readable source files found in that folder.");
    const form = new FormData();
    for (const f of kept) {
      form.append("files", f, f.name);
      form.append("paths", f.webkitRelativePath || f.name);
    }
    await sendUpload(form, `Uploading & indexing ${kept.length} files…`, files.length - kept.length);
  }

  async function uploadZip(e) {
    const file = e.target.files[0];
    e.target.value = "";
    if (!file) return;
    const form = new FormData();
    form.append("zip", file, file.name);
    await sendUpload(form, `Uploading & indexing ${file.name}…`, 0);
  }

  async function sendUpload(form, label, clientSkipped) {
    const done = busyTree(label);
    try {
      const res = await api("/api/projects/upload", { method: "POST", form });
      const skipped = res.skipped_count + clientSkipped;
      toast(`Opened “${res.name}”: ${res.file_count} files, ${res.chunks} code chunks indexed${skipped ? `, ${skipped} skipped` : ""}.`, "success");
      await loadProjects();
      await openProject(res.project_id);
    } catch (err) {
      toast(`Upload failed: ${err.message}`);
    } finally {
      done();
    }
  }

  /* ── Files + static analysis ─────────────────────── */
  async function openFile(path, line) {
    if (!S.projectId) return;
    let model = S.models[path];
    if (!model) {
      try {
        const f = await api(`/api/projects/${S.projectId}/file?path=${encodeURIComponent(path)}`);
        model = monaco.editor.createModel(f.content, f.language, monaco.Uri.parse(`file:///project-${S.projectId}/${path}`));
        model.__lang = f.language;
        model.__path = path;
        S.models[path] = model;
        let timer;
        model.onDidChangeContent(() => {
          S.dirty.add(path);
          renderPath();
          clearTimeout(timer);
          timer = setTimeout(() => analyzeModel(model, model.__lang), 700);
        });
        analyzeModel(model, f.language);
      } catch (e) {
        toast(e.message);
        return;
      }
    }
    if (S.tab !== "project") switchTab("project");
    S.currentPath = path;
    S.editor.setModel(model);
    $("editorEmpty").classList.add("d-none");
    renderPath();
    Tree.setActive($("tree"), path);
    if (line) revealLine(S.editor, line);
    updateSelectionUI();
  }

  function renderPath() {
    if (!S.currentPath) return;
    const parts = [el("span", { text: S.currentPath })];
    const dirty = S.dirty.has(S.currentPath);
    if (dirty) parts.push(el("span", { class: "dirty", text: "● unsaved changes" }));
    $("filePath").replaceChildren(...parts);
    $("btnSave").classList.toggle("d-none", !dirty || S.tab !== "project");
  }

  async function analyzeModel(model, language) {
    if (!model || model.isDisposed()) return;
    if (language !== "python") return setFindings(model, []);
    try {
      const res = await api("/api/analyze", { method: "POST", json: { code: model.getValue(), language, path: model.__path || "input.py" } });
      if (!model.isDisposed()) setFindings(model, res.findings);
    } catch (e) { /* analysis is best-effort */ }
  }

  const SEV = () => ({ error: monaco.MarkerSeverity.Error, warning: monaco.MarkerSeverity.Warning, info: monaco.MarkerSeverity.Info });

  function escapeMd(s) {
    return String(s).replace(/[\\`*_{}\[\]()#+\-.!|<>]/g, "\\$&");
  }

  function decoState(model) {
    const k = model.uri.toString();
    S.decos[k] = S.decos[k] || { static: [], ai: [] };
    return S.decos[k];
  }

  function setFindings(model, findings) {
    const lineCount = model.getLineCount();
    const valid = findings.filter((f) => f.line >= 1 && f.line <= lineCount);
    monaco.editor.setModelMarkers(model, "static", valid.map((f) => ({
      startLineNumber: f.line, endLineNumber: f.line,
      startColumn: Math.min(f.col + 1, model.getLineMaxColumn(f.line)), endColumn: model.getLineMaxColumn(f.line),
      message: `${f.code}: ${f.message}`, severity: SEV()[f.severity] || monaco.MarkerSeverity.Info, source: "static analysis",
    })));
    const st = decoState(model);
    st.static = model.deltaDecorations(st.static, valid.map((f) => ({
      range: new monaco.Range(f.line, 1, f.line, 1),
      options: { glyphMarginClassName: `glyph-${f.severity}`, glyphMarginHoverMessage: { value: `**Static analysis** · ${escapeMd(f.code)}\n\n${escapeMd(f.message)}` } },
    })));
  }

  function setAiIssues(model, issues) {
    if (!model || model.isDisposed()) return;
    const lineCount = model.getLineCount();
    const valid = issues.filter((i) => i.line && i.line >= 1 && i.line <= lineCount);
    const st = decoState(model);
    st.ai = model.deltaDecorations(st.ai, valid.map((i) => {
      const hover = { value: `**AI · ${escapeMd(i.severity)}: ${escapeMd(i.title)}**\n\n${escapeMd(i.reason.replace(/\[\d+\]/g, ""))}` };
      return {
        range: new monaco.Range(i.line, 1, i.line, model.getLineMaxColumn(i.line)),
        options: { isWholeLine: true, className: "line-ai", glyphMarginClassName: "glyph-ai", hoverMessage: hover, glyphMarginHoverMessage: hover },
      };
    }));
  }

  /* ── Selection + run ─────────────────────────────── */
  function activeEditor() {
    return S.tab === "paste" ? S.paste : S.editor;
  }

  function selectionInfo() {
    const ed = activeEditor();
    const model = ed && ed.getModel();
    if (!model) return null;
    const sel = ed.getSelection();
    let range;
    if (!sel || sel.isEmpty()) {
      if (S.tab !== "paste") return null;
      range = model.getFullModelRange();
    } else {
      const endLine = sel.endColumn === 1 && sel.endLineNumber > sel.startLineNumber ? sel.endLineNumber - 1 : sel.endLineNumber;
      range = new monaco.Range(sel.startLineNumber, 1, endLine, model.getLineMaxColumn(endLine));
    }
    return { range, model, code: model.getValueInRange(range, monaco.editor.EndOfLinePreference.LF), startLine: range.startLineNumber };
  }

  function updateStatusBar(ed, sel) {
    const model = ed && ed.getModel();
    $("sbCursor").classList.toggle("d-none", !sel);
    $("sbLang").classList.toggle("d-none", !model);
    if (!model || !sel) return;
    const pos = sel.getPosition();
    const lines = sel.endLineNumber - sel.startLineNumber + (sel.endColumn === 1 && !sel.isEmpty() ? 0 : 1);
    $("sbCursor").textContent = `Ln ${pos.lineNumber}, Col ${pos.column}${sel.isEmpty() ? "" : ` (${lines} lines selected)`}`;
    const lang = model.getLanguageId();
    $("sbLang").textContent = lang === "plaintext" ? "Plain text" : lang.charAt(0).toUpperCase() + lang.slice(1);
  }

  function updateSelectionUI() {
    const pop = $("selPop");
    const ed = activeEditor();
    const sel = ed && ed.getModel() ? ed.getSelection() : null;
    const has = !!(sel && !sel.isEmpty());
    updateStatusBar(ed, sel);
    const canRun = !S.busy && (has || (S.tab === "paste" && ed && ed.getModel()));
    $("btnExplain").disabled = !canRun;
    $("btnDebug").disabled = !canRun;
    $("selInfo").textContent = has
      ? `Lines ${sel.startLineNumber}–${sel.endColumn === 1 && sel.endLineNumber > sel.startLineNumber ? sel.endLineNumber - 1 : sel.endLineNumber}`
      : S.tab === "paste" ? "Whole snippet" : "Select code";
    if (!has || S.busy) return pop.classList.add("d-none");
    const pos = ed.getScrolledVisiblePosition({ lineNumber: sel.endLineNumber, column: sel.endColumn });
    if (!pos) return pop.classList.add("d-none");
    const wrap = pop.parentElement.getBoundingClientRect();
    pop.classList.remove("d-none");
    const top = Math.min(pos.top + pos.height + 6, wrap.height - 40);
    pop.style.top = `${Math.max(4, top)}px`;
    pop.style.left = `${Math.max(56, Math.min(pos.left, wrap.width - pop.offsetWidth - 12))}px`;
  }

  async function run(action) {
    if (S.busy) return;
    const info = selectionInfo();
    const problem = $("problemText").value.trim();
    if (!info || (!info.code.trim() && !problem)) {
      toast(S.tab === "paste" ? "Paste some code first." : "Select some code in the editor first (or use Paste mode).", "warning");
      return;
    }
    const language = S.tab === "paste" ? $("pasteLang").value : info.model.__lang || "plaintext";
    const path = S.tab === "project" ? S.currentPath : null;
    S.last = { ...info, action, path, language, versionId: info.model.getAlternativeVersionId(), hasProject: S.tab === "project" && !!S.projectId };
    setAiIssues(info.model, []);
    S.controller = new AbortController();
    const { signal } = S.controller;
    setBusy(true);
    ProjectPanel.showView("selection");
    AIPanel.showRetrieving(action);
    let retrieval;
    try {
      retrieval = await api("/api/retrieve", {
        method: "POST",
        json: {
          project_id: S.tab === "project" ? S.projectId : null,
          file_path: path,
          code: info.code,
          full_code: S.tab === "paste" ? info.model.getValue(monaco.editor.EndOfLinePreference.LF) : undefined,
          start_line: info.startLine,
          problem_text: problem,
          mode: $("modeSelect").value,
          action,
          language,
        },
        signal,
      });
      AIPanel.renderRetrieval(retrieval, S.last);
    } catch (e) {
      if (e instanceof CL.Cancelled) AIPanel.renderError("Stopped before anything was retrieved.");
      else {
        AIPanel.renderError(e.message);
        toast(e.message);
      }
      setBusy(false);
      return;
    }
    $("aiStatus").textContent = "Generating…";
    try {
      await fetchAnswer(retrieval.query_id, info.model, signal);
    } catch (e) {
      if (e instanceof CL.Cancelled) AIPanel.renderAnswerError("Stopped. The retrieved sources above are still shown; run Explain or Debug again for an answer.");
      else {
        AIPanel.renderAnswerError(e.message);
        toast(e.message);
      }
    } finally {
      setBusy(false);
    }
  }

  async function fetchAnswer(queryId, model, signal) {
    const res = await api("/api/answer", { method: "POST", json: { query_id: queryId }, signal });
    AIPanel.renderAnswer(res, S.last);
    setAiIssues(model, res.answer.issues);
  }

  /* Retry after a sources-only (offline) answer: same retrieval, ask the models again. */
  async function retryAnswer(queryId) {
    if (S.busy || !S.last) return;
    S.controller = new AbortController();
    setBusy(true);
    try {
      await fetchAnswer(queryId, S.last.model, S.controller.signal);
    } catch (e) {
      if (!(e instanceof CL.Cancelled)) toast(e.message);
    } finally {
      setBusy(false);
    }
  }

  function setBusy(busy) {
    S.busy = busy;
    if (!busy) S.controller = null;
    $("btnStop").classList.toggle("d-none", !busy);
    $("aiStatus").textContent = busy ? "Retrieving…" : "";
    updateSelectionUI();
  }

  function jumpToLine(line) {
    const ctx = S.last;
    const ed = ctx && ctx.model === S.paste.getModel() ? S.paste : S.editor;
    if (ctx && ctx.path && ctx.path !== S.currentPath && S.models[ctx.path]) {
      return openFile(ctx.path, line);
    }
    if (ed === S.paste && S.tab !== "paste") switchTab("paste");
    revealLine(ed, line);
  }

  function revealLine(ed, line) {
    const model = ed.getModel();
    if (!model) return;
    const ln = Math.max(1, Math.min(line, model.getLineCount()));
    ed.revealLineInCenter(ln);
    ed.setPosition({ lineNumber: ln, column: 1 });
    const flash = model.deltaDecorations([], [{ range: new monaco.Range(ln, 1, ln, 1), options: { isWholeLine: true, className: "line-flash" } }]);
    setTimeout(() => !model.isDisposed() && model.deltaDecorations(flash, []), 1200);
    ed.focus();
  }

  function applyFix(fixedCode) {
    const ctx = S.last;
    if (!ctx || ctx.model.isDisposed()) {
      toast("The original code is no longer open.");
      return false;
    }
    if (ctx.model.getAlternativeVersionId() !== ctx.versionId &&
        !confirm("The code changed since this answer was generated. Apply the fix to the original selection anyway?")) {
      return false;
    }
    const text = fixedCode.replace(/\r\n/g, "\n");
    ctx.model.pushEditOperations([], [{ range: ctx.range, text }], () => null);
    const lines = text.split("\n");
    const newRange = new monaco.Range(ctx.startLine, 1, ctx.startLine + lines.length - 1, lines[lines.length - 1].length + 1);
    ctx.range = newRange;
    ctx.versionId = ctx.model.getAlternativeVersionId();
    setAiIssues(ctx.model, []);
    if (ctx.path && ctx.path !== S.currentPath) openFile(ctx.path, ctx.startLine);
    const ed = ctx.model === S.paste.getModel() ? S.paste : S.editor;
    ed.setSelection(newRange);
    ed.revealRangeInCenter(newRange);
    toast(ctx.path ? "Fix applied in the editor. Press Save (Ctrl+S) to keep it in the project; Ctrl+Z to undo." : "Fix applied in the editor. Ctrl+Z to undo.", "success");
    return true;
  }

  /* ── Project copy: save, overview, download ───────── */
  async function saveFile(path) {
    const model = S.models[path];
    if (!model || !S.projectId) return false;
    try {
      await api(`/api/projects/${S.projectId}/file`, { method: "POST", json: { path, content: model.getValue(monaco.editor.EndOfLinePreference.LF) } });
    } catch (e) {
      toast(`Couldn't save ${path}: ${e.message}`);
      return false;
    }
    S.dirty.delete(path);
    renderPath();
    return true;
  }

  async function saveCurrent() {
    if (S.tab !== "project" || !S.currentPath || !S.dirty.has(S.currentPath)) return;
    if (await saveFile(S.currentPath)) {
      toast(`Saved ${S.currentPath} to the project copy (re-indexed).`, "success");
      refreshOverview();
    }
  }

  async function refreshOverview() {
    if (!S.projectId) return;
    const ov = await ProjectPanel.loadOverview(S.projectId);
    if (ov) Tree.setBadges($("tree"), Object.fromEntries(ov.per_file.map((f) => [f.path, f])));
  }

  async function download() {
    if (!S.projectId) return;
    const dirty = [...S.dirty];
    if (dirty.length) {
      if (confirm(`${dirty.length} file(s) have unsaved changes (${dirty.join(", ")}). Save them before downloading?`)) {
        for (const p of dirty) await saveFile(p);
      }
    }
    window.location.href = `/api/projects/${S.projectId}/download`;
  }

  /* Called by the chat panel after it writes a file; content null = file deleted. */
  async function fileSaved(path, content) {
    const model = S.models[path];
    if (content === null) {
      if (model) model.dispose();
      delete S.models[path];
      if (S.currentPath === path) {
        S.currentPath = null;
        S.editor.setModel(null);
        $("editorEmpty").classList.remove("d-none");
        $("filePath").replaceChildren();
      }
    } else if (model) {
      model.pushEditOperations([], [{ range: model.getFullModelRange(), text: content }], () => null);
      S.dirty.delete(path);
      renderPath();
    }
    const data = await api(`/api/projects/${S.projectId}/tree`).catch(() => null);
    if (data) Tree.render($("tree"), data.tree, (p) => openFile(p));
    if (S.currentPath) Tree.setActive($("tree"), S.currentPath);
    await refreshOverview();
  }

  function context() {
    const inProject = S.session === "project" && S.projectId;
    const project = inProject ? $("projectName").textContent : "";
    // Paste session: the snippet (or the selected part of it) is the chat context.
    const info = (S.tab === "project" && S.editor.getModel()) || S.session === "paste" ? selectionInfo() : null;
    return {
      session: S.session, projectId: inProject ? S.projectId : null, project,
      file_path: S.tab === "project" ? S.currentPath || "" : "",
      selection: info ? info.code : "", start_line: info ? info.startLine : 1,
    };
  }

  window.IDE = { context, openFile, fileSaved, download, isDirty: (p) => S.dirty.has(p) };
})();
