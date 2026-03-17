(function(){
  document.querySelectorAll('.js-delete').forEach(function(form){
    form.addEventListener('submit', function(e){
      if (!window.confirm('Tem a certeza que pretende eliminar este registo?')) {
        e.preventDefault();
      }
    });
  });
})();
