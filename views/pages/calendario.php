<?php use App\Auth; ?>
<div class="d-flex justify-content-between align-items-center mb-3">
  <h1 class="h4 mb-0">Calendário · <?= htmlspecialchars($turma['nome']) ?></h1>
  <a class="btn btn-outline-secondary btn-sm" href="/turmas">Voltar</a>
</div>

<div class="card shadow-sm">
  <div class="table-responsive">
    <table class="table align-middle mb-0">
      <thead><tr><th>Data</th><th>N.º módulo</th><th>Total</th><th>Tipo</th><th>Sumário</th><th></th></tr></thead>
      <tbody>
      <?php foreach (($aulas ?? []) as $aula): ?>
        <tr>
          <td><?= htmlspecialchars((string)$aula['data']) ?></td>
          <td><?= htmlspecialchars((string)($aula['numero_modulo'] ?? '-')) ?></td>
          <td><?= htmlspecialchars((string)($aula['total_geral'] ?? '-')) ?></td>
          <td><?= htmlspecialchars((string)$aula['tipo']) ?></td>
          <td><?= htmlspecialchars((string)($aula['sumario'] ?? '')) ?></td>
          <td>
            <button class="btn btn-sm btn-outline-primary" data-bs-toggle="modal" data-bs-target="#m<?= (int)$aula['id'] ?>">Editar</button>
            <div class="modal fade" id="m<?= (int)$aula['id'] ?>" tabindex="-1">
              <div class="modal-dialog"><div class="modal-content"><div class="modal-body">
                <form method="post" action="/aulas/update">
                  <input type="hidden" name="_csrf" value="<?= htmlspecialchars(Auth::csrfToken()) ?>">
                  <input type="hidden" name="aula_id" value="<?= (int)$aula['id'] ?>">
                  <input type="hidden" name="turma_id" value="<?= (int)$turma['id'] ?>">
                  <label class="form-label">Sumário</label>
                  <textarea class="form-control mb-2" rows="4" name="sumario"><?= htmlspecialchars((string)($aula['sumario'] ?? '')) ?></textarea>
                  <label class="form-label">Previsão</label>
                  <textarea class="form-control mb-3" rows="3" name="previsao"><?= htmlspecialchars((string)($aula['previsao'] ?? '')) ?></textarea>
                  <button class="btn btn-primary" type="submit">Guardar</button>
                </form>
              </div></div></div>
            </div>
          </td>
        </tr>
      <?php endforeach; ?>
      </tbody>
    </table>
  </div>
</div>
