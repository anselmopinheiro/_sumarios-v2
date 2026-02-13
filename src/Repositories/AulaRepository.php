<?php

declare(strict_types=1);

namespace App\Repositories;

use App\Db;

final class AulaRepository
{
    public function byTurma(int $turmaId): array
    {
        $stmt = Db::conn()->prepare('SELECT ca.*, m.nome AS modulo_nome
            FROM calendario_aulas ca
            LEFT JOIN modulos m ON m.id = ca.modulo_id
            WHERE ca.turma_id = :turma_id AND ca.apagado = 0
            ORDER BY ca.data DESC, ca.id DESC
            LIMIT 200');
        $stmt->execute(['turma_id' => $turmaId]);
        return $stmt->fetchAll();
    }

    public function updateSummary(int $id, string $sumario, string $previsao): void
    {
        $stmt = Db::conn()->prepare('UPDATE calendario_aulas SET sumario=:sumario, previsao=:previsao WHERE id=:id');
        $stmt->execute(['id' => $id, 'sumario' => $sumario, 'previsao' => $previsao]);
    }
}
