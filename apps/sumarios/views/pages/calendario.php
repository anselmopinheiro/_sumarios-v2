<div class="card">
  <div class="card-header">Calendário (semana)</div>
  <div class="table-responsive">
    <table class="table mb-0">
      <thead><tr><th>Data</th><th>Tipo</th><th>Total</th><th>Sumário</th><th></th></tr></thead>
      <tbody>
      <?php foreach (($aulas ?? []) as $a): ?>
        <tr>
          <td><?= htmlspecialchars((string)$a['data']) ?></td>
          <td><?= htmlspecialchars((string)$a['tipo']) ?></td>
          <td><?= htmlspecialchars((string)$a['total_geral']) ?></td>
          <td><?= htmlspecialchars((string)($a['sumario'] ?? '')) ?></td>
          <td><a class="btn btn-sm btn-outline-primary" href="<?= htmlspecialchars($basePathVar) ?>/aula/<?= (int)$a['id'] ?>/editar">Editar</a></td>
        </tr>
      <?php endforeach; ?>
      </tbody>
    </table>
  </div>
</div>
