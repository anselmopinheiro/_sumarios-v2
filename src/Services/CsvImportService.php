<?php

declare(strict_types=1);

namespace App\Services;

use App\Db;

final class CsvImportService
{
    public function parse(string $tmpPath, string $delimiter): array
    {
        $rows = [];
        $errors = [];

        $handle = fopen($tmpPath, 'rb');
        if (!$handle) {
            return ['headers' => [], 'rows' => [], 'errors' => ['Não foi possível abrir o CSV.']];
        }

        $headers = fgetcsv($handle, 0, $delimiter) ?: [];
        $line = 1;

        while (($data = fgetcsv($handle, 0, $delimiter)) !== false) {
            $line++;
            if (count($data) !== count($headers)) {
                $errors[] = "Linha {$line}: número de colunas inválido.";
                continue;
            }
            $rows[] = array_combine($headers, $data);
        }

        fclose($handle);

        return ['headers' => $headers, 'rows' => $rows, 'errors' => $errors];
    }

    public function importTurmas(array $rows, bool $dryRun = true): array
    {
        $conn = Db::conn();
        $inserted = 0;
        $errors = [];

        if (!$dryRun) {
            $conn->beginTransaction();
        }

        try {
            foreach ($rows as $idx => $row) {
                $nome = trim((string)($row['nome'] ?? ''));
                if ($nome === '') {
                    $errors[] = 'Linha ' . ($idx + 2) . ': nome vazio.';
                    continue;
                }

                $stmt = $conn->prepare('SELECT id FROM turmas WHERE nome = :nome LIMIT 1');
                $stmt->execute(['nome' => $nome]);
                if ($stmt->fetch()) {
                    continue;
                }

                if (!$dryRun) {
                    $ins = $conn->prepare('INSERT INTO turmas (nome, tipo, periodo_tipo, letiva) VALUES (:nome,:tipo,:periodo_tipo,1)');
                    $ins->execute([
                        'nome' => $nome,
                        'tipo' => $row['tipo'] ?? 'regular',
                        'periodo_tipo' => $row['periodo_tipo'] ?? 'anual',
                    ]);
                }
                $inserted++;
            }

            if (!$dryRun) {
                $conn->commit();
            }
        } catch (\Throwable $e) {
            if (!$dryRun && $conn->inTransaction()) {
                $conn->rollBack();
            }
            Db::logError($e);
            $errors[] = 'Erro interno durante importação.';
        }

        return ['inserted' => $inserted, 'errors' => $errors];
    }
}
