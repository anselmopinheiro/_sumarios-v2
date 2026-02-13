<?php

use App\Auth;

$flash = $_SESSION['_flash'] ?? [];
unset($_SESSION['_flash']);
?>
<!doctype html>
<html lang="pt">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title><?= htmlspecialchars($title ?? 'Sumários') ?></title>
  <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootswatch@5.3.3/dist/flatly/bootstrap.min.css">
  <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.3/font/bootstrap-icons.min.css">
  <style>
    body { min-height: 100vh; }
    .app-shell { display: grid; grid-template-columns: 260px 1fr; min-height: 100vh; }
    .sidebar { background: #f8f9fa; border-right: 1px solid #e9ecef; }
    @media (max-width: 991px) { .app-shell { grid-template-columns: 1fr; } }
  </style>
</head>
<body>
<div class="app-shell">
  <aside class="sidebar p-3">
    <div class="h5 mb-3">Gestor letivo PHP</div>
    <?php if (Auth::check()): ?>
      <nav class="nav flex-column gap-1">
        <a class="nav-link px-0" href="/">Dashboard</a>
        <a class="nav-link px-0" href="/turmas">Turmas</a>
        <a class="nav-link px-0" href="/importar">Importar CSV</a>
      </nav>
      <form class="mt-3" method="post" action="/logout">
        <input type="hidden" name="_csrf" value="<?= htmlspecialchars(Auth::csrfToken()) ?>">
        <button class="btn btn-outline-secondary btn-sm" type="submit">Sair</button>
      </form>
    <?php endif; ?>
  </aside>
  <main class="p-3 p-lg-4">
    <?php foreach ($flash as $item): ?>
      <div class="alert alert-<?= htmlspecialchars($item['type']) ?>"><?= htmlspecialchars($item['message']) ?></div>
    <?php endforeach; ?>
    <?php include $viewFile; ?>
  </main>
</div>
<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/js/bootstrap.bundle.min.js"></script>
</body>
</html>
