<?php

declare(strict_types=1);

namespace Sumarios;

use PDO;

final class Db
{
    public static function connect(Config $config): PDO
    {
        $dsn = sprintf(
            'mysql:host=%s;port=%d;dbname=%s;charset=%s',
            $config->get('db.host'),
            (int)$config->get('db.port'),
            $config->get('db.name'),
            $config->get('db.charset', 'utf8mb4')
        );

        return new PDO($dsn, (string)$config->get('db.user'), (string)$config->get('db.pass'), [
            PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION,
            PDO::ATTR_DEFAULT_FETCH_MODE => PDO::FETCH_ASSOC,
            PDO::ATTR_EMULATE_PREPARES => false,
        ]);
    }
}
