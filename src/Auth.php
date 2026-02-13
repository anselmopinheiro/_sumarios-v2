<?php

declare(strict_types=1);

namespace App;

final class Auth
{
    public static function start(): void
    {
        if (session_status() === PHP_SESSION_NONE) {
            session_start();
        }
    }

    public static function login(string $username, string $password): bool
    {
        $storedUser = (string) Config::get('APP_USER', 'admin');
        $storedHash = (string) Config::get('APP_PASSWORD_HASH', '');
        if ($storedHash === '') {
            return false;
        }

        if (hash_equals($storedUser, $username) && password_verify($password, $storedHash)) {
            $_SESSION['user'] = $storedUser;
            return true;
        }

        return false;
    }

    public static function logout(): void
    {
        unset($_SESSION['user']);
    }

    public static function check(): bool
    {
        return isset($_SESSION['user']);
    }

    public static function requireAuth(): void
    {
        if (!self::check()) {
            header('Location: /login');
            exit;
        }
    }

    public static function csrfToken(): string
    {
        if (!isset($_SESSION['_csrf'])) {
            $_SESSION['_csrf'] = bin2hex(random_bytes(32));
        }

        return $_SESSION['_csrf'];
    }

    public static function validateCsrf(?string $token): bool
    {
        return is_string($token) && isset($_SESSION['_csrf']) && hash_equals($_SESSION['_csrf'], $token);
    }
}
