<div class="card">
  <div class="card-header">Editar aula #<?= (int)$aula['id'] ?></div>
  <div class="card-body">
    <form method="post" action="<?= htmlspecialchars($basePathVar) ?>/aula/<?= (int)$aula['id'] ?>/editar">
      <div class="mb-3">
        <label class="form-label">Sumário</label>
        <textarea class="form-control" name="sumario" rows="4"><?= htmlspecialchars((string)($aula['sumario'] ?? '')) ?></textarea>
      </div>
      <div class="mb-3">
        <label class="form-label">Previsão</label>
        <textarea class="form-control" name="previsao" rows="3"><?= htmlspecialchars((string)($aula['previsao'] ?? '')) ?></textarea>
      </div>
      <button class="btn btn-primary">Guardar</button>
    </form>
  </div>
</div>
