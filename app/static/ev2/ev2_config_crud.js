(function(){
  document.querySelectorAll('.js-delete').forEach(function(form){
    form.addEventListener('submit', function(e){
      if (!window.confirm('Tem a certeza que pretende eliminar este registo?')) {
        e.preventDefault();
      }
    });
  });

  document.querySelectorAll('.js-duplicate-domain').forEach(function(form){
    form.addEventListener('submit', function(e){
      var input = form.querySelector('input[name="new_name"]');
      var currentNameCell = form.closest('tr')?.querySelector('td:nth-child(2)');
      var suggestion = currentNameCell ? (currentNameCell.textContent.trim() + ' (cópia)') : '';
      var newName = window.prompt('Novo nome do domínio duplicado:', suggestion);
      if (!newName) {
        e.preventDefault();
        return;
      }
      input.value = newName.trim();
      if (!input.value) {
        e.preventDefault();
      }
    });
  });

  document.querySelectorAll('.js-import-rubricas').forEach(function(form){
    form.addEventListener('submit', function(e){
      var source = form.querySelector('select[name="source_domain_id"]')?.value;
      var target = form.querySelector('select[name="target_domain_id"]')?.value;
      if (!source || !target) {
        return;
      }
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
