<?php use App\Auth; ?>
<div class="row g-3">
  <div class="col-lg-5">
    <div class="card shadow-sm">
      <div class="card-body">
        <h1 class="h4">Importar CSV</h1>
        <form method="post" action="/importar" enctype="multipart/form-data">
          <input type="hidden" name="_csrf" value="<?= htmlspecialchars(Auth::csrfToken()) ?>">
          <div class="mb-2">
            <label class="form-label">Tabela</label>
            <select class="form-select" name="table"><option value="turmas">Turmas</option></select>
          </div>
          <div class="mb-2">
            <label class="form-label">Separador</label>
            <select class="form-select" name="delimiter"><option value=";">Ponto e vírgula</option><option value=",">Vírgula</option></select>
          </div>
          <div class="mb-2">
            <label class="form-label">Modo</label>
            <select class="form-select" name="mode"><option value="dry-run">Dry-run</option><option value="import">Importar</option></select>
          </div>
          <div class="mb-3"><input class="form-control" type="file" name="csv" accept=".csv" required></div>
          <button class="btn btn-primary" type="submit">Executar</button>
        </form>
      </div>
    </div>
  </div>
  <div class="col-lg-7">
    <div class="card shadow-sm">
      <div class="card-body">
        <h2 class="h5">Resultado</h2>
        <?php if (!empty($result)): ?>
          <p class="mb-2">Linhas válidas: <?= (int)$result['inserted'] ?>.</p>
        <?php endif; ?>
        <?php foreach (($parseErrors ?? []) as $err): ?><div class="alert alert-warning py-1"><?= htmlspecialchars($err) ?></div><?php endforeach; ?>
        <?php foreach (($result['errors'] ?? []) as $err): ?><div class="alert alert-danger py-1"><?= htmlspecialchars($err) ?></div><?php endforeach; ?>
        <?php if (!empty($previewRows)): ?>
          <div class="table-responsive">
            <table class="table table-sm">
              <thead><tr><?php foreach (($previewHeaders ?? []) as $h): ?><th><?= htmlspecialchars((string)$h) ?></th><?php endforeach; ?></tr></thead>
              <tbody>
                <?php foreach ($previewRows as $r): ?><tr><?php foreach ($previewHeaders as $h): ?><td><?= htmlspecialchars((string)($r[$h] ?? '')) ?></td><?php endforeach; ?></tr><?php endforeach; ?>
              </tbody>
            </table>
          </div>
        <?php endif; ?>
      </div>
    </div>
  </div>
</div>
