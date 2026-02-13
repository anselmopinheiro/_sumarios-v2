<?php use App\Auth; ?>
<div class="d-flex justify-content-between align-items-center mb-3">
  <h1 class="h4 mb-0">Turmas</h1>
</div>

<div class="card shadow-sm mb-3">
  <div class="card-body">
    <form class="row g-2" method="post" action="/turmas">
      <input type="hidden" name="_csrf" value="<?= htmlspecialchars(Auth::csrfToken()) ?>">
      <div class="col-md-4"><input class="form-control" name="nome" placeholder="Nome da turma" required></div>
      <div class="col-md-3">
        <select class="form-select" name="tipo">
          <option value="regular">Regular</option>
          <option value="profissional">Profissional</option>
        </select>
      </div>
      <div class="col-md-3">
        <select class="form-select" name="periodo_tipo">
          <option value="anual">Anual</option>
          <option value="semestre1">1.º semestre</option>
          <option value="semestre2">2.º semestre</option>
        </select>
      </div>
      <div class="col-md-2"><button class="btn btn-primary w-100">Guardar</button></div>
    </form>
  </div>
</div>

<div class="card shadow-sm">
  <div class="table-responsive">
    <table class="table table-hover mb-0">
      <thead><tr><th>Turma</th><th>Tipo</th><th>Período</th><th>Ano letivo</th><th></th></tr></thead>
      <tbody>
      <?php foreach (($turmas ?? []) as $turma): ?>
        <tr>
          <td><?= htmlspecialchars($turma['nome']) ?></td>
          <td><?= htmlspecialchars($turma['tipo']) ?></td>
          <td><?= htmlspecialchars($turma['periodo_tipo']) ?></td>
          <td><?= htmlspecialchars($turma['ano_letivo'] ?? '-') ?></td>
          <td><a class="btn btn-sm btn-outline-primary" href="/calendario?turma_id=<?= (int)$turma['id'] ?>">Calendário</a></td>
        </tr>
      <?php endforeach; ?>
      </tbody>
    </table>
  </div>
</div>
