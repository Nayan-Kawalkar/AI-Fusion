/* Shared helpers: CSRF-aware fetch, safe DOM building, toasts. */
(function () {
  function getCookie(name) {
    const match = document.cookie.split(";").map((c) => c.trim()).find((c) => c.startsWith(name + "="));
    return match ? decodeURIComponent(match.slice(name.length + 1)) : null;
  }

  class Cancelled extends Error {}

  /* signal: an AbortSignal; aborting rejects with CL.Cancelled. */
  async function api(url, { method = "GET", json, form, signal } = {}) {
    const opts = { method, signal, headers: { "X-CSRFToken": getCookie("csrftoken") || "" } };
    if (json !== undefined) {
      opts.headers["Content-Type"] = "application/json";
      opts.body = JSON.stringify(json);
    } else if (form) {
      opts.body = form;
    }
    let res;
    try {
      res = await fetch(url, opts);
    } catch (e) {
      if (e.name === "AbortError") throw new Cancelled("Stopped");
      throw new Error("Network error — is the server running?");
    }
    let data = {};
    try {
      data = await res.json();
    } catch (e) {
      if (!res.ok) throw new Error(`Request failed (${res.status})`);
    }
    if (!res.ok) throw new Error(data.error || `Request failed (${res.status})`);
    return data;
  }

  /* el("div", {class: "x", onclick: fn}, [children]) — text is always set via textContent. */
  function el(tag, attrs = {}, children = []) {
    const node = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) {
      if (v === null || v === undefined || v === false) continue;
      if (k === "class") node.className = v;
      else if (k === "text") node.textContent = v;
      else if (k === "style" && typeof v === "object") Object.assign(node.style, v);
      else if (k.startsWith("on") && typeof v === "function") node.addEventListener(k.slice(2), v);
      else node.setAttribute(k, v === true ? "" : v);
    }
    for (const child of [].concat(children)) {
      if (child === null || child === undefined || child === false) continue;
      node.appendChild(typeof child === "string" ? document.createTextNode(child) : child);
    }
    return node;
  }

  function icon(name) {
    return el("i", { class: `bi bi-${name}`, "aria-hidden": "true" });
  }

  function toast(message, kind = "danger") {
    const container = document.getElementById("toasts");
    if (!container || !window.bootstrap) return alert(message);
    const iconName = { danger: "exclamation-octagon", success: "check-circle", info: "info-circle", warning: "exclamation-triangle" }[kind] || "info-circle";
    const node = el("div", { class: `toast cl-toast cl-toast-${kind}`, role: "alert", "aria-live": "assertive" }, [
      el("div", { class: "d-flex align-items-start gap-2 p-2" }, [
        icon(iconName),
        el("div", { class: "flex-grow-1", text: message }),
        el("button", { type: "button", class: "btn-close btn-close-white", "data-bs-dismiss": "toast", "aria-label": "Close" }),
      ]),
    ]);
    container.appendChild(node);
    const t = new bootstrap.Toast(node, { delay: kind === "danger" ? 7000 : 3500 });
    node.addEventListener("hidden.bs.toast", () => node.remove());
    t.show();
  }

  window.CL = { api, el, icon, toast, getCookie, Cancelled };
})();
