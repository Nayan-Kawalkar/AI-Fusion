/* Skills page: list, upload, write, refresh and delete SKILL.md packs. */
(function () {
  const { api, el, icon, toast } = CL;
  const $ = (id) => document.getElementById(id);
  const TEMPLATE = `---
name: my-skill
description: One line shown in the / menu
docs:
  - django_querysets
urls:
  - https://docs.djangoproject.com/en/5.1/ref/models/querysets/
---
Instructions the assistant follows while this skill is active:

- What to focus on
- How to structure the answer
`;

  function skillCard(s) {
    const del = el("button", { class: "btn btn-sm cl-btn", title: `Delete /${s.name}`, "aria-label": `Delete ${s.name}` }, [icon("trash")]);
    del.addEventListener("click", async () => {
      if (!confirm(`Delete /${s.name}? Its fetched web docs stay in the knowledge base.`)) return;
      try {
        await api(`/api/skills/${s.name}`, { method: "DELETE" });
        toast(`Deleted /${s.name}`, "success");
        load();
      } catch (e) { toast(e.message); }
    });
    const edit = el("button", { class: "btn btn-sm cl-btn", title: "Edit source" }, [icon("pencil")]);
    edit.addEventListener("click", async () => {
      try {
        const d = await api(`/api/skills/${s.name}`);
        $("skillEditor").value = d.source;
        $("skillEditor").scrollIntoView({ behavior: "smooth", block: "center" });
        $("skillEditor").focus();
      } catch (e) { toast(e.message); }
    });
    const refresh = el("button", { class: "btn btn-sm cl-btn", title: "Re-fetch web docs", disabled: !s.urls.length || null }, [icon("arrow-repeat")]);
    refresh.addEventListener("click", async () => {
      refresh.disabled = true;
      refresh.replaceChildren(el("span", { class: "spinner-border spinner-border-sm" }));
      try {
        const d = await api(`/api/skills/${s.name}/refresh`, { method: "POST" });
        reportUrls(d.skill.url_results);
        load();
      } catch (e) { toast(e.message); refresh.disabled = false; refresh.replaceChildren(icon("arrow-repeat")); }
    });

    const docs = s.scoped
      ? (s.matched_docs.length ? s.matched_docs.map((t) => el("span", { class: "query-chip", text: t })) : [el("span", { class: "muted small", text: "No knowledge-base docs match yet" })])
      : [el("span", { class: "muted small", text: "All knowledge-base docs" })];
    const urls = s.urls.map((u) => el("div", { class: "skill-url" }, [
      el("span", { class: `sev-dot ${u.indexed ? "ok" : "warning"}`, title: u.indexed ? "Fetched and indexed" : "Not fetched" }),
      el("a", { href: u.url, target: "_blank", rel: "noopener noreferrer", text: u.title.replace(/^web: /, "") || u.url }),
      u.indexed ? el("span", { class: "muted small", text: `${u.chunks} chunks` }) : el("span", { class: "small", style: { color: "var(--amber)" }, text: "not fetched" }),
    ]));
    return el("div", { class: "skill-card" }, [
      el("div", { class: "skill-head" }, [el("span", { class: "skill-name", text: `/${s.name}` }), el("span", { class: "ms-auto d-flex gap-1" }, [edit, refresh, del])]),
      el("div", { class: "skill-desc", text: s.description || "No description" }),
      el("div", { class: "sub-label", text: "Knowledge base" }),
      el("div", { class: "query-chips" }, docs),
      s.urls.length ? el("div", { class: "sub-label", text: "Web docs" }) : null,
      ...urls,
    ]);
  }

  async function load() {
    try {
      const d = await api("/api/skills");
      $("skillSummary").textContent = d.skills.length ? `${d.skills.length} skills` : "";
      $("skillList").replaceChildren(...(d.skills.length ? d.skills.map(skillCard)
        : [el("div", { class: "muted small py-3", text: "No skills yet. Upload a SKILL.md or write one below." })]));
    } catch (e) { toast(e.message); }
  }

  function reportUrls(results) {
    const bad = results.filter((r) => !r.ok);
    if (bad.length) toast(`Couldn't fetch: ${bad.map((r) => `${r.url} (${r.error})`).join("; ")}`, "warning");
    const ok = results.filter((r) => r.ok && r.fetched).length;
    if (ok) toast(`Fetched and indexed ${ok} web doc${ok === 1 ? "" : "s"}.`, "success");
  }

  async function install(promise, label) {
    $("skillStatus").replaceChildren(el("span", { class: "spinner-border spinner-border-sm me-1" }), document.createTextNode(`${label}… (fetching web docs can take a few seconds)`));
    try {
      const d = await promise;
      $("skillStatus").textContent = `Saved /${d.skill.name}`;
      toast(`Skill /${d.skill.name} is ready — type /${d.skill.name} in Chat.`, "success");
      reportUrls(d.skill.url_results);
      load();
    } catch (e) {
      $("skillStatus").textContent = "";
      toast(e.message);
    }
  }

  async function uploadFiles(files) {
    for (const f of files) {
      const form = new FormData();
      form.append("file", f, f.name);
      await install(api("/api/skills", { method: "POST", form }), `Installing ${f.name}`);
    }
  }

  const drop = $("skillDrop");
  drop.addEventListener("click", () => $("skillInput").click());
  drop.addEventListener("keydown", (e) => (e.key === "Enter" || e.key === " ") && $("skillInput").click());
  drop.addEventListener("dragover", (e) => { e.preventDefault(); drop.classList.add("over"); });
  drop.addEventListener("dragleave", () => drop.classList.remove("over"));
  drop.addEventListener("drop", (e) => { e.preventDefault(); drop.classList.remove("over"); uploadFiles([...e.dataTransfer.files]); });
  $("skillInput").addEventListener("change", (e) => { uploadFiles([...e.target.files]); e.target.value = ""; });
  $("skillSave").addEventListener("click", () => install(api("/api/skills", { method: "POST", json: { source: $("skillEditor").value } }), "Saving"));
  $("skillTemplate").addEventListener("click", () => { $("skillEditor").value = TEMPLATE; });
  $("skillEditor").value = TEMPLATE;
  load();
})();
