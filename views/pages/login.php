<?php use App\Auth; ?>
<div class="row justify-content-center">
  <div class="col-md-5 col-lg-4">
    <div class="card shadow-sm">
      <div class="card-body">
        <h1 class="h4 mb-3">Entrar</h1>
        <form method="post" action="/login">
          <input type="hidden" name="_csrf" value="<?= htmlspecialchars(Auth::csrfToken()) ?>">
          <div class="mb-3">
            <label class="form-label">Utilizador</label>
            <input class="form-control" name="username" required>
          </div>
          <div class="mb-3">
            <label class="form-label">Palavra-passe</label>
            <input class="form-control" type="password" name="password" required>
          </div>
          <button class="btn btn-primary w-100" type="submit">Entrar</button>
        </form>
      </div>
    </div>
  </div>
</div>
