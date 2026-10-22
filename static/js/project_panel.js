/* Project Overview (whole-project scan) and Chat (ask, explain, fix) views of the AI pane.
   Model text goes through AIPanel.ui.rich (textContent only), never innerHTML. */
window.ProjectPanel = (function () {
  const { api, el, icon, toast } = CL;
  const $ = (id) => document.getElementById(id);
  const ui = () => AIPanel.ui;
  const PASTE_SUGGESTIONS = [
    "Explain this code step by step.",
    "Find the bugs in this code and show the fix.",
    "/python-debugging Why could this crash?",
  ];
  const SUGGESTIONS = [
    "What does this project do? Give me a tour of the main files.",
    "Review the whole project: what bugs or risks do you see?",
    "Why is the order total too low? Fix it.",
    "How do I fix the cart so users don't share items?",
  ];

  let conversationId = null;
  let busy = false;
  let controller = null; // AbortController of the running request, if any
  const diffs = [];

  /* ── Tabs ─────────────────────────────────────────── */
  function showView(name) {
    document.querySelectorAll(".ai-tab").forEach((t) => t.classList.toggle("active", t.dataset.view === name));
    $("aiOverview").classList.toggle("d-none", name !== "overview");
    $("aiChat").classList.toggle("d-none", name !== "chat");
    $("aiPanel").classList.toggle("d-none", name !== "selection");
    if (name === "chat") {
      renderContextChip();
      $("chatInput").focus();
    }
  }

  /* ── Overview ─────────────────────────────────────── */
  async function loadOverview(projectId) {
    const box = $("aiOverview");
    box.replaceChildren(ui().loadingLine("Scanning every file in the project…"));
    let ov;
    try {
      ov = await api(`/api/projects/${projectId}/overview`);
    } catch (e) {
      box.replaceChildren(el("div", { class: "ai-error", text: e.message }));
      return null;
    }
    const t = ov.totals;
    const issues = t.error + t.warning + t.info;
    $("ovBadge").textContent = issues ? String(issues) : "";
    $("ovBadge").className = `tab-badge ${t.error ? "err" : t.warning ? "warn" : ""}`;

    const stat = (value, label) => el("div", { class: "ov-stat" }, [el("b", { text: String(value) }), el("span", { text: label })]);
    const header = el("section", { class: "ai-section summary-card" }, [
      el("div", { class: "sec-body" }, [
        el("div", { class: "ov-title" }, [icon("folder2-open"), el("span", { text: ov.name })]),
        el("div", { class: "ov-stats" }, [
          stat(ov.files, "files"), stat(ov.lines.toLocaleString(), "lines"),
          stat(t.error, "errors"), stat(t.warning, "warnings"),
        ]),
        el("div", { class: "ov-langs" }, ov.languages.map(([lang, n]) => el("span", { class: "query-chip", text: `${lang} · ${n}` }))),
        el("div", { class: "ov-actions" }, [
          actionBtn("stars", "Ask AI to review the project", "cl-btn-primary", () => ask(SUGGESTIONS[1])),
          actionBtn("download", "Download .zip", "cl-btn", () => IDE.download()),
        ]),
        el("div", { class: "muted small mt-2", text: "Static scan only (ast + pyflakes) — the code is never run." }),
      ]),
    ]);

    const byFile = {};
    for (const p of ov.problems) (byFile[p.path] = byFile[p.path] || []).push(p);
    const groups = Object.entries(byFile).map(([path, list]) => el("div", { class: "ov-file" }, [
      el("div", { class: "ov-file-head" }, [icon("file-earmark-code"), el("span", { class: "mono", text: path }), el("span", { class: "sec-meta", text: String(list.length) })]),
      ...list.map((p) => {
        const row = el("button", { type: "button", class: "ov-problem", title: "Open at this line" }, [
          el("span", { class: `sev-dot ${p.severity}` }),
          el("span", { class: "mono ov-line", text: `L${p.line}` }),
          el("span", { class: "ov-msg", text: p.message }),
          el("span", { class: "ov-code", text: p.code }),
        ]);
        row.addEventListener("click", () => IDE.openFile(path, p.line));
        return row;
      }),
    ]));
    const problems = ui().section("exclamation-diamond", `Problems (${issues})`, "click to open", groups.length ? groups
      : [el("div", { class: "muted small", text: "No static-analysis problems found. Ask the AI in Chat to look for logic bugs." })]);

    const files = ui().foldable(null, "Files", `${ov.files}`, [el("div", { class: "ov-files" }, ov.per_file.map((f) => {
      const row = el("button", { type: "button", class: "ov-filerow" }, [
        el("span", { class: "mono", text: f.path }),
        el("span", { class: "muted", text: `${f.lines} lines` }),
        f.errors ? el("span", { class: "tab-badge err", text: String(f.errors) }) : f.warnings ? el("span", { class: "tab-badge warn", text: String(f.warnings) }) : null,
      ]);
      row.addEventListener("click", () => IDE.openFile(f.path));
      return row;
    }))], false);
    box.replaceChildren(header, problems, files);
    return ov;
  }

  function actionBtn(iconName, label, cls, onClick) {
    const b = el("button", { type: "button", class: `btn btn-sm ${cls}` }, [icon(iconName), ` ${label}`]);
    b.addEventListener("click", onClick);
    return b;
  }

  /* ── Chat ─────────────────────────────────────────── */
  function resetChat() {
    stop();
    conversationId = null;
    diffs.splice(0).forEach((d) => d.dispose());
    const paste = window.IDE && IDE.context().session === "paste";
    const sugg = el("div", { class: "chat-suggest" }, (paste ? PASTE_SUGGESTIONS : SUGGESTIONS).map((s) => {
      const b = el("button", { type: "button", class: "suggest", text: s });
      b.addEventListener("click", () => ask(s));
      return b;
    }));
    $("chatLog").replaceChildren(el("div", { class: "chat-empty" }, [
      el("div", { class: "ai-empty-title", text: "Chat with your project" }),
      el("div", { class: "ai-empty-sub" }, [
        "Ask how something works, why it breaks, or ask for a change. Answers use your docs and the whole codebase, and edits are shown as diffs for you to apply. Type ",
        el("kbd", { text: "/" }), " to pick a ", el("a", { href: "/skills/", text: "skill" }), " that focuses the search on the right docs.",
      ]),
      sugg,
    ]));
  }

  function renderContextChip() {
    const ctx = IDE.context();
    const box = $("chatContext");
    if (ctx.session === "paste") {
      const n = ctx.selection.trim() ? ctx.selection.split("\n").length : 0;
      box.replaceChildren(el("span", { class: "ctx-chip" }, [icon("clipboard"), n ? ` Pasted code · ${n} lines` : " Paste session · paste code to discuss it"]));
      return;
    }
    if (!ctx.project) {
      box.replaceChildren(el("span", { class: "ctx-chip muted" }, [icon("journal-text"), " Docs only"]));
      return;
    }
    const label = ctx.selection ? `${ctx.file_path}:${ctx.start_line}–${ctx.start_line + ctx.selection.split("\n").length - 1}` : ctx.file_path || "whole project";
    box.replaceChildren(el("span", { class: "ctx-chip" }, [icon("paperclip"), ` ${ctx.project} · ${label}`]));
  }

  function ask(text) {
    showView("chat");
    $("chatInput").value = text;
    send();
  }

  async function send() {
    const input = $("chatInput");
    const message = input.value.trim();
    if (busy) return; // the button is a Stop button while busy; Enter waits for the answer
    if (!message) {
      input.focus();
      return;
    }
    controller = new AbortController();
    const { signal } = controller;
    setBusy(true);
    input.value = "";
    autoSize();
    const log = $("chatLog");
    log.querySelector(".chat-empty")?.remove();
    log.appendChild(el("div", { class: "msg user" }, [el("div", { class: "bubble", text: message })]));
    $("chatSkill").classList.add("d-none");
    const turn = el("div", { class: "msg bot" });
    const status = timedLine("Searching your docs and project…");
    turn.appendChild(status);
    log.appendChild(turn);
    scrollDown();

    const ctx = IDE.context();
    let r;
    try {
      r = await api("/api/chat/retrieve", {
        method: "POST",
        json: { project_id: ctx.projectId, conversation_id: conversationId, message, mode: $("modeSelect").value,
                file_path: ctx.file_path, selection: ctx.selection, start_line: ctx.start_line },
        signal,
      });
      conversationId = r.conversation_id;
    } catch (e) {
      status.stop();
      status.replaceWith(e instanceof CL.Cancelled ? stoppedNote() : el("div", { class: "ai-error", text: e.message }));
      return done();
    }
    status.stop();
    const scope = { cites: Object.fromEntries(r.citations.map((c) => [c.n, c])), terms: ui().termsFrom(r.queries) };
    const sources = [...r.doc_chunks, ...r.code_chunks];
    const scopeNote = r.skill ? `/${r.skill.name}: ${r.skill.scoped ? `${r.skill.docs.length} docs` : "all docs"} · ` : "";
    const inspector = ui().foldable("search", r.skill ? `Sources via /${r.skill.name}` : "Sources", `${scopeNote}${sources.length} found · ${r.latency_ms} ms`,
      sources.length ? sources.map((c) => ui().chunkCard(c, r.threshold, scope)) : [el("div", { class: "muted small", text: "Nothing relevant was found." })], false);
    status.replaceWith(inspector);
    const writing = timedLine(r.focus_files.length ? `Reading ${r.focus_files.join(", ")} and writing an answer…` : "Writing an answer…");
    turn.appendChild(writing);
    scrollDown();

    try {
      const res = await api("/api/chat/answer", { method: "POST", json: { query_id: r.query_id }, signal });
      writing.stop();
      writing.replaceWith(renderAnswer(res.answer, scope, res, r.query_id));
      const cited = new Set(res.answer.used_citations);
      inspector.querySelectorAll(".chunk-card").forEach((c) => c.classList.toggle("cited", cited.has(Number(c.dataset.n))));
      inspector.setMeta(`${sources.length} found · ${cited.size} cited`);
    } catch (e) {
      writing.stop();
      writing.replaceWith(e instanceof CL.Cancelled ? stoppedNote()
        : el("div", { class: "ai-error", text: `Couldn't generate an answer: ${e.message}` }));
    }
    done();
    scrollDown();
  }

  function done() {
    controller = null;
    setBusy(false);
  }

  /* Abort the running request (Stop button, Esc, or New chat). */
  function stop() {
    if (controller) controller.abort();
  }

  /* While busy the Send button becomes Stop; typing stays possible. */
  function setBusy(on) {
    busy = on;
    const btn = $("chatSend");
    btn.classList.toggle("is-stop", on);
    btn.title = on ? "Stop (Esc)" : "Send (Enter)";
    btn.setAttribute("aria-label", on ? "Stop generating" : "Send message");
    btn.replaceChildren(icon(on ? "stop-fill" : "send"));
  }

  function stoppedNote() {
    return el("div", { class: "stopped-note" }, [icon("pause-circle"), " Stopped. Edit your question or send a new one."]);
  }

  /* Loading line with a live seconds counter so long answers don't look frozen. */
  function timedLine(text) {
    const secs = el("span", { class: "elapsed" });
    const line = el("div", { class: "loading-line" }, [
      el("span", { class: "spinner-border spinner-border-sm", role: "status" }), el("span", { text }), secs,
    ]);
    const started = Date.now();
    const timer = setInterval(() => {
      const s = Math.round((Date.now() - started) / 1000);
      secs.textContent = s >= 3 ? `${s}s` : "";
    }, 1000);
    line.stop = () => clearInterval(timer);
    return line;
  }

  function renderAnswer(a, scope, res, queryId) {
    const box = el("div", { class: "bot-answer" });
    if (a.offline) {
      box.appendChild(ui().offlineBanner(a.offline_reason, async () => {
        try {
          const again = await api("/api/chat/answer", { method: "POST", json: { query_id: queryId } });
          box.replaceWith(renderAnswer(again.answer, scope, again, queryId));
        } catch (e) {
          toast(e.message);
          box.replaceWith(renderAnswer(a, scope, res, queryId));
        }
      }));
    }
    const reply = el("div", { class: "bubble bot-bubble" }, [ui().rich(a.reply || "(no answer)", scope)]);
    box.appendChild(reply);
    const meta = [];
    meta.push(el("span", { class: `gb-pill ${a.grounded ? "ok" : "no"}` }, [icon(a.grounded ? "patch-check-fill" : "exclamation-triangle-fill"),
      a.grounded ? " Grounded in your docs" : " Not found in your knowledge base"]));
    a.used_citations.forEach((n) => {
      const b = ui().citeButton(n, scope);
      if (b) meta.push(el("span", { class: "source-chip" }, [b, el("span", { text: scope.cites[n].label })]));
    });
    if (res.cached) meta.push(el("span", { class: "muted small", text: "cached" }));
    else if (!a.offline && res.latency_ms) meta.push(el("span", { class: "muted small", text: `${(res.latency_ms / 1000).toFixed(1)} s` }));
    box.appendChild(el("div", { class: "source-chips" }, meta));
    if (a.edits.length) box.appendChild(renderEdits(a.edits));
    if (a.general_notes) {
      box.appendChild(ui().section("globe2", "General AI knowledge (unverified)", "not from your docs",
        [ui().rich(a.general_notes, scope)], "general-notes"));
    }
    return box;
  }

  /* ── Proposed edits ───────────────────────────────── */
  function renderEdits(edits) {
    const wrap = el("div", { class: "edits" }, [el("div", { class: "sub-label", text: `Proposed changes (${edits.length})` })]);
    const appliers = [];
    for (const e of edits) {
      const host = el("div", { class: "diff-host" });
      const lines = Math.max(e.original.split("\n").length, e.content.split("\n").length);
      host.style.height = `${Math.min(320, Math.max(110, lines * 17 + 30))}px`;
      const applyBtn = el("button", { type: "button", class: "btn btn-sm cl-btn-primary" }, [icon("check2-square"), " Apply"]);
      const openBtn = el("button", { type: "button", class: "btn btn-sm cl-btn" }, [icon("box-arrow-up-right"), " Open"]);
      const state = el("span", { class: "muted small ms-auto" });
      let applied = false;
      const apply = async () => {
        if (applied) return true;
        if (IDE.isDirty(e.path) && !confirm(`${e.path} has unsaved editor changes. Replace them with this change?`)) return false;
        applyBtn.disabled = true;
        try {
          await api(`/api/projects/${IDE.context().projectId}/file`, { method: "POST", json: { path: e.path, content: e.content } });
        } catch (err) {
          toast(`Couldn't apply ${e.path}: ${err.message}`);
          applyBtn.disabled = false;
          return false;
        }
        applied = true;
        await IDE.fileSaved(e.path, e.content);
        applyBtn.replaceChildren(icon("arrow-counterclockwise"), " Undo");
        applyBtn.disabled = false;
        applyBtn.classList.replace("cl-btn-primary", "cl-btn");
        state.textContent = "Applied — saved to the project copy";
        return true;
      };
      const undo = async () => {
        applyBtn.disabled = true;
        try {
          if (e.action === "create") await api(`/api/projects/${IDE.context().projectId}/file?path=${encodeURIComponent(e.path)}`, { method: "DELETE" });
          else await api(`/api/projects/${IDE.context().projectId}/file`, { method: "POST", json: { path: e.path, content: e.original } });
        } catch (err) {
          toast(`Couldn't undo: ${err.message}`);
          applyBtn.disabled = false;
          return;
        }
        applied = false;
        await IDE.fileSaved(e.path, e.action === "create" ? null : e.original);
        applyBtn.replaceChildren(icon("check2-square"), " Apply");
        applyBtn.classList.replace("cl-btn", "cl-btn-primary");
        applyBtn.disabled = false;
        state.textContent = "Change undone";
      };
      applyBtn.addEventListener("click", () => (applied ? undo() : apply()));
      openBtn.addEventListener("click", () => IDE.openFile(e.path));
      appliers.push(apply);
      wrap.appendChild(el("div", { class: "edit-card" }, [
        el("div", { class: "edit-head" }, [
          el("span", { class: `edit-kind ${e.action}`, text: e.action === "create" ? "new file" : "modify" }),
          el("span", { class: "mono edit-path", text: e.path }),
        ]),
        e.summary ? el("div", { class: "edit-summary", text: e.summary }) : null,
        host,
        el("div", { class: "diff-actions" }, [applyBtn, e.action === "create" ? null : openBtn, state]),
      ]));
      requestIdle(() => diffs.push(DiffView.create(host, e.original, e.content, languageFor(e.path))));
    }
    if (edits.length > 1) {
      const all = el("button", { type: "button", class: "btn btn-sm cl-btn-primary" }, [icon("check2-all"), ` Apply all ${edits.length} changes`]);
      all.addEventListener("click", async () => {
        for (const apply of appliers) if (!(await apply())) break;
      });
      wrap.appendChild(all);
    }
    return wrap;
  }

  // Mount after the card is in the DOM (setTimeout, not rAF: rAF pauses in background tabs).
  function requestIdle(fn) { setTimeout(fn, 0); }

  function languageFor(path) {
    const ext = (path.split(".").pop() || "").toLowerCase();
    return { py: "python", js: "javascript", ts: "typescript", html: "html", css: "css", json: "json", md: "markdown" }[ext] || "plaintext";
  }

  /* ── Composer ─────────────────────────────────────── */
  function autoSize() {
    const t = $("chatInput");
    t.style.height = "auto";
    t.style.height = `${Math.min(140, t.scrollHeight)}px`;
  }

  function scrollDown() {
    const log = $("chatLog");
    log.scrollTop = log.scrollHeight;
  }

  function init() {
    document.querySelectorAll(".ai-tab").forEach((t) => t.addEventListener("click", () => showView(t.dataset.view)));
    $("chatForm").addEventListener("submit", (e) => { e.preventDefault(); busy ? stop() : send(); });
    $("chatInput").addEventListener("keydown", (e) => {
      if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); send(); }
      else if (e.key === "Escape" && busy) { e.preventDefault(); stop(); }
    });
    $("chatInput").addEventListener("input", autoSize);
    SlashMenu.attach($("chatInput"), { chip: $("chatSkill") });
    $("chatNew").addEventListener("click", resetChat);
    resetChat();
    $("aiOverview").replaceChildren(el("div", { class: "ai-empty" }, [
      el("div", { class: "ai-empty-title", text: "Project overview" }),
      el("div", { class: "ai-empty-sub", text: "Open a folder or .zip and every file is scanned here: problems across the whole project, file sizes and languages." }),
    ]));
  }

  return { init, showView, loadOverview, resetChat, ask, renderContextChip };
})();
