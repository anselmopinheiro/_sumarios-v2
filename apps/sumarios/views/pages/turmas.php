<div class="card">
  <div class="card-header">Turmas</div>
  <div class="table-responsive">
    <table class="table mb-0">
      <thead><tr><th>ID</th><th>Nome</th><th>Tipo</th><th>Período</th></tr></thead>
      <tbody>
      <?php foreach (($turmas ?? []) as $t): ?>
        <tr>
          <td><?= (int)$t['id'] ?></td>
          <td><?= htmlspecialchars((string)$t['nome']) ?></td>
          <td><?= htmlspecialchars((string)$t['tipo']) ?></td>
          <td><?= htmlspecialchars((string)$t['periodo_tipo']) ?></td>
        </tr>
      <?php endforeach; ?>
      </tbody>
    </table>
  </div>
</div>
