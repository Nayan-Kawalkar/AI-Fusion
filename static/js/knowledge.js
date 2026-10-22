/* Knowledge Base page: upload, list, delete and test-search documents. */
(function () {
  const { api, el, icon, toast } = CL;
  const $ = (id) => document.getElementById(id);

  async function loadDocs() {
    let data;
    try {
      data = await api("/api/docs");
    } catch (e) {
      toast(e.message);
      return;
    }
    const docs = data.docs;
    const chunks = docs.reduce((n, d) => n + (d.chunks || 0), 0);
    $("docSummary").textContent = docs.length ? `${docs.length} documents · ${chunks} chunks` : "";
    if (!docs.length) {
      $("docTable").replaceChildren(el("div", { class: "muted small py-3", text: "No documents yet. Upload some above — or run `python manage.py load_demo` for the demo set." }));
      return;
    }
    const rows = docs.map((d) => {
      const del = el("button", { class: "btn btn-sm cl-btn", title: "Delete document", "aria-label": `Delete ${d.title}` }, [icon("trash")]);
      del.addEventListener("click", async () => {
        if (!confirm(`Delete “${d.title}” and its ${d.chunks} chunks from the knowledge base?`)) return;
        try {
          await api(`/api/docs/${d.id}`, { method: "DELETE" });
          toast(`Deleted ${d.title}`, "success");
          loadDocs();
        } catch (e) {
          toast(e.message);
        }
      });
      return el("tr", {}, [
        el("td", {}, [icon(d.kind === "pdf" ? "file-earmark-pdf" : "file-earmark-text"), " ", el("span", { class: "fw-semibold", text: d.title })]),
        el("td", { class: "text-uppercase small muted", text: d.kind }),
        el("td", { text: String(d.pages) }),
        el("td", { text: String(d.chunks) }),
        el("td", {}, [el("span", { class: `status-pill ${d.indexed ? "ok" : "no"}`, text: d.indexed ? "Indexed" : "Not indexed" })]),
        el("td", { class: "small muted", text: new Date(d.uploaded_at).toLocaleString() }),
        el("td", { class: "text-end" }, [del]),
      ]);
    });
    $("docTable").replaceChildren(
      el("table", { class: "kb-table" }, [
        el("thead", {}, [el("tr", {}, ["Title", "Type", "Pages", "Chunks", "Status", "Uploaded", ""].map((h) => el("th", { text: h })))]),
        el("tbody", {}, rows),
      ])
    );
  }

  async function upload(files) {
    files = [...files].filter((f) => /\.(pdf|txt|md)$/i.test(f.name));
    if (!files.length) return toast("Only PDF, TXT and MD files are supported.", "warning");
    const form = new FormData();
    files.forEach((f) => form.append("file", f, f.name));
    $("uploadStatus").replaceChildren(el("span", { class: "spinner-border spinner-border-sm me-2" }), document.createTextNode(`Extracting, chunking and embedding ${files.length} file(s)…`));
    try {
      const res = await api("/api/docs/upload", { method: "POST", form });
      const msg = res.docs.map((d) => `${d.title}: ${d.pages} pages → ${d.chunks} chunks`).join(" · ");
      $("uploadStatus").textContent = msg;
      toast(`Indexed ${res.docs.length} document(s)`, "success");
      if (res.errors.length) toast(res.errors.join("\n"), "warning");
    } catch (e) {
      $("uploadStatus").textContent = "";
      toast(`Upload failed: ${e.message}`);
    }
    loadDocs();
  }

  async function search(e) {
    e.preventDefault();
    const q = $("searchInput").value.trim();
    if (!q) return;
    $("searchResults").replaceChildren(el("div", { class: "loading-line" }, [el("span", { class: "spinner-border spinner-border-sm" }), el("span", { text: "Searching…" })]));
    try {
      const r = await api("/api/retrieve", { method: "POST", json: { problem_text: q, code: "", action: "explain" } });
      const badge = el("div", { class: `ground-badge mb-2 ${r.grounded ? "ground-ok" : "ground-no"}` }, [
        icon(r.grounded ? "patch-check-fill" : "exclamation-triangle-fill"),
        el("div", {}, [
          el("div", { class: "gb-title", text: r.grounded ? "Covered by your knowledge base" : "Not found in your knowledge base" }),
          el("div", { class: "gb-sub", text: `Top score ${r.top_score.toFixed(2)} vs threshold ${r.threshold.toFixed(2)}` }),
        ]),
      ]);
      const cards = r.doc_chunks.map((c) => el("div", { class: "chunk-card" }, [
        el("div", { class: "chunk-top" }, [el("span", { class: "cite-n", text: `[${c.n}]` }), el("span", { class: "chunk-src", text: c.label }), el("span", { class: "ms-auto score-val", text: c.score.toFixed(2) })]),
        c.heading ? el("div", { class: "chunk-heading", text: c.heading }) : null,
        el("div", { class: "chunk-preview", text: c.text.replace(/^## .*\n+/, "").slice(0, 500) }),
      ]));
      $("searchResults").replaceChildren(badge, ...(cards.length ? cards : [el("div", { class: "muted small", text: "No chunks found." })]));
    } catch (err) {
      $("searchResults").replaceChildren();
      toast(err.message);
    }
  }

  const dz = $("dropzone");
  dz.addEventListener("click", () => $("docInput").click());
  dz.addEventListener("keydown", (e) => (e.key === "Enter" || e.key === " ") && $("docInput").click());
  dz.addEventListener("dragover", (e) => { e.preventDefault(); dz.classList.add("over"); });
  dz.addEventListener("dragleave", () => dz.classList.remove("over"));
  dz.addEventListener("drop", (e) => { e.preventDefault(); dz.classList.remove("over"); upload(e.dataTransfer.files); });
  $("docInput").addEventListener("change", (e) => { upload(e.target.files); e.target.value = ""; });
  $("searchForm").addEventListener("submit", search);
  loadDocs();
})();
