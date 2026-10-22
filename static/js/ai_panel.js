/* Right-hand AI panel: Retrieval Inspector → grounding badge → answer.
   All model text is inserted with textContent (via CL.el), never innerHTML. */
window.AIPanel = (function () {
  const { el, icon, api, toast } = CL;
  const CITE_RE = /\[(\d+)\]/g;
  const STOP = new Set(["python", "the", "and", "for", "with", "this", "that", "from", "self", "return", "none", "true", "false", "import", "def", "class", "what", "does", "why", "how"]);

  let root = null;
  let handlers = {};
  let citations = {};   // n -> {id, source_type, label}
  let queryTerms = [];
  let answerSlot = null;
  let groundBadge = null;
  let inspector = null;
  let stepper = null;
  let diffView = null;
  let modal = null;

  /* ── Progress stepper: Retrieve → Grounding → Answer ── */
  const STEPS = ["Retrieve context", "Check grounding", "Generate answer"];

  function makeStepper() {
    stepper = el("ol", { class: "stepper", "aria-label": "Progress" }, STEPS.map((label) =>
      el("li", { class: "st" }, [el("span", { class: "st-dot" }), el("span", { class: "st-label", text: label })])));
    return stepper;
  }

  /* states: idle | active | done | warn | error */
  function setSteps(...states) {
    if (!stepper) return;
    [...stepper.children].forEach((li, i) => { li.className = `st ${states[i] || "idle"}`; });
  }

  function init(container, opts) {
    root = container;
    handlers = opts;
    modal = new bootstrap.Modal(document.getElementById("chunkModal"));
    showEmpty(null);
  }

  function disposeDiff() {
    if (diffView) diffView.dispose();
    diffView = null;
  }

  function section(step, title, meta, body, extraClass = "") {
    return el("section", { class: `ai-section ${extraClass}` }, [
      el("div", { class: "sec-head" }, [
        typeof step === "string" ? el("i", { class: `bi bi-${step} sec-icon`, "aria-hidden": "true" })
          : step ? el("span", { class: "step", text: String(step) }) : null,
        el("span", { text: title }),
        meta ? el("span", { class: "sec-meta", text: meta }) : null,
      ]),
      el("div", { class: "sec-body" }, body),
    ]);
  }

  /* A section that folds to its header (native <details>, keyboard accessible). */
  function foldable(step, title, meta, body, open = true, extraClass = "") {
    const metaEl = el("span", { class: "sec-meta", text: meta || "" });
    const node = el("details", { class: `ai-section foldable ${extraClass}`, open: open || null }, [
      el("summary", { class: "sec-head" }, [
        typeof step === "string" ? el("i", { class: `bi bi-${step} sec-icon`, "aria-hidden": "true" })
          : step ? el("span", { class: "step", text: String(step) }) : null,
        el("span", { text: title }),
        metaEl,
        el("i", { class: "bi bi-chevron-down fold-chev", "aria-hidden": "true" }),
      ]),
      el("div", { class: "sec-body" }, body),
    ]);
    node.setMeta = (text) => { metaEl.textContent = text; };
    return node;
  }

  function loadingLine(text) {
    return el("div", { class: "loading-line" }, [el("span", { class: "spinner-border spinner-border-sm", role: "status" }), el("span", { text })]);
  }

  /* ── Empty / loading / error ───────────────────────── */
  function showEmpty(kbCount) {
    disposeDiff();
    // null = count not loaded yet; say nothing rather than something wrong.
    const kbNote = kbCount === null ? null : kbCount
      ? el("p", { class: "mt-3", text: `${kbCount} document${kbCount === 1 ? "" : "s"} in your knowledge base.` })
      : el("p", { class: "mt-3" }, [
          "No documentation uploaded yet — answers can't be grounded. ",
          el("a", { href: "/knowledge/", text: "Add docs to the Knowledge Base" }),
          ".",
        ]);
    const how = (n, title, text) => el("li", { class: "how-step" }, [
      el("span", { class: "how-n", text: String(n) }),
      el("div", {}, [el("div", { class: "how-title", text: title }), el("div", { class: "how-text", text })]),
    ]);
    root.replaceChildren(
      el("div", { class: "ai-empty" }, [
        el("div", { class: "ai-empty-title", text: "Ask about any code" }),
        el("div", { class: "ai-empty-sub" }, [
          "Select lines in the editor, then press ",
          el("kbd", { text: "Ctrl+Shift+E" }), " to explain or ", el("kbd", { text: "Ctrl+Shift+D" }), " to debug.",
        ]),
        el("ol", { class: "how" }, [
          how(1, "Retrieve", "Your docs and project are searched first."),
          how(2, "Inspect", "You see every source found, with its score."),
          how(3, "Answer", "The AI answers using only those sources, with [n] citations."),
        ]),
        kbNote,
      ])
    );
  }

  function showRetrieving(action) {
    disposeDiff();
    inspector = foldable(1, "Retrieval Inspector", action === "debug" ? "Debug" : "Explain", [
      loadingLine("Searching your docs and project…"),
      el("div", { class: "skeleton" }),
      el("div", { class: "skeleton", style: { width: "70%" } }),
    ]);
    root.replaceChildren(makeStepper(), inspector);
    setSteps("active");
  }

  function renderError(message) {
    disposeDiff();
    setSteps("error");
    root.replaceChildren(...(stepper ? [stepper] : []), el("div", { class: "ai-error" }, [icon("exclamation-octagon"), " ", message]));
  }

  /* ── Retrieval Inspector ───────────────────────────── */
  function scoreColor(chunk, threshold) {
    if (chunk.source_type === "code") return "var(--violet)";
    return chunk.score >= threshold ? "var(--green)" : "var(--amber)";
  }

  function chunkCard(c, threshold, scope) {
    const pct = Math.max(2, Math.min(100, Math.round(c.score * 100)));
    const card = el("button", {
      type: "button", class: "chunk-card", "data-n": c.n,
      title: `Matched by ${c.via.join(" + ")} · click to read the full passage`,
    }, [
      el("div", { class: "chunk-top" }, [
        el("span", { class: `cite-n ${c.source_type === "code" ? "code" : ""}`, text: `[${c.n}]` }),
        el("span", { class: "chunk-src", text: c.heading || c.label }),
        el("span", { class: "score-val", text: c.score.toFixed(2) }),
      ]),
      el("div", { class: "chunk-meta" }, [icon(c.source_type === "code" ? "code-slash" : "journal-text"), el("span", { text: c.label })]),
      el("div", { class: "score-bar" }, [el("span", { style: { width: `${pct}%`, background: scoreColor(c, threshold) } })]),
      el("div", { class: "chunk-preview", text: c.text.replace(/^## .*\n+/, "").slice(0, 300) }),
    ]);
    card.addEventListener("click", () => openChunk(c.id, c.n, scope && scope.terms));
    return card;
  }

  function termsFrom(queries) {
    const words = new Set();
    for (const q of queries) {
      for (const w of q.match(/[A-Za-z_][A-Za-z0-9_]{3,}/g) || []) {
        const lw = w.toLowerCase();
        if (!STOP.has(lw)) words.add(lw);
      }
    }
    return [...words].slice(0, 30);
  }

  function renderRetrieval(r, ctx) {
    disposeDiff();
    citations = {};
    for (const c of r.citations) citations[c.n] = c;
    queryTerms = termsFrom(r.queries);

    const body = [
      el("details", { class: "queries" }, [
        el("summary", { text: `How we searched · ${r.queries.length} queries` }),
        el("div", { class: "query-chips" }, r.queries.map((q) => el("span", { class: "query-chip", title: q, text: q.split("\n")[0].slice(0, 90) }))),
      ]),
    ];
    if (r.findings.length) {
      body.push(el("div", { class: "sub-label", text: `Static findings in selection (${r.findings.length})` }));
      body.push(el("ul", { class: "finding-list" }, r.findings.map((f) =>
        el("li", {}, [el("span", { class: `sev-dot ${f.severity}` }), el("span", { class: "mono", text: `L${f.line}` }), el("span", { text: `${f.code}: ${f.message}` })]))));
    }
    body.push(el("div", { class: "sub-label", text: `Documentation (${r.doc_chunks.length})` }));
    if (r.doc_chunks.length) body.push(...r.doc_chunks.map((c) => chunkCard(c, r.threshold)));
    else body.push(el("div", { class: "muted small" }, ["No documents indexed. ", el("a", { href: "/knowledge/", text: "Upload docs" }), "."]));
    if (ctx.hasProject) {
      body.push(el("div", { class: "sub-label", text: `Related project code (${r.code_chunks.length})` }));
      if (r.code_chunks.length) body.push(...r.code_chunks.map((c) => chunkCard(c, r.threshold)));
      else body.push(el("div", { class: "muted small", text: "No related code found." }));
    }

    const score = `Best documentation match ${r.top_score.toFixed(2)}`;
    groundBadge = el("div");
    if (r.grounded) {
      setBadge("pending", "Relevant docs found", `${score} ≥ threshold ${r.threshold.toFixed(2)} · confirming the answer cites them…`);
    } else {
      setBadge("no", "Not found in your knowledge base", `${score} < threshold ${r.threshold.toFixed(2)} — the answer will use general AI knowledge, clearly labelled.`);
    }

    answerSlot = el("div", { class: "d-flex flex-column gap-3" }, [
      section(3, "Answer", null, [loadingLine("Writing the answer from these sources…"), el("div", { class: "skeleton" }), el("div", { class: "skeleton", style: { width: "85%" } }), el("div", { class: "skeleton", style: { width: "60%" } })]),
    ]);
    const total = r.doc_chunks.length + r.code_chunks.length;
    if (r.skill) {
      body.unshift(el("div", { class: "skill-note" }, [icon("magic"), ` Skill /${r.skill.name} — ${r.skill.scoped ? `searched only: ${r.skill.docs.join(", ") || "no matching docs"}` : "searched all docs"}`]));
    }
    inspector = foldable(1, r.skill ? `Retrieval Inspector · /${r.skill.name}` : "Retrieval Inspector", `${total} sources · ${r.latency_ms} ms`, body);
    root.replaceChildren(stepper || makeStepper(), inspector, groundBadge, answerSlot);
    setSteps("done", r.grounded ? "done" : "warn", "active");
  }

  /* After the answer: fold the inspector to one line and mark the cited sources. */
  function collapseInspector(a) {
    if (!inspector) return;
    const cited = new Set(a.used_citations);
    inspector.querySelectorAll(".chunk-card").forEach((card) => card.classList.toggle("cited", cited.has(Number(card.dataset.n))));
    const total = inspector.querySelectorAll(".chunk-card").length;
    inspector.setMeta(`${total} sources · ${cited.size} cited`);
    inspector.open = false;
  }

  /* state: ok | pending | no */
  function setBadge(state, title, sub) {
    const cls = state === "no" ? "ground-no" : state === "ok" ? "ground-ok" : "ground-pending";
    const iconName = state === "no" ? "exclamation-triangle-fill" : state === "ok" ? "patch-check-fill" : "search";
    groundBadge.className = `ground-badge ${cls}`;
    groundBadge.replaceChildren(icon(iconName), el("div", {}, [el("div", { class: "gb-title", text: title }), el("div", { class: "gb-sub", text: sub })]));
  }

  function finalizeBadge(a) {
    if (a.grounded) {
      const docs = a.used_citations.filter((n) => citations[n] && citations[n].source_type === "doc");
      setBadge("ok", "Grounded in your docs", `The answer cites ${docs.map((n) => `[${n}]`).join(" ")} from your knowledge base.`);
    } else if (a.retrieval_grounded) {
      setBadge("no", "Not found in your knowledge base", "Docs matched your code, but none of them answered the question — the answer uses general AI knowledge, clearly labelled.");
    }
  }

  /* ── Rich text (safe) ─────────────────────────────── */
  /* scope = {cites, terms} lets chat messages carry their own citation map. */
  function inline(parent, text, scope) {
    const re = /(`[^`\n]+`|\*\*[^*\n]+\*\*|\[\d+\])/g;
    let last = 0;
    let m;
    const pushText = (t) => {
      t.split("\n").forEach((line, i) => {
        if (i) parent.appendChild(el("br"));
        if (line) parent.appendChild(document.createTextNode(line));
      });
    };
    while ((m = re.exec(text))) {
      pushText(text.slice(last, m.index));
      const tok = m[0];
      if (tok.startsWith("`")) parent.appendChild(el("code", { text: tok.slice(1, -1) }));
      else if (tok.startsWith("**")) parent.appendChild(el("strong", { text: tok.slice(2, -2) }));
      else parent.appendChild(citeButton(Number(tok.slice(1, -1)), scope) || document.createTextNode(tok));
      last = m.index + tok.length;
    }
    pushText(text.slice(last));
  }

  function rich(text, scope) {
    const frag = document.createDocumentFragment();
    const parts = (text || "").split(/```[\w+-]*\n?([\s\S]*?)```/g);
    parts.forEach((part, i) => {
      if (i % 2 === 1) {
        frag.appendChild(el("pre", {}, [el("code", { text: part.replace(/\n$/, "") })]));
        return;
      }
      for (const para of part.split(/\n{2,}/)) {
        if (!para.trim()) continue;
        const lines = para.trim().split("\n");
        const bullet = lines.every((l) => /^\s*([-*]|\d+[.)])\s+/.test(l));
        if (bullet) {
          const ordered = /^\s*\d/.test(lines[0]);
          const list = el(ordered ? "ol" : "ul", { class: "mb-2 ps-3" });
          for (const l of lines) {
            const li = el("li");
            inline(li, l.replace(/^\s*([-*]|\d+[.)])\s+/, ""), scope);
            list.appendChild(li);
          }
          frag.appendChild(list);
        } else {
          const p = el("p");
          inline(p, para.trim(), scope);
          frag.appendChild(p);
        }
      }
    });
    return frag;
  }

  function citeButton(n, scope) {
    const c = (scope ? scope.cites : citations)[n];
    if (!c) return null;
    const btn = el("button", { class: `cite-btn ${c.source_type === "code" ? "code" : ""}`, type: "button", title: c.label, text: `[${n}]` });
    btn.addEventListener("click", () => openChunk(c.id, n, scope && scope.terms));
    return btn;
  }

  /* ── Answer ───────────────────────────────────────── */
  function renderAnswer(res, ctx) {
    const a = res.answer;
    const blocks = [];
    const afterMount = [];
    const debug = ctx.action === "debug";
    finalizeBadge(a);
    collapseInspector(a);
    setSteps("done", a.grounded ? "done" : "warn", a.offline ? "warn" : "done");
    const meta = a.offline ? "without AI" : `${res.cached ? "cached · " : ""}${(res.latency_ms / 1000).toFixed(1)} s`;
    if (a.offline) blocks.push(offlineBanner(a.offline_reason, () => handlers.onRetry(res.query_id)));

    // Summary card: the one-paragraph takeaway plus the sources it relies on.
    const summaryBody = [];
    if (a.summary) summaryBody.push(el("div", { class: "summary-text" }, [rich(a.summary)]));
    if (!debug && a.explanation) summaryBody.push(rich(a.explanation));
    if (!a.summary && !a.explanation) summaryBody.push(el("p", { class: "muted", text: "The model returned no explanation." }));
    if (a.used_citations.length) {
      summaryBody.push(el("div", { class: "source-chips" }, a.used_citations.map((n) => {
        const b = citeButton(n);
        return b ? el("span", { class: "source-chip" }, [b, el("span", { text: citations[n].label })]) : null;
      })));
    }
    blocks.push(section(debug ? "bug" : "lightbulb", debug ? "Diagnosis" : "Explanation", meta, summaryBody, "summary-card"));

    if (a.issues.length) {
      const items = a.issues.map((iss) => {
        const reason = el("div", { class: "issue-reason" });
        reason.appendChild(rich(iss.reason));
        const node = el("div", { class: `issue ${iss.severity}`, title: iss.line ? `Jump to line ${iss.line}` : "" }, [
          el("span", { class: "sev" }),
          el("div", { class: "flex-grow-1" }, [
            el("div", {}, [el("span", { class: "issue-title", text: iss.title }), iss.line ? el("span", { class: "issue-line", text: `line ${iss.line}` }) : null]),
            reason,
          ]),
        ]);
        node.addEventListener("click", (e) => {
          if (e.target.closest(".cite-btn")) return;
          if (iss.line) handlers.onJump(iss.line);
        });
        return node;
      });
      blocks.push(section("exclamation-diamond", `Issues (${a.issues.length})`, "click to jump to the line", items));
    }

    if (a.fixed_code) {
      const host = el("div", { class: "diff-host" });
      const applyBtn = el("button", { class: "btn btn-sm cl-btn-primary", type: "button" }, [icon("check2-square"), " Apply fix"]);
      const copyBtn = el("button", { class: "btn btn-sm cl-btn", type: "button" }, [icon("clipboard"), " Copy"]);
      applyBtn.addEventListener("click", () => {
        if (handlers.onApplyFix(a.fixed_code)) {
          applyBtn.disabled = true;
          applyBtn.replaceChildren(icon("check2"), " Applied to editor");
        }
      });
      copyBtn.addEventListener("click", async () => {
        try {
          await navigator.clipboard.writeText(a.fixed_code);
          toast("Fix copied to clipboard", "success");
        } catch (e) {
          toast("Could not access the clipboard");
        }
      });
      const fixBody = [host, el("div", { class: "diff-actions" }, [applyBtn, copyBtn, el("span", { class: "muted small ms-auto", text: "Edits the editor buffer only" })])];
      if (a.fix_explanation) {
        const fe = el("div", { class: "mt-2" });
        fe.appendChild(rich(a.fix_explanation));
        fixBody.push(fe);
      }
      blocks.push(section("wrench-adjustable", "Suggested fix", `lines ${ctx.startLine}–${ctx.startLine + ctx.code.split("\n").length - 1}`, fixBody));
      const lines = Math.max(ctx.code.split("\n").length, a.fixed_code.split("\n").length);
      host.style.height = `${Math.min(420, Math.max(120, lines * 19 + 40))}px`;
      afterMount.push(() => {
        diffView = DiffView.create(host, ctx.code, a.fixed_code, ctx.language, ctx.startLine);
      });
    }

    if (a.hints.length) {
      const list = el("ol", { class: "hint-list" });
      a.hints.forEach((h, i) => {
        const li = el("li", { class: i === 0 ? "" : "locked", title: i === 0 ? "" : "Click to reveal" });
        li.appendChild(rich(h));
        li.addEventListener("click", () => li.classList.remove("locked"));
        list.appendChild(li);
      });
      blocks.push(section("signpost-split", "Hints", "click to reveal the next one", [list]));
    }

    // In Debug the full reasoning comes after the fix, folded by default.
    if (debug && a.explanation) {
      blocks.push(foldable(null, "Why this happens", "full explanation", [rich(a.explanation)], false));
    }

    if (a.general_notes) {
      blocks.push(section("globe2", "General AI knowledge (unverified)", "not from your docs", [
        el("div", { class: "muted small mb-2", text: "This part is not supported by your knowledge base. Verify it before relying on it." }),
        rich(a.general_notes),
      ], "general-notes"));
    }
    answerSlot.replaceChildren(...blocks);
    afterMount.forEach((fn) => fn());
  }

  /* Shown when every model failed: the answer below is sources-only, with a Retry. */
  function offlineBanner(text, onRetry) {
    const retry = el("button", { type: "button", class: "btn btn-sm cl-btn" }, [icon("arrow-clockwise"), " Retry"]);
    retry.addEventListener("click", () => {
      retry.disabled = true;
      retry.replaceChildren(el("span", { class: "spinner-border spinner-border-sm" }), " Retrying…");
      onRetry();
    });
    return el("div", { class: "offline-banner" }, [
      icon("cloud-slash"),
      el("div", { class: "flex-grow-1" }, [el("div", { class: "fw-semibold", text: "AI temporarily unavailable" }), el("div", { class: "small", text })]),
      retry,
    ]);
  }

  function renderAnswerError(message) {
    if (!answerSlot) return renderError(message);
    setSteps("done", stepper && stepper.children[1].classList.contains("warn") ? "warn" : "done", "error");
    answerSlot.replaceChildren(
      el("div", { class: "ai-error" }, [icon("exclamation-octagon"), " ", /^Stopped/.test(message) ? message : `Answer generation failed: ${message}`, el("div", { class: "small mt-1", text: "The retrieval above is still valid." })])
    );
  }

  /* ── Citation modal ───────────────────────────────── */
  function highlighted(text, terms) {
    const frag = document.createDocumentFragment();
    if (!terms.length) {
      frag.appendChild(document.createTextNode(text));
      return frag;
    }
    const escaped = terms.map((t) => t.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
    const re = new RegExp(`(${escaped.join("|")})`, "gi");
    let last = 0;
    let m;
    while ((m = re.exec(text))) {
      frag.appendChild(document.createTextNode(text.slice(last, m.index)));
      frag.appendChild(el("mark", { text: m[0] }));
      last = m.index + m[0].length;
    }
    frag.appendChild(document.createTextNode(text.slice(last)));
    return frag;
  }

  async function openChunk(chromaId, n, terms) {
    const card = root.querySelector(`.chunk-card[data-n="${n}"]`);
    if (card) {
      card.classList.add("flash");
      setTimeout(() => card.classList.remove("flash"), 1400);
    }
    let c;
    try {
      c = await api(`/api/chunk/${encodeURIComponent(chromaId)}`);
    } catch (e) {
      toast(e.message);
      return;
    }
    document.getElementById("chunkModalTitle").textContent = `${n ? `[${n}] ` : ""}${c.label}`;
    document.getElementById("chunkModalMeta").textContent = c.heading ? `Section: ${c.heading}` : c.source_type === "code" ? "Project code" : "Documentation";
    document.getElementById("chunkModalBody").replaceChildren(highlighted(c.text, terms || queryTerms));
    const openBtn = document.getElementById("chunkModalOpen");
    openBtn.classList.toggle("d-none", c.source_type !== "code");
    openBtn.onclick = () => {
      modal.hide();
      handlers.onOpenFile(c.path, c.start_line);
    };
    modal.show();
  }

  // Shared building blocks for the chat panel.
  const ui = { rich, citeButton, chunkCard, foldable, section, termsFrom, loadingLine, offlineBanner };

  return { init, showEmpty, showRetrieving, renderRetrieval, renderAnswer, renderAnswerError, renderError, ui };
})();
