(function(){
  function ready(fn) {
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', fn);
    else fn();
  }

  async function parseResponse(response) {
    const text = await response.text();
    try { return JSON.parse(text); }
    catch { return { error: text || 'Erro inesperado' }; }
  }

  function showMessage(boxId, message, isError) {
    const box = document.getElementById(boxId);
    if (box) {
      box.textContent = message;
      box.style.display = 'block';
      box.style.borderColor = isError ? '#b00020' : '#0a58ca';
      box.style.color = isError ? '#b00020' : '#0a58ca';
    }
    if (isError) {
      window.alert(message);
      console.error('[EV2 Config]', message);
    }
  }

  async function handleDomainButtons(event) {
    const duplicateBtn = event.target.closest('.js-domain-duplicate');
    if (duplicateBtn) {
      const row = duplicateBtn.closest('tr');
      const currentName = row?.querySelector('.js-domain-name')?.textContent?.trim() || '';
      const suggestion = currentName ? `${currentName} (cópia)` : '';
      const newDesignation = window.prompt('Novo nome/designação do domínio duplicado:', suggestion);
      if (!newDesignation || !newDesignation.trim()) return true;

      const response = await fetch('/ev2/config/domains/duplicate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'Accept': 'application/json' },
        body: JSON.stringify({ domain_id: Number(duplicateBtn.dataset.domainId), new_designation: newDesignation.trim() }),
      });
      const data = await parseResponse(response);
      if (!response.ok) {
        showMessage('js-domain-msg', data.error || 'Falha ao duplicar domínio.', true);
        return true;
      }
      window.location.reload();
      return true;
    }

    const deleteBtn = event.target.closest('.js-domain-delete');
    if (deleteBtn) {
      if (!window.confirm('Tem a certeza que pretende eliminar domínio?')) return true;
      const response = await fetch(`/ev2/config/domains/${deleteBtn.dataset.domainId}`, {
        method: 'DELETE',
        headers: { 'Accept': 'application/json' },
      });
      const data = await parseResponse(response);
      if (!response.ok) {
        showMessage('js-domain-msg', data.error || 'Falha ao eliminar domínio.', true);
        return true;
      }
      window.location.reload();
      return true;
    }

    return false;
  }

  function setRubricaFormMode(editing) {
    const title = document.getElementById('js-rubrica-form-title');
    const saveBtn = document.getElementById('js-rubrica-save-btn');
    const cancelBtn = document.getElementById('js-rubrica-cancel');
    if (title) title.textContent = editing ? 'Editar rubrica' : 'Nova rubrica';
    if (saveBtn) saveBtn.textContent = editing ? 'Guardar alterações' : 'Criar rubrica';
    if (cancelBtn) cancelBtn.style.display = editing ? 'inline-block' : 'none';
  }

  function resetRubricaForm() {
    const form = document.getElementById('js-rubrica-form');
    if (!form) return;
    form.reset();
    const id = document.getElementById('js-rubrica-id');
    if (id) id.value = '';
    setRubricaFormMode(false);
  }

  function closeInlineRubricaEditor() {
    document.querySelectorAll('.js-inline-rubrica-editor').forEach((el) => el.remove());
  }

  function buildDomainOptions(selected) {
    return Array.from(document.querySelectorAll('#js-rubrica-domain option'))
      .filter((opt) => opt.value)
      .map((opt) => `<option value="${opt.value}" ${String(selected) === String(opt.value) ? 'selected' : ''}>${opt.textContent || '—'}</option>`)
      .join('');
  }

  function openInlineRubricaEditor(row) {
    if (!row) return;
    closeInlineRubricaEditor();
    const editor = document.createElement('tr');
    editor.className = 'js-inline-rubrica-editor table-warning';
    editor.innerHTML = `
      <td colspan="10">
        <form class="js-inline-rubrica-form row g-2 align-items-end">
          <div class="col-12 col-md-3">
            <label class="form-label small mb-1">Domínio</label>
            <select name="domain_id" class="form-select form-select-sm">${buildDomainOptions(row.dataset.domainId)}</select>
          </div>
          <div class="col-6 col-md-1">
            <label class="form-label small mb-1">Código</label>
            <input name="codigo" class="form-control form-control-sm" value="${row.dataset.codigo || ''}" required>
          </div>
          <div class="col-6 col-md-2">
            <label class="form-label small mb-1">Nome</label>
            <input name="nome" class="form-control form-control-sm" value="${row.dataset.nome || ''}" required>
          </div>
          <div class="col-12 col-md-2">
            <label class="form-label small mb-1">Descrição</label>
            <input name="descricao" class="form-control form-control-sm" value="${row.dataset.descricao || ''}">
          </div>
          <div class="col-12">
            <label class="form-label small mb-1">Desc. N1</label>
            <textarea name="descritor_nivel_1" class="form-control form-control-sm" rows="4" style="resize: vertical;">${row.dataset.descritorNivel1 || ''}</textarea>
          </div>
          <div class="col-12">
            <label class="form-label small mb-1">Desc. N2</label>
            <textarea name="descritor_nivel_2" class="form-control form-control-sm" rows="4" style="resize: vertical;">${row.dataset.descritorNivel2 || ''}</textarea>
          </div>
          <div class="col-12">
            <label class="form-label small mb-1">Desc. N3</label>
            <textarea name="descritor_nivel_3" class="form-control form-control-sm" rows="4" style="resize: vertical;">${row.dataset.descritorNivel3 || ''}</textarea>
          </div>
          <div class="col-12">
            <label class="form-label small mb-1">Desc. N4</label>
            <textarea name="descritor_nivel_4" class="form-control form-control-sm" rows="4" style="resize: vertical;">${row.dataset.descritorNivel4 || ''}</textarea>
          </div>
          <div class="col-12">
            <label class="form-label small mb-1">Desc. N5</label>
            <textarea name="descritor_nivel_5" class="form-control form-control-sm" rows="4" style="resize: vertical;">${row.dataset.descritorNivel5 || ''}</textarea>
          </div>
          <div class="col-6 col-md-1">
            <label class="form-label small mb-1">Ordem</label>
            <input type="number" name="ordem" class="form-control form-control-sm" value="${row.dataset.ordem || 0}">
          </div>
          <div class="col-6 col-md-1">
            <label class="form-label small mb-1">Peso</label>
            <input type="number" step="0.01" name="peso" class="form-control form-control-sm" value="${row.dataset.peso || 0}">
          </div>
          <div class="col-6 col-md-1">
            <div class="form-check mt-4">
              <input class="form-check-input" type="checkbox" name="ativo" ${row.dataset.ativo === '1' ? 'checked' : ''}>
              <label class="form-check-label small">Ativo</label>
            </div>
          </div>
          <div class="col-12 col-md-1 d-flex gap-2 justify-content-md-end">
            <button type="submit" class="btn btn-sm btn-success">Guardar</button>
            <button type="button" class="btn btn-sm btn-outline-secondary js-inline-rubrica-cancel">Cancelar</button>
          </div>
        </form>
      </td>
    `;
    row.insertAdjacentElement('afterend', editor);
    editor.scrollIntoView({ block: 'nearest' });
  }

  function domainNameMap() {
    const map = {};
    document.querySelectorAll('#js-rubrica-domain option[value]').forEach((opt) => {
      if (opt.value) map[String(opt.value)] = opt.textContent || '—';
    });
    return map;
  }

  function renderRubricasTable(items) {
    const tbody = document.querySelector('#js-rubricas-table tbody');
    if (!tbody) return;
    const dmap = domainNameMap();
    tbody.innerHTML = '';
    items.forEach((r) => {
      const tr = document.createElement('tr');
      tr.dataset.rubricaId = r.id;
      tr.dataset.domainId = r.domain_id;
      tr.dataset.codigo = r.codigo || '';
      tr.dataset.nome = r.nome || '';
      tr.dataset.descricao = r.descricao || '';
      tr.dataset.descritorNivel1 = r.descritor_nivel_1 || '';
      tr.dataset.descritorNivel2 = r.descritor_nivel_2 || '';
      tr.dataset.descritorNivel3 = r.descritor_nivel_3 || '';
      tr.dataset.descritorNivel4 = r.descritor_nivel_4 || '';
      tr.dataset.descritorNivel5 = r.descritor_nivel_5 || '';
      tr.dataset.ordem = String(r.ordem ?? 0);
      tr.dataset.peso = String(r.peso ?? 0);
      tr.dataset.ativo = r.ativo ? '1' : '0';
      tr.id = `rubrica-${r.id}`;
      tr.innerHTML = `
        <td class="col-id">${r.id}</td>
        <td class="col-left">${dmap[String(r.domain_id)] || r.domain_nome || '—'}</td>
        <td class="col-left">${r.codigo || ''}</td>
        <td class="col-left">${r.nome || ''}</td>
        <td class="col-left">${r.descricao || ''}</td>
        <td class="col-right text-end">${r.ordem ?? 0}</td>
        <td class="col-right text-end">${Number(r.peso ?? 0).toFixed(2)}</td>
        <td class="col-center">${r.components_count ?? (Array.isArray(r.components) ? r.components.length : 0)}</td>
        <td class="col-center">${r.ativo ? 'Sim' : 'Não'}</td>
        <td class="col-left">
          <button type="button" class="js-rubrica-edit secondary">Editar</button>
          <button type="button" class="js-rubrica-delete secondary">Eliminar</button>
        </td>
      `;
      tbody.appendChild(tr);
    });
  }

  async function refreshRubricasTable() {
    const response = await fetch('/ev2/config/rubricas?format=json', { headers: { 'Accept': 'application/json' } });
    const data = await parseResponse(response);
    if (!response.ok || !Array.isArray(data)) {
      showMessage('js-rubrica-msg', (data && data.error) || 'Falha ao atualizar lista de rubricas.', true);
      return;
    }
    renderRubricasTable(data);
    applyRubricasFilters();
  }


  function applyRubricasFilters() {
    const domainFilter = document.getElementById('js-rubrica-filter-domain')?.value || '';
    const term = (document.getElementById('js-rubrica-search')?.value || '').trim().toLowerCase();
    document.querySelectorAll('#js-rubricas-table tbody tr').forEach((row) => {
      const rowDomain = row.dataset.domainId || '';
      const codigo = (row.dataset.codigo || '').toLowerCase();
      const nome = (row.dataset.nome || '').toLowerCase();
      const passDomain = !domainFilter || rowDomain === String(domainFilter);
      const passSearch = !term || codigo.includes(term) || nome.includes(term);
      row.style.display = passDomain && passSearch ? '' : 'none';
    });
  }

  ready(function(){
    document.addEventListener('click', async function(event){
      const handledDomain = await handleDomainButtons(event);
      if (handledDomain) return;

      const editBtn = event.target.closest('.js-rubrica-edit');
      if (editBtn) {
        const row = editBtn.closest('tr');
        openInlineRubricaEditor(row);
        return;
      }

      const inlineCancelBtn = event.target.closest('.js-inline-rubrica-cancel');
      if (inlineCancelBtn) {
        closeInlineRubricaEditor();
        return;
      }

      const deleteBtn = event.target.closest('.js-rubrica-delete');
      if (deleteBtn) {
        if (!window.confirm('Tem a certeza que pretende eliminar rubrica?')) return;
        const row = deleteBtn.closest('tr');
        const rubricaId = row?.dataset?.rubricaId;
        if (!rubricaId) return;

        const response = await fetch(`/ev2/config/rubricas/${rubricaId}`, {
          method: 'DELETE',
          headers: { 'Accept': 'application/json' },
        });
        const data = await parseResponse(response);
        if (!response.ok) {
          showMessage('js-rubrica-msg', data.error || 'Falha ao eliminar rubrica.', true);
          return;
        }
        showMessage('js-rubrica-msg', 'Rubrica eliminada com sucesso.', false);
        await refreshRubricasTable();
        closeInlineRubricaEditor();
        resetRubricaForm();
      }
    });

    document.addEventListener('submit', async function(event){
      const inlineForm = event.target.closest('.js-inline-rubrica-form');
      if (!inlineForm) return;
      event.preventDefault();
      const hostRow = inlineForm.closest('tr')?.previousElementSibling;
      const rubricaId = hostRow?.dataset?.rubricaId;
      if (!rubricaId) return;

      const payload = {
        domain_id: Number(inlineForm.querySelector('[name="domain_id"]')?.value),
        codigo: inlineForm.querySelector('[name="codigo"]')?.value?.trim(),
        nome: inlineForm.querySelector('[name="nome"]')?.value?.trim(),
        descricao: inlineForm.querySelector('[name="descricao"]')?.value?.trim() || null,
        descritor_nivel_1: inlineForm.querySelector('[name="descritor_nivel_1"]')?.value?.trim() || null,
        descritor_nivel_2: inlineForm.querySelector('[name="descritor_nivel_2"]')?.value?.trim() || null,
        descritor_nivel_3: inlineForm.querySelector('[name="descritor_nivel_3"]')?.value?.trim() || null,
        descritor_nivel_4: inlineForm.querySelector('[name="descritor_nivel_4"]')?.value?.trim() || null,
        descritor_nivel_5: inlineForm.querySelector('[name="descritor_nivel_5"]')?.value?.trim() || null,
        ordem: Number(inlineForm.querySelector('[name="ordem"]')?.value || 0),
        peso: Number(inlineForm.querySelector('[name="peso"]')?.value || 0),
        ativo: !!inlineForm.querySelector('[name="ativo"]')?.checked,
      };

      const response = await fetch(`/ev2/config/rubricas/${rubricaId}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', 'Accept': 'application/json' },
        body: JSON.stringify(payload),
      });
      const data = await parseResponse(response);
      if (!response.ok) {
        showMessage('js-rubrica-msg', data.error || 'Falha ao guardar rubrica.', true);
        return;
      }

      showMessage('js-rubrica-msg', 'Rubrica atualizada.', false);
      await refreshRubricasTable();
      closeInlineRubricaEditor();
      const updatedRow = document.getElementById(`rubrica-${rubricaId}`);
      if (updatedRow) updatedRow.scrollIntoView({ block: 'center' });
    });

    const rubricaCancel = document.getElementById('js-rubrica-cancel');
    if (rubricaCancel) rubricaCancel.addEventListener('click', resetRubricaForm);

    const rubricaForm = document.getElementById('js-rubrica-form');
    if (rubricaForm) {
      rubricaForm.addEventListener('submit', async function(e){
        e.preventDefault();
        const rubricaId = (document.getElementById('js-rubrica-id')?.value || '').trim();
        const domainId = document.getElementById('js-rubrica-domain')?.value;
        const codigo = document.getElementById('js-rubrica-codigo')?.value?.trim();
        const nome = document.getElementById('js-rubrica-nome')?.value?.trim();
        const descricao = document.getElementById('js-rubrica-descricao')?.value?.trim();
        const descritor1 = document.getElementById('js-rubrica-descritor-1')?.value?.trim();
        const descritor2 = document.getElementById('js-rubrica-descritor-2')?.value?.trim();
        const descritor3 = document.getElementById('js-rubrica-descritor-3')?.value?.trim();
        const descritor4 = document.getElementById('js-rubrica-descritor-4')?.value?.trim();
        const descritor5 = document.getElementById('js-rubrica-descritor-5')?.value?.trim();
        const ordem = Number(document.getElementById('js-rubrica-ordem')?.value || 0);
        const peso = Number(document.getElementById('js-rubrica-peso')?.value || 0);
        const ativo = !!document.getElementById('js-rubrica-ativo')?.checked;

        const payload = {
          domain_id: Number(domainId),
          codigo,
          nome,
          descricao,
          descritor_nivel_1: descritor1 || null,
          descritor_nivel_2: descritor2 || null,
          descritor_nivel_3: descritor3 || null,
          descritor_nivel_4: descritor4 || null,
          descritor_nivel_5: descritor5 || null,
          ordem,
          peso,
          ativo,
        };
        const url = rubricaId ? `/ev2/config/rubricas/${rubricaId}` : '/ev2/config/rubricas';
        const method = rubricaId ? 'PUT' : 'POST';

        const response = await fetch(url, {
          method,
          headers: { 'Content-Type': 'application/json', 'Accept': 'application/json' },
          body: JSON.stringify(payload),
        });
        const data = await parseResponse(response);
        if (!response.ok) {
          showMessage('js-rubrica-msg', data.error || 'Falha ao guardar rubrica.', true);
          return;
        }
        showMessage('js-rubrica-msg', rubricaId ? 'Rubrica atualizada.' : 'Rubrica criada.', false);
        await refreshRubricasTable();
        closeInlineRubricaEditor();
        resetRubricaForm();
      });
    }

    const filterDomain = document.getElementById('js-rubrica-filter-domain');
    const searchInput = document.getElementById('js-rubrica-search');
    if (filterDomain) filterDomain.addEventListener('change', applyRubricasFilters);
    if (searchInput) searchInput.addEventListener('input', applyRubricasFilters);
    applyRubricasFilters();

    const importForm = document.getElementById('js-rubricas-import-form');
    if (importForm) {
      importForm.addEventListener('submit', async function(e){
        e.preventDefault();
        const source = importForm.querySelector('select[name="source_domain_id"]')?.value;
        const target = importForm.querySelector('select[name="target_domain_id"]')?.value;
        if (!source || !target) return;
        if (source === target) {
          showMessage('js-rubrica-msg', 'Origem e destino devem ser diferentes.', true);
          return;
        }
        if (!window.confirm('Importar todas as rubricas do domínio origem para o destino?')) return;

        const response = await fetch('/ev2/config/rubricas/import', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', 'Accept': 'application/json' },
          body: JSON.stringify({ source_domain_id: Number(source), target_domain_id: Number(target) }),
        });
        const data = await parseResponse(response);
        if (!response.ok) {
          showMessage('js-rubrica-msg', data.error || 'Falha ao importar rubricas.', true);
          return;
        }
        const warnings = data.warnings?.length ? ` Avisos: ${data.warnings.join(' | ')}` : '';
        showMessage('js-rubrica-msg', `Rubricas importadas com sucesso.${warnings}`, false);
        await refreshRubricasTable();
        resetRubricaForm();
      });
    }
  });
})();
