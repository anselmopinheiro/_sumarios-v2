<?php

declare(strict_types=1);

use Sumarios\Config;
use Sumarios\Db;
use Sumarios\Router;

require_once __DIR__ . '/Config.php';
require_once __DIR__ . '/Db.php';
require_once __DIR__ . '/Router.php';

if (session_status() === PHP_SESSION_NONE) {
    session_start();
}

$configFile = dirname(__DIR__) . '/config/config.php';
$config = new Config(require $configFile);
$basePath = (string)$config->get('base_path', '/sumarios');

$storagePath = (string)$config->get('storage_path');
if (!is_dir($storagePath . '/logs')) {
    @mkdir($storagePath . '/logs', 0775, true);
}

$render = static function (string $view, array $data = []) use ($config, $basePath): void {
    extract($data, EXTR_SKIP);
    $basePathVar = $basePath;
    $viewFile = dirname(__DIR__) . '/views/pages/' . $view . '.php';
    include dirname(__DIR__) . '/views/layout.php';
};

try {
    $pdo = Db::connect($config);
} catch (Throwable $e) {
    @file_put_contents($storagePath . '/logs/error.log', '[' . date('c') . '] ' . $e->getMessage() . PHP_EOL, FILE_APPEND);
    http_response_code(500);
    echo 'Erro de ligação à base de dados.';
    return;
}

$router = new Router($basePath);

$router->get('/', function () use ($render): void {
    $render('dashboard', ['title' => 'Dashboard']);
});

$router->get('/turmas', function () use ($pdo, $render): void {
    $rows = $pdo->query('SELECT id, nome, tipo, periodo_tipo FROM turmas ORDER BY nome')->fetchAll();
    $render('turmas', ['title' => 'Turmas', 'turmas' => $rows]);
});

$router->get('/calendario', function () use ($pdo, $render): void {
    $sql = 'SELECT id, data, tipo, total_geral, sumario FROM calendario_aulas WHERE apagado = 0 ORDER BY data DESC, id DESC LIMIT 100';
    $rows = $pdo->query($sql)->fetchAll();
    $render('calendario', ['title' => 'Calendário (semana)', 'aulas' => $rows]);
});

$router->get('/aula/{id}/editar', function (array $params) use ($pdo, $render): void {
    $stmt = $pdo->prepare('SELECT id, data, sumario, previsao, tipo FROM calendario_aulas WHERE id = :id');
    $stmt->execute(['id' => (int)$params['id']]);
    $aula = $stmt->fetch();
    if (!$aula) {
        http_response_code(404);
        echo 'Aula não encontrada';
        return;
    }
    $render('aula_editar', ['title' => 'Editar aula', 'aula' => $aula]);
});

$router->post('/aula/{id}/editar', function (array $params) use ($pdo, $basePath): void {
    $sumario = trim((string)($_POST['sumario'] ?? ''));
    $previsao = trim((string)($_POST['previsao'] ?? ''));
    $stmt = $pdo->prepare('UPDATE calendario_aulas SET sumario=:sumario, previsao=:previsao WHERE id=:id');
    $stmt->execute(['sumario' => $sumario, 'previsao' => $previsao, 'id' => (int)$params['id']]);
    header('Location: ' . $basePath . '/calendario');
});

$router->get('/importar', function () use ($render): void {
    $render('importar', ['title' => 'Importar CSV']);
});

$router->post('/importar', function () use ($pdo, $render): void {
    $errors = [];
    $preview = [];
    $headers = [];
    $result = ['inserted' => 0];

    if (!isset($_FILES['csv']) || $_FILES['csv']['error'] !== UPLOAD_ERR_OK) {
        $errors[] = 'Upload inválido.';
        $render('importar', compact('errors', 'preview', 'headers', 'result') + ['title' => 'Importar CSV']);
        return;
    }

    $delimiter = ($_POST['delimiter'] ?? ';') === ',' ? ',' : ';';
    $mode = ($_POST['mode'] ?? 'dry-run') === 'import' ? 'import' : 'dry-run';

    $fh = fopen($_FILES['csv']['tmp_name'], 'rb');
    $headers = fgetcsv($fh ?: null, 0, $delimiter) ?: [];
    $required = ['nome', 'tipo', 'periodo_tipo'];
    foreach ($required as $h) {
        if (!in_array($h, $headers, true)) {
            $errors[] = 'Cabeçalho em falta: ' . $h;
        }
    }

    $rows = [];
    $line = 1;
    while ($fh && ($row = fgetcsv($fh, 0, $delimiter)) !== false) {
        $line++;
        if (count($row) !== count($headers)) {
            $errors[] = "Linha {$line}: número de colunas inválido.";
            continue;
        }
        $assoc = array_combine($headers, $row);
        if (!is_array($assoc)) {
            $errors[] = "Linha {$line}: erro de mapeamento.";
            continue;
        }
        if (trim((string)($assoc['nome'] ?? '')) === '') {
            $errors[] = "Linha {$line}: nome vazio.";
            continue;
        }
        $rows[] = $assoc;
    }
    if ($fh) {
        fclose($fh);
    }

    $preview = array_slice($rows, 0, 20);

    if ($mode === 'import' && !$errors) {
        $pdo->beginTransaction();
        try {
            foreach ($rows as $idx => $r) {
                $check = $pdo->prepare('SELECT id FROM turmas WHERE nome = :nome LIMIT 1');
                $check->execute(['nome' => trim((string)$r['nome'])]);
                if ($check->fetch()) {
                    continue;
                }
                $ins = $pdo->prepare('INSERT INTO turmas (nome, tipo, periodo_tipo, letiva) VALUES (:nome,:tipo,:periodo_tipo,1)');
                $ins->execute([
                    'nome' => trim((string)$r['nome']),
                    'tipo' => trim((string)($r['tipo'] ?? 'regular')),
                    'periodo_tipo' => trim((string)($r['periodo_tipo'] ?? 'anual')),
                ]);
                $result['inserted']++;
            }
            $pdo->commit();
        } catch (Throwable $e) {
            $pdo->rollBack();
            $errors[] = 'Erro ao importar: ' . $e->getMessage();
        }
    }

    $render('importar', ['title' => 'Importar CSV', 'errors' => $errors, 'preview' => $preview, 'headers' => $headers, 'result' => $result, 'mode' => $mode]);
});

$router->dispatch($_SERVER['REQUEST_METHOD'] ?? 'GET', $_SERVER['REQUEST_URI'] ?? '/');
