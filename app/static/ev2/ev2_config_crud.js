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

  ready(function(){
    document.addEventListener('click', async function(event){
      const handledDomain = await handleDomainButtons(event);
      if (handledDomain) return;

      const editBtn = event.target.closest('.js-rubrica-edit');
      if (editBtn) {
        const row = editBtn.closest('tr');
        document.getElementById('js-rubrica-id').value = row.dataset.rubricaId || '';
        document.getElementById('js-rubrica-domain').value = row.dataset.domainId || '';
        document.getElementById('js-rubrica-codigo').value = row.dataset.codigo || '';
        document.getElementById('js-rubrica-nome').value = row.dataset.nome || '';
        document.getElementById('js-rubrica-descricao').value = row.dataset.descricao || '';
        document.getElementById('js-rubrica-ativo').checked = row.dataset.ativo === '1';
        setRubricaFormMode(true);
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
        window.location.reload();
      }
    });

    const rubricaCancel = document.getElementById('js-rubrica-cancel');
    if (rubricaCancel) {
      rubricaCancel.addEventListener('click', function(){
        resetRubricaForm();
      });
    }

    const rubricaForm = document.getElementById('js-rubrica-form');
    if (rubricaForm) {
      rubricaForm.addEventListener('submit', async function(e){
        e.preventDefault();
        const rubricaId = (document.getElementById('js-rubrica-id')?.value || '').trim();
        const domainId = document.getElementById('js-rubrica-domain')?.value;
        const codigo = document.getElementById('js-rubrica-codigo')?.value?.trim();
        const nome = document.getElementById('js-rubrica-nome')?.value?.trim();
        const descricao = document.getElementById('js-rubrica-descricao')?.value?.trim();
        const ativo = !!document.getElementById('js-rubrica-ativo')?.checked;

        const payload = { domain_id: Number(domainId), codigo, nome, descricao, ativo };
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
        window.location.reload();
      });
    }

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
        window.location.reload();
      });
    }
  });
})();
