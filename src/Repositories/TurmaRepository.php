<?php

declare(strict_types=1);

namespace App\Repositories;

use App\Db;

final class TurmaRepository
{
    public function all(): array
    {
        $sql = 'SELECT t.id, t.nome, t.tipo, t.periodo_tipo, al.nome AS ano_letivo
                FROM turmas t
                LEFT JOIN anos_letivos al ON al.id = t.ano_letivo_id
                ORDER BY t.nome';
        return Db::conn()->query($sql)->fetchAll();
    }

    public function find(int $id): ?array
    {
        $stmt = Db::conn()->prepare('SELECT * FROM turmas WHERE id = :id');
        $stmt->execute(['id' => $id]);
        return $stmt->fetch() ?: null;
    }

    public function create(array $data): void
    {
        $stmt = Db::conn()->prepare('INSERT INTO turmas (nome, tipo, periodo_tipo, ano_letivo_id, letiva) VALUES (:nome,:tipo,:periodo_tipo,:ano_letivo_id,1)');
        $stmt->execute([
            'nome' => $data['nome'],
            'tipo' => $data['tipo'],
            'periodo_tipo' => $data['periodo_tipo'],
            'ano_letivo_id' => $data['ano_letivo_id'] ?: null,
        ]);
    }
}
