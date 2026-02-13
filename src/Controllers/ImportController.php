<?php

declare(strict_types=1);

namespace App\Controllers;

use App\Auth;
use App\Services\CsvImportService;

final class ImportController extends BaseController
{
    public function __construct(private readonly CsvImportService $service)
    {
    }

    public function form(): void
    {
        Auth::requireAuth();
        $this->render('importar', ['title' => 'Importar CSV']);
    }

    public function upload(): void
    {
        Auth::requireAuth();
        if (!Auth::validateCsrf($_POST['_csrf'] ?? null)) {
            $this->flash('danger', 'Token CSRF inválido.');
            $this->redirect('/importar');
        }

        if (!isset($_FILES['csv']) || $_FILES['csv']['error'] !== UPLOAD_ERR_OK) {
            $this->flash('danger', 'Upload inválido.');
            $this->redirect('/importar');
        }

        $delimiter = ($_POST['delimiter'] ?? ';') === ',' ? ',' : ';';
        $parsed = $this->service->parse($_FILES['csv']['tmp_name'], $delimiter);

        $result = ['inserted' => 0, 'errors' => []];
        if (($_POST['table'] ?? '') === 'turmas') {
            $dryRun = ($_POST['mode'] ?? 'dry-run') === 'dry-run';
            $result = $this->service->importTurmas($parsed['rows'], $dryRun);
        }

        $this->render('importar', [
            'title' => 'Importar CSV',
            'previewHeaders' => $parsed['headers'],
            'previewRows' => array_slice($parsed['rows'], 0, 20),
            'parseErrors' => $parsed['errors'],
            'result' => $result,
        ]);
    }
}
