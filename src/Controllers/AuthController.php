<?php

declare(strict_types=1);

namespace App\Controllers;

use App\Auth;

final class AuthController extends BaseController
{
    public function loginForm(): void
    {
        $this->render('login', ['title' => 'Entrar']);
    }

    public function login(): void
    {
        if (!Auth::validateCsrf($_POST['_csrf'] ?? null)) {
            $this->flash('danger', 'Token CSRF inválido.');
            $this->redirect('/login');
        }

        $username = trim((string)($_POST['username'] ?? ''));
        $password = (string)($_POST['password'] ?? '');

        if (!Auth::login($username, $password)) {
            $this->flash('danger', 'Credenciais inválidas.');
            $this->redirect('/login');
        }

        $this->redirect('/');
    }

    public function logout(): void
    {
        Auth::logout();
        $this->redirect('/login');
    }
}
