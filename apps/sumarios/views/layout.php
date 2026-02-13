<!doctype html>
<html lang="pt">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title><?= htmlspecialchars($title ?? 'Sumários') ?></title>
  <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootswatch@5.3.3/dist/lux/bootstrap.min.css">
</head>
<body>
<div class="container py-4">
  <nav class="mb-4">
    <a class="me-3" href="<?= htmlspecialchars($basePathVar) ?>/">Dashboard</a>
    <a class="me-3" href="<?= htmlspecialchars($basePathVar) ?>/turmas">Turmas</a>
    <a class="me-3" href="<?= htmlspecialchars($basePathVar) ?>/calendario">Calendário</a>
    <a href="<?= htmlspecialchars($basePathVar) ?>/importar">Importar</a>
  </nav>
  <?php include $viewFile; ?>
</div>
</body>
</html>
