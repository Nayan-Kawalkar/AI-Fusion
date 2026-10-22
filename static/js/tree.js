/* Collapsible file tree rendered from /api/projects/<id>/tree. */
window.Tree = (function () {
  const { el, icon } = CL;
  const EXT_ICON = {
    py: ["filetype-py", "py"], js: ["filetype-js", "js"], mjs: ["filetype-js", "js"], jsx: ["filetype-jsx", "js"],
    ts: ["filetype-tsx", "js"], tsx: ["filetype-tsx", "js"], html: ["filetype-html", "html"], css: ["filetype-css", ""],
    json: ["filetype-json", ""], md: ["filetype-md", "md"], txt: ["file-text", ""], yml: ["filetype-yml", ""],
    yaml: ["filetype-yml", ""], sql: ["filetype-sql", ""], java: ["filetype-java", ""], sh: ["terminal", ""],
  };

  function fileIcon(name) {
    const ext = name.includes(".") ? name.split(".").pop().toLowerCase() : "";
    const [bi, cls] = EXT_ICON[ext] || ["file-earmark", ""];
    return el("i", { class: `bi bi-${bi} file-icon ${cls}`, "aria-hidden": "true" });
  }

  function renderNode(node, depth, onOpen) {
    const pad = { paddingLeft: `${10 + depth * 14}px` };
    if (node.type === "file") {
      const row = el("div", { class: "tree-row", style: pad, "data-path": node.path, title: node.path, role: "treeitem" }, [
        el("span", { class: "chev" }),
        fileIcon(node.name),
        el("span", { text: node.name }),
      ]);
      row.addEventListener("click", () => onOpen(node.path));
      return el("li", {}, [row]);
    }
    const open = depth === 0;
    const folderIcon = icon(open ? "folder2-open" : "folder2");
    const row = el("div", { class: `tree-row${open ? " open" : ""}`, style: pad, title: node.path, role: "treeitem" }, [
      el("i", { class: "bi bi-chevron-right chev", "aria-hidden": "true" }),
      folderIcon,
      el("span", { text: node.name }),
    ]);
    const kids = el("ul", { class: `tree-children${open ? "" : " collapsed"}`, role: "group" },
      node.children.map((c) => renderNode(c, depth + 1, onOpen)));
    row.addEventListener("click", () => {
      const nowOpen = kids.classList.toggle("collapsed") === false;
      row.classList.toggle("open", nowOpen);
      folderIcon.className = `bi bi-${nowOpen ? "folder2-open" : "folder2"}`;
    });
    return el("li", {}, [row, kids]);
  }

  function render(container, tree, onOpen) {
    const list = el("ul", { role: "tree" }, tree.children.map((c) => renderNode(c, 0, onOpen)));
    container.replaceChildren(list);
  }

  function setActive(container, path) {
    container.querySelectorAll(".tree-row.active").forEach((r) => r.classList.remove("active"));
    const row = [...container.querySelectorAll(".tree-row[data-path]")].find((r) => r.dataset.path === path);
    if (!row) return;
    row.classList.add("active");
    // Expand collapsed ancestors so the active file is visible.
    let ul = row.closest("ul.tree-children");
    while (ul) {
      if (ul.classList.contains("collapsed")) ul.previousElementSibling.click();
      ul = ul.parentElement.closest("ul.tree-children");
    }
    row.scrollIntoView({ block: "nearest" });
  }

  /* Problem-count badges from the project scan: {path: {errors, warnings}}. */
  function setBadges(container, counts) {
    container.querySelectorAll(".tree-badge").forEach((b) => b.remove());
    container.querySelectorAll(".tree-row[data-path]").forEach((row) => {
      const c = counts[row.dataset.path];
      if (!c || !(c.errors || c.warnings)) return;
      row.appendChild(el("span", {
        class: `tree-badge ${c.errors ? "err" : "warn"}`,
        title: `${c.errors} errors, ${c.warnings} warnings`,
        text: String(c.errors || c.warnings),
      }));
    });
  }

  return { render, setActive, setBadges };
})();
