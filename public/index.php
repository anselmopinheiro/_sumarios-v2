<?php

declare(strict_types=1);

$paths = [
    getenv('SUMARIOS_APP_BOOTSTRAP') ?: '',
    '/apps/sumarios/src/bootstrap.php',
    dirname(__DIR__) . '/apps/sumarios/src/bootstrap.php',
];

foreach ($paths as $bootstrap) {
    if ($bootstrap !== '' && is_file($bootstrap)) {
        require $bootstrap;
        exit;
    }
}

http_response_code(500);
echo 'Bootstrap da aplicação não encontrado.';
