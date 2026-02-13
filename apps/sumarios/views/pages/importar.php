<div class="card mb-3">
  <div class="card-body">
    <form method="post" enctype="multipart/form-data" action="<?= htmlspecialchars($basePathVar) ?>/importar">
      <div class="row g-2">
        <div class="col-md-3">
          <select class="form-select" name="delimiter"><option value=";">;</option><option value=",">,</option></select>
        </div>
        <div class="col-md-3">
          <select class="form-select" name="mode"><option value="dry-run">dry-run</option><option value="import">import</option></select>
        </div>
        <div class="col-md-4"><input class="form-control" type="file" name="csv" accept=".csv" required></div>
        <div class="col-md-2"><button class="btn btn-primary w-100">Executar</button></div>
      </div>
    </form>
  </div>
</div>

<?php foreach (($errors ?? []) as $e): ?><div class="alert alert-danger py-1"><?= htmlspecialchars($e) ?></div><?php endforeach; ?>
<div class="alert alert-info py-1">Inseridos: <?= (int)($result['inserted'] ?? 0) ?></div>

<?php if (!empty($preview)): ?>
<div class="card"><div class="card-header">Pré-visualização (20 linhas)</div><div class="table-responsive"><table class="table mb-0"><thead><tr><?php foreach (($headers ?? []) as $h): ?><th><?= htmlspecialchars((string)$h) ?></th><?php endforeach; ?></tr></thead><tbody><?php foreach ($preview as $r): ?><tr><?php foreach (($headers ?? []) as $h): ?><td><?= htmlspecialchars((string)($r[$h] ?? '')) ?></td><?php endforeach; ?></tr><?php endforeach; ?></tbody></table></div></div>
<?php endif; ?>
