<?php

declare(strict_types=1);

return [
    'app_name' => 'Sumários',
    'base_path' => '/sumarios',
    'db' => [
        'host' => '127.0.0.1',
        'port' => 3306,
        'name' => 'sumarios',
        'user' => 'root',
        'pass' => '',
        'charset' => 'utf8mb4',
    ],
    'storage_path' => dirname(__DIR__) . '/storage',
];
