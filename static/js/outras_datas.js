(function () {
  const cfg = window.OUTRAS_DATAS_CONFIG || {};
  const tiposSemAula = Array.isArray(cfg.tiposSemAula) ? cfg.tiposSemAula : [];

  const selectTipo = document.getElementById("novo-tipo-outras");
  const temposInput = document.getElementById("tempos-sem-aula-outras");

  function sincronizarTemposBulk() {
    if (!selectTipo || !temposInput) return;
    const isSemAula = tiposSemAula.includes(selectTipo.value);
    if (isSemAula) {
      temposInput.readOnly = false;
      temposInput.classList.remove("bg-light", "text-muted");
      return;
    }
    temposInput.value = 0;
    temposInput.readOnly = true;
    temposInput.classList.add("bg-light", "text-muted");
  }

  sincronizarTemposBulk();
  if (selectTipo) {
    selectTipo.addEventListener("change", sincronizarTemposBulk);
  }

  const rows = Array.from(
    document.querySelectorAll("tr[data-aula-id][data-observacoes-endpoint]")
  );
  if (!rows.length) return;

  const states = new Map();
  const ALLOWED_TAGS = new Set(["P", "BR", "B", "STRONG", "I", "EM", "UL", "OL", "LI", "A"]);

  function hashHtml(value) {
    let hash = 0;
    const str = String(value || "");
    for (let i = 0; i < str.length; i += 1) {
      hash = (hash << 5) - hash + str.charCodeAt(i);
      hash |= 0;
    }
    return hash.toString();
  }

  function toSavedHour(savedAtRaw) {
    if (!savedAtRaw) return "";
    const date = new Date(savedAtRaw);
    if (Number.isNaN(date.getTime())) return "";
    return date.toLocaleTimeString("pt-PT", { hour: "2-digit", minute: "2-digit" });
  }

  function sanitizeClientHtml(rawHtml) {
    const wrapper = document.createElement("div");
    wrapper.innerHTML = String(rawHtml || "");

    const cleanNode = (node) => {
      Array.from(node.childNodes).forEach((child) => {
        if (child.nodeType === Node.TEXT_NODE) return;
        if (child.nodeType !== Node.ELEMENT_NODE) {
          child.remove();
          return;
        }

        const tag = child.tagName.toUpperCase();
        if (tag === "SCRIPT" || tag === "STYLE") {
          child.remove();
          return;
        }

        if (!ALLOWED_TAGS.has(tag)) {
          if (tag === "DIV") {
            const p = document.createElement("p");
            while (child.firstChild) p.appendChild(child.firstChild);
            child.replaceWith(p);
            cleanNode(p);
            return;
          }
          const fragment = document.createDocumentFragment();
          while (child.firstChild) fragment.appendChild(child.firstChild);
          child.replaceWith(fragment);
          cleanNode(fragment);
          return;
        }

        Array.from(child.attributes).forEach((attr) => {
          if (tag === "A" && attr.name.toLowerCase() === "href") {
            const href = (attr.value || "").trim();
            if (!/^https?:\/\//i.test(href)) {
              child.removeAttribute("href");
              return;
            }
            child.setAttribute("href", href);
            return;
          }
          child.removeAttribute(attr.name);
        });

        if (tag === "A" && !child.getAttribute("href")) {
          const fragment = document.createDocumentFragment();
          while (child.firstChild) fragment.appendChild(child.firstChild);
          child.replaceWith(fragment);
          cleanNode(fragment);
          return;
        }

        cleanNode(child);
      });
    };

    cleanNode(wrapper);
    return wrapper.innerHTML.trim();
  }

  function setStatus(state, message, level) {
    if (!state || !state.statusNode) return;
    state.statusNode.textContent = message;
    state.statusNode.classList.remove("text-muted", "text-success", "text-danger");
    if (level === "success") {
      state.statusNode.classList.add("text-success");
      return;
    }
    if (level === "error") {
      state.statusNode.classList.add("text-danger");
      return;
    }
    state.statusNode.classList.add("text-muted");
  }

  async function saveNow(state, force) {
    if (!state) return;

    clearTimeout(state.timer);
    state.timer = null;

    const sanitized = sanitizeClientHtml(state.editor.innerHTML || "");
    if (sanitized !== (state.editor.innerHTML || "").trim()) {
      state.editor.innerHTML = sanitized;
    }

    const currentHash = hashHtml(sanitized);
    state.lastLocalHash = currentHash;

    if (!force && currentHash === state.lastSentHash) {
      setStatus(state, "Sem alterações", "muted");
      return;
    }

    if (state.isSaving) {
      state.pending = true;
      return;
    }

    state.isSaving = true;
    state.button.disabled = true;
    setStatus(state, "A guardar...", "muted");

    try {
      const resp = await fetch(state.endpoint, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Accept: "application/json",
        },
        body: JSON.stringify({ observacoes_html: sanitized }),
      });
      const data = await resp.json().catch(() => ({ ok: false, error: "Erro ao guardar" }));
      if (!resp.ok || !data.ok) {
        throw new Error(data.error || "Erro ao guardar");
      }

      const savedHtml = sanitizeClientHtml(data.observacoes_html || sanitized || "");
      if (savedHtml !== (state.editor.innerHTML || "").trim()) {
        state.editor.innerHTML = savedHtml;
      }

      state.lastSentHash = hashHtml(savedHtml);
      state.lastLocalHash = state.lastSentHash;

      const hhmm = toSavedHour(data.saved_at);
      if (hhmm) {
        setStatus(state, `Guardado às ${hhmm}`, "success");
      } else {
        setStatus(state, "Guardado", "success");
      }
    } catch (err) {
      console.error(err);
      setStatus(state, "Erro ao guardar", "error");
    } finally {
      state.isSaving = false;
      state.button.disabled = false;
      if (state.pending) {
        state.pending = false;
        saveNow(state, false);
      }
    }
  }

  function scheduleSave(state) {
    if (!state) return;
    clearTimeout(state.timer);
    state.timer = setTimeout(() => {
      saveNow(state, false);
    }, 1000);
  }

  rows.forEach((row) => {
    const aulaId = row.dataset.aulaId;
    const endpoint = row.dataset.observacoesEndpoint;
    const editor = row.querySelector(`.js-observacoes-editor[data-aula-id="${aulaId}"]`);
    const button = row.querySelector(`.js-observacoes-save[data-aula-id="${aulaId}"]`);
    const statusNode = row.querySelector(`.js-observacoes-status[data-aula-id="${aulaId}"]`);
    if (!aulaId || !endpoint || !editor || !button || !statusNode) return;

    const initialHtml = sanitizeClientHtml(editor.innerHTML || "");
    editor.innerHTML = initialHtml;

    const state = {
      aulaId,
      endpoint,
      editor,
      button,
      statusNode,
      timer: null,
      isSaving: false,
      pending: false,
      lastSentHash: hashHtml(initialHtml),
      lastLocalHash: hashHtml(initialHtml),
    };
    states.set(aulaId, state);

    editor.addEventListener("input", () => {
      const current = sanitizeClientHtml(editor.innerHTML || "");
      const currentHash = hashHtml(current);
      state.lastLocalHash = currentHash;
      if (currentHash === state.lastSentHash) {
        clearTimeout(state.timer);
        state.timer = null;
        setStatus(state, "Sem alterações", "muted");
        return;
      }
      setStatus(state, "Por guardar...", "muted");
      scheduleSave(state);
    });

    editor.addEventListener("blur", () => {
      saveNow(state, false);
    });

    button.addEventListener("click", () => {
      saveNow(state, true);
    });
  });

  document.addEventListener("click", (ev) => {
    const cmdBtn = ev.target.closest(".js-observacoes-cmd");
    if (!cmdBtn) return;
    ev.preventDefault();

    const aulaId = cmdBtn.dataset.aulaId;
    const command = cmdBtn.dataset.command;
    const state = states.get(aulaId);
    if (!state || !command) return;

    state.editor.focus();
    if (command === "createLink") {
      const url = window.prompt("Indica o URL (http/https):", "https://");
      if (!url) return;
      const trimmed = url.trim();
      if (!/^https?:\/\//i.test(trimmed)) {
        setStatus(state, "Link inválido (usar http/https)", "error");
        return;
      }
      document.execCommand("createLink", false, trimmed);
    } else {
      document.execCommand(command, false, null);
    }

    const current = sanitizeClientHtml(state.editor.innerHTML || "");
    state.editor.innerHTML = current;
    const currentHash = hashHtml(current);
    state.lastLocalHash = currentHash;
    if (currentHash === state.lastSentHash) {
      setStatus(state, "Sem alterações", "muted");
      return;
    }
    setStatus(state, "Por guardar...", "muted");
    scheduleSave(state);
  });
})();
