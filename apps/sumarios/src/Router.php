<?php

declare(strict_types=1);

namespace Sumarios;

final class Router
{
    private array $routes = [];

    public function __construct(private string $basePath)
    {
        $this->basePath = rtrim($basePath, '/');
    }

    public function get(string $path, callable $handler): void { $this->add('GET', $path, $handler); }
    public function post(string $path, callable $handler): void { $this->add('POST', $path, $handler); }

    private function add(string $method, string $path, callable $handler): void
    {
        $this->routes[$method][] = ['path' => $path, 'handler' => $handler];
    }

    public function dispatch(string $method, string $uri): void
    {
        $path = parse_url($uri, PHP_URL_PATH) ?: '/';
        if ($this->basePath !== '' && str_starts_with($path, $this->basePath)) {
            $path = substr($path, strlen($this->basePath)) ?: '/';
        }

        foreach ($this->routes[$method] ?? [] as $route) {
            $regex = preg_replace('#\{([a-zA-Z_][a-zA-Z0-9_]*)\}#', '(?P<$1>[^/]+)', $route['path']);
            $regex = '#^' . $regex . '$#';
            if (preg_match($regex, $path, $matches)) {
                $params = array_filter($matches, static fn($k) => !is_int($k), ARRAY_FILTER_USE_KEY);
                $route['handler']($params);
                return;
            }
        }

        http_response_code(404);
        echo 'Página não encontrada';
    }
}
