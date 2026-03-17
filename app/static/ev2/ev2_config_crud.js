(function(){
  function ready(fn) {
    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', fn);
    } else {
      fn();
    }
  }

  async function parseResponse(response) {
    const text = await response.text();
    try { return JSON.parse(text); }
    catch { return { error: text || 'Erro inesperado' }; }
  }

  function showDomainError(message) {
    const box = document.getElementById('js-domain-msg');
    if (box) {
      box.textContent = message;
      box.style.display = 'block';
    }
    window.alert(message);
    console.error('[EV2 Domains]', message);
  }

  ready(function(){
    document.addEventListener('click', async function(event){
      const duplicateBtn = event.target.closest('.js-domain-duplicate');
      if (duplicateBtn) {
        const row = duplicateBtn.closest('tr');
        const currentName = row?.querySelector('.js-domain-name')?.textContent?.trim() || '';
        const suggestion = currentName ? `${currentName} (cópia)` : '';
        const newDesignation = window.prompt('Novo nome/designação do domínio duplicado:', suggestion);
        if (!newDesignation || !newDesignation.trim()) return;

        const response = await fetch('/ev2/config/domains/duplicate', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'Accept': 'application/json',
          },
          body: JSON.stringify({
            domain_id: Number(duplicateBtn.dataset.domainId),
            new_designation: newDesignation.trim(),
          }),
        });

        const data = await parseResponse(response);
        if (!response.ok) {
          showDomainError(data.error || 'Falha ao duplicar domínio.');
          return;
        }
        window.location.reload();
        return;
      }

      const deleteBtn = event.target.closest('.js-domain-delete');
      if (deleteBtn) {
        if (!window.confirm('Tem a certeza que pretende eliminar domínio?')) return;

        const response = await fetch(`/ev2/config/domains/${deleteBtn.dataset.domainId}`, {
          method: 'DELETE',
          headers: { 'Accept': 'application/json' },
        });

        const data = await parseResponse(response);
        if (!response.ok) {
          showDomainError(data.error || 'Falha ao eliminar domínio.');
          return;
        }
        window.location.reload();
      }
    });

    document.querySelectorAll('.js-delete').forEach(function(form){
      form.addEventListener('submit', function(e){
        if (!window.confirm('Tem a certeza que pretende eliminar este registo?')) {
          e.preventDefault();
        }
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
  });
})();
