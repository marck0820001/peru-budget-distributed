# PC4 — Etapa 2: API REST y especificación OpenAPI

El servidor HTTP en `cmd/api` reutiliza `massive.DistributedTrain` de la etapa 1. No duplica el algoritmo de PC3 y no inventa resultados. La comunicación API->nodos es TCP, cada nodo procesa un shard disjunto del binario de 3,642,510 líneas (si están montados los datos completos).

| Método | Ruta | Resultado |
|---|---|---|
| GET | `/health` | 200; metadatos del dataset y estado de la API (no comprueba nodos) |
| GET | `/api/v1/cluster/nodes` | 200; prueba de conexión TCP a cada nodo |
| POST | `/api/v1/train` | 202; `job_id` y URL de estado, trabajo asíncrono |
| GET | `/api/v1/jobs` | 200; trabajos de la sesión |
| GET | `/api/v1/jobs/{id}` | 200; `running`, `succeeded` o `failed` |
| GET | `/api/v1/jobs/{id}/result` | 200 tras finalizar; JSON completo; 409 mientras corre |
| GET | `/openapi.yaml` | Especificación OpenAPI 3.0.3 |
| GET | `/docs` | Interfaz Swagger UI (carga recursos desde CDN) |

El POST recibe un objeto con `k` (2–16, predeterminado 3), `seed` (predeterminado 42) y `max_iterations` (1–100, predeterminado 25). Para referencia PC3 mantener `k=3`, `seed=42` y 25 iteraciones máximas. Otros parámetros de entrenamiento se fijan iguales a los de PC3: `clip-z=5`, muestra de inicialización 10,000, `batch=8192`, tolerancia `1e-4`.

## Validación y latencias

Ejecutar `go test ./...`, levantar `compose.pc4.api.yaml`, comprobar `GET /health`, `GET /api/v1/cluster/nodes`, `POST /api/v1/train`, y consultar hasta estado `succeeded`. Las métricas de `GET /health`/`GET /jobs/{id}` deben medirse en Postman y registrarse, sin afirmar resultados no medidos.

Los resultados de esta etapa se guardan en `data/processed/pc4_api`, sin reemplazar los del experimento TCP previo. Los estados en memoria son transitorios; MongoDB/Redis se incorporarán posteriormente.
