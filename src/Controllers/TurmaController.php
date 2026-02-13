<?php

declare(strict_types=1);

namespace App\Controllers;

use App\Auth;
use App\Repositories\AulaRepository;
use App\Repositories\TurmaRepository;

final class TurmaController extends BaseController
{
    public function __construct(
        private readonly TurmaRepository $turmas,
        private readonly AulaRepository $aulas,
    ) {
    }

    public function index(): void
    {
        Auth::requireAuth();
        $this->render('turmas', [
            'title' => 'Turmas',
            'turmas' => $this->turmas->all(),
        ]);
    }

    public function create(): void
    {
        Auth::requireAuth();
        if (!Auth::validateCsrf($_POST['_csrf'] ?? null)) {
            $this->flash('danger', 'Token CSRF inválido.');
            $this->redirect('/turmas');
        }

        $nome = trim((string)($_POST['nome'] ?? ''));
        if ($nome === '') {
            $this->flash('danger', 'Nome da turma é obrigatório.');
            $this->redirect('/turmas');
        }

        $this->turmas->create([
            'nome' => $nome,
            'tipo' => $_POST['tipo'] ?? 'regular',
            'periodo_tipo' => $_POST['periodo_tipo'] ?? 'anual',
            'ano_letivo_id' => $_POST['ano_letivo_id'] ?? null,
        ]);

        $this->flash('success', 'Turma criada.');
        $this->redirect('/turmas');
    }

    public function calendario(): void
    {
        Auth::requireAuth();
        $turmaId = (int)($_GET['turma_id'] ?? 0);
        $turma = $this->turmas->find($turmaId);
        if (!$turma) {
            $this->flash('danger', 'Turma não encontrada.');
            $this->redirect('/turmas');
        }

        $this->render('calendario', [
            'title' => 'Calendário',
            'turma' => $turma,
            'aulas' => $this->aulas->byTurma($turmaId),
        ]);
    }

    public function updateAula(): void
    {
        Auth::requireAuth();
        if (!Auth::validateCsrf($_POST['_csrf'] ?? null)) {
            $this->flash('danger', 'Token CSRF inválido.');
            $this->redirect('/turmas');
        }

        $aulaId = (int)($_POST['aula_id'] ?? 0);
        $turmaId = (int)($_POST['turma_id'] ?? 0);
        $this->aulas->updateSummary($aulaId, trim((string)($_POST['sumario'] ?? '')), trim((string)($_POST['previsao'] ?? '')));
        $this->flash('success', 'Aula atualizada.');
        $this->redirect('/calendario?turma_id=' . $turmaId);
    }
}
