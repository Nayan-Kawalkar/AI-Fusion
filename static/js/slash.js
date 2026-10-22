/* "/" skill picker for a textarea: type / at the start to choose a skill, like Claude Code. */
window.SlashMenu = (function () {
  const { api, el } = CL;
  let skills = null;
  let loading = null;

  async function load(force = false) {
    if (skills && !force) return skills;
    if (!loading || force) {
      loading = api("/api/skills").then((d) => (skills = d.skills)).catch(() => (skills = []));
    }
    return loading;
  }

  /* The skill named at the start of text, if it exists. */
  function activeSkill(text) {
    const m = /^\s*\/([a-z0-9-]+)(\s|$)/.exec(text || "");
    return m && skills ? skills.find((s) => s.name === m[1]) || null : null;
  }

  function scopeLabel(s) {
    const docs = s.matched_docs.length;
    return s.scoped ? `searches ${docs} doc${docs === 1 ? "" : "s"}` : "searches all docs";
  }

  /* attach(textarea, {chip}) — chip: element that shows the active skill below/above the box. */
  function attach(input, opts = {}) {
    const menu = el("div", { class: "slash-menu d-none", role: "listbox" });
    input.parentElement.style.position = "relative";
    input.parentElement.appendChild(menu);
    let items = [];
    let index = 0;

    const close = () => { menu.classList.add("d-none"); items = []; };
    const pick = (s) => {
      const rest = input.value.replace(/^\s*\/[a-z0-9-]*\s*/, "");
      input.value = `/${s.name} ${rest}`;
      close();
      input.focus();
      input.setSelectionRange(input.value.length, input.value.length);
      input.dispatchEvent(new Event("input"));
    };
    const render = () => {
      menu.replaceChildren(...items.map((s, i) => {
        const row = el("button", { type: "button", class: `slash-item${i === index ? " active" : ""}`, role: "option" }, [
          el("span", { class: "slash-name", text: `/${s.name}` }),
          el("span", { class: "slash-desc", text: s.description || "" }),
          el("span", { class: "slash-scope", text: scopeLabel(s) }),
        ]);
        row.addEventListener("mousedown", (e) => { e.preventDefault(); pick(s); });
        return row;
      }));
      if (!items.length) {
        menu.replaceChildren(el("div", { class: "slash-empty" }, [
          "No matching skills. ", el("a", { href: "/skills/", text: "Add a skill" }),
        ]));
      }
    };
    const update = async () => {
      if (opts.chip) renderChip(opts.chip, input.value);
      const m = /^\s*\/([a-z0-9-]*)$/.exec(input.value.slice(0, input.selectionStart));
      if (!m) return close();
      await load();
      items = skills.filter((s) => s.name.includes(m[1]));
      index = 0;
      menu.classList.remove("d-none");
      render();
    };
    input.addEventListener("input", update);
    input.addEventListener("focus", () => load(true).then(() => opts.chip && renderChip(opts.chip, input.value)));
    input.addEventListener("blur", () => setTimeout(close, 120));
    // Capture phase so the menu handles Enter/arrows before the box's own Enter-to-send.
    input.addEventListener("keydown", (e) => {
      if (menu.classList.contains("d-none") || !items.length) return;
      if (e.key === "ArrowDown") { index = (index + 1) % items.length; render(); e.preventDefault(); }
      else if (e.key === "ArrowUp") { index = (index - 1 + items.length) % items.length; render(); e.preventDefault(); }
      else if (e.key === "Enter" || e.key === "Tab") { pick(items[index]); e.preventDefault(); e.stopImmediatePropagation(); }
      else if (e.key === "Escape") { close(); e.preventDefault(); }
    }, true);
  }

  function renderChip(chip, text) {
    const s = activeSkill(text);
    chip.classList.toggle("d-none", !s);
    if (s) chip.replaceChildren(el("i", { class: "bi bi-magic" }), ` /${s.name} · ${scopeLabel(s)}${s.urls.length ? ` · ${s.urls.length} web doc${s.urls.length === 1 ? "" : "s"}` : ""}`);
  }

  return { attach, load, activeSkill };
})();
