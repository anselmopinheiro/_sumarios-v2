<?php

declare(strict_types=1);

namespace App\Controllers;

final class HomeController extends BaseController
{
    public function index(): void
    {
        $this->render('dashboard', ['title' => 'Dashboard']);
    }
}
