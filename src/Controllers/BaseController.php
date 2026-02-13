<?php

declare(strict_types=1);

namespace App\Controllers;

abstract class BaseController
{
    protected function render(string $view, array $data = []): void
    {
        extract($data, EXTR_SKIP);
        $viewFile = dirname(__DIR__, 2) . '/views/pages/' . $view . '.php';
        include dirname(__DIR__, 2) . '/views/layout.php';
    }

    protected function redirect(string $path): void
    {
        header('Location: ' . $path);
        exit;
    }

    protected function flash(string $type, string $message): void
    {
        $_SESSION['_flash'][] = ['type' => $type, 'message' => $message];
    }
}
