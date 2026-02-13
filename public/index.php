<?php

declare(strict_types=1);

use App\Auth;
use App\Controllers\AuthController;
use App\Controllers\HomeController;
use App\Controllers\ImportController;
use App\Controllers\TurmaController;
use App\Repositories\AulaRepository;
use App\Repositories\TurmaRepository;
use App\Router;
use App\Services\CsvImportService;

spl_autoload_register(static function (string $class): void {
    $prefix = 'App\\';
    if (!str_starts_with($class, $prefix)) {
        return;
    }
    $relative = substr($class, strlen($prefix));
    $file = dirname(__DIR__) . '/src/' . str_replace('\\', '/', $relative) . '.php';
    if (is_file($file)) {
        require_once $file;
    }
});

Auth::start();

$router = new Router();
$authController = new AuthController();
$homeController = new HomeController();
$turmaController = new TurmaController(new TurmaRepository(), new AulaRepository());
$importController = new ImportController(new CsvImportService());

$router->get('/', static fn() => Auth::check() ? $homeController->index() : $authController->loginForm());
$router->get('/login', static fn() => $authController->loginForm());
$router->post('/login', static fn() => $authController->login());
$router->post('/logout', static fn() => $authController->logout());
$router->get('/turmas', static fn() => $turmaController->index());
$router->post('/turmas', static fn() => $turmaController->create());
$router->get('/calendario', static fn() => $turmaController->calendario());
$router->post('/aulas/update', static fn() => $turmaController->updateAula());
$router->get('/importar', static fn() => $importController->form());
$router->post('/importar', static fn() => $importController->upload());

try {
    $router->dispatch($_SERVER['REQUEST_METHOD'] ?? 'GET', $_SERVER['REQUEST_URI'] ?? '/');
} catch (Throwable $e) {
    App\Db::logError($e);
    http_response_code(500);
    echo 'Erro interno.';
}
