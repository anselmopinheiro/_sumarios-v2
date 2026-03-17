(function(){
  document.querySelectorAll('.js-delete').forEach(function(form){
    form.addEventListener('submit', function(e){
      if (!window.confirm('Tem a certeza que pretende eliminar este registo?')) {
        e.preventDefault();
      }
    });
  });

  async function parseResponse(response) {
    const text = await response.text();
    try { return JSON.parse(text); } catch { return { error: text || 'Erro inesperado' }; }
  }

  document.querySelectorAll('.js-domain-duplicate').forEach(function(btn){
    btn.addEventListener('click', async function(){
      const row = btn.closest('tr');
      const currentName = row?.querySelector('.js-domain-name')?.textContent?.trim() || '';
      const suggestion = currentName ? `${currentName} (cópia)` : '';
      const newDesignation = window.prompt('Novo nome/designação do domínio duplicado:', suggestion);
      if (!newDesignation || !newDesignation.trim()) return;

      const response = await fetch('/ev2/config/domains/duplicate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'Accept': 'application/json' },
        body: JSON.stringify({
          domain_id: Number(btn.dataset.domainId),
          new_designation: newDesignation.trim(),
        }),
      });
      const data = await parseResponse(response);
      if (!response.ok) {
        window.alert(data.error || 'Falha ao duplicar domínio.');
        return;
      }
      window.location.reload();
    });
  });

  document.querySelectorAll('.js-domain-delete').forEach(function(btn){
    btn.addEventListener('click', async function(){
      if (!window.confirm('Tem a certeza que pretende eliminar domínio?')) return;
      const response = await fetch(`/ev2/config/domains/${btn.dataset.domainId}`, {
        method: 'DELETE',
        headers: { 'Accept': 'application/json' },
      });
      const data = await parseResponse(response);
      if (!response.ok) {
        window.alert(data.error || 'Falha ao eliminar domínio.');
        return;
      }
      window.location.reload();
    });
  });

  document.querySelectorAll('.js-import-rubricas').forEach(function(form){
    form.addEventListener('submit', function(e){
      var source = form.querySelector('select[name="source_domain_id"]')?.value;
      var target = form.querySelector('select[name="target_domain_id"]')?.value;
      if (!source || !target) return;
      if (source === target) {
        e.preventDefault();
        window.alert('Origem e destino devem ser diferentes.');
        return;
      }
      if (!window.confirm('Importar todas as rubricas do domínio origem para o destino?')) {
        e.preventDefault();
      }
    });
  });
})();
