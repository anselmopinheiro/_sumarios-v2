<?php

declare(strict_types=1);

namespace App;

final class Config
{
    public static function get(string $key, mixed $default = null): mixed
    {
        static $env = null;

        if ($env === null) {
            $env = [];
            $envFile = dirname(__DIR__) . '/.env';
            if (is_file($envFile)) {
                $lines = file($envFile, FILE_IGNORE_NEW_LINES | FILE_SKIP_EMPTY_LINES) ?: [];
                foreach ($lines as $line) {
                    $line = trim($line);
                    if ($line === '' || str_starts_with($line, '#') || !str_contains($line, '=')) {
                        continue;
                    }
                    [$k, $v] = array_map('trim', explode('=', $line, 2));
                    $env[$k] = trim($v, "\"'");
                }
            }
        }

        return $_ENV[$key] ?? $_SERVER[$key] ?? $env[$key] ?? $default;
    }
}
