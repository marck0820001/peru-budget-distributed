# PeruBudget Distributed — PC4 Etapa 2: REST API y Swagger

**Dependencia:** ejecutar después de integrar la etapa 1 (`cmd/mlnode`, `internal/ml/massive/distributed.go`). Se reutiliza el binario PC3: `data/processed/massive_mef/budget_lines.f64` y sus metadatos. No sobrescribe resultados PC3 ni PC4 etapa 1.

## 1. Copiar archivos en el repositorio

En la rama de trabajo PC4, extrae este ZIP en la **raíz del repositorio**, respetando las rutas. El paquete añade `cmd/api`, `internal/api`, `compose.pc4.api.yaml`, `deployments/docker/Dockerfile.pc4-api`, `scripts/pc4/verify_api.ps1` y `docs/pc4/02-api-rest-swagger.md`.

```powershell
Test-Path data/processed/massive_mef/budget_lines.f64
Test-Path data/processed/massive_mef/budget_lines_metadata.json
go test ./...
docker compose -f compose.pc4.api.yaml config
```

## 2. Levantar API y nodos

Antes, apaga el clúster de etapa 1 si todavía sigue en ejecución:

```powershell
docker compose -f compose.pc4.cluster.yaml down
New-Item -ItemType Directory -Path data/processed/pc4_api -Force | Out-Null
docker compose -f compose.pc4.api.yaml up -d --build
docker compose -f compose.pc4.api.yaml ps
```

- Swagger UI: **http://localhost:8080/docs** (requiere acceso a CDN para cargar UI).
- OpenAPI YAML disponible sin CDN: **http://localhost:8080/openapi.yaml**.
- Salud: **http://localhost:8080/health**.

## 3. Validar API (sin iniciar entrenamiento)

```powershell
powershell -ExecutionPolicy Bypass -File scripts/pc4/verify_api.ps1
```

## 4. Entrenar desde la API de forma asíncrona

```powershell
powershell -ExecutionPolicy Bypass -File scripts/pc4/verify_api.ps1 -RunTraining
```

Alternativa manual (PowerShell):

```powershell
$body = @{ k = 3; seed = 42; max_iterations = 25 } | ConvertTo-Json
$job = Invoke-RestMethod -Uri http://localhost:8080/api/v1/train -Method Post -ContentType 'application/json' -Body $body
$job
Invoke-RestMethod -Uri "http://localhost:8080/api/v1/jobs/$($job.job_id)"
Invoke-RestMethod -Uri "http://localhost:8080/api/v1/jobs/$($job.job_id)/result"
```

La respuesta inicial es **HTTP 202 Accepted**, con un `job_id`, no el resultado final. Un trabajo simultáneo adicional devuelve **409 Conflict**. El entrenador se ejecuta en segundo plano dentro del contenedor API y se comunica con los nodos mediante TCP. La carpeta `data/processed/pc4_api` almacena los reportes de forma separada.

## 5. Logs y evidencias

```powershell
docker compose -f compose.pc4.api.yaml logs --no-color api node-a node-b
```

Capturas de Swagger UI; POST 202; GET trabajo `running` y luego `succeeded`; GET resultado con inercia, filas y tamaños; logs con shards distintos. Medir latencia de `/health` y GET estado en Postman (repeticiones, misma máquina). **No se ha comprobado todavía el objetivo <100 ms**, se debe medir. No confundir latencia HTTP con los segundos del entrenamiento.

## 6. Limitaciones reales

- La API funciona con un único entrenamiento activo y mantiene los estados en **memoria**. Al reiniciar el contenedor se pierden los IDs y sus estados; los JSON que ya fueron guardados permanecen en `data/processed/pc4_api`.
- La API **no tiene autenticación**: se publica exclusivamente en `127.0.0.1:8080` para pruebas locales. No exponer a Internet.
- MongoDB y Redis **aún no están integrados**: será la etapa 3.
- Swagger UI descarga recursos desde un CDN; el documento OpenAPI YAML está embebido y funciona sin Internet.
- La primera ejecución se debe validar en el Docker Desktop del usuario; este paquete contiene código y pruebas unitarias, pero no supone verificada la medición de latencia ni el despliegue del equipo.

## 7. Finalizar

```powershell
docker compose -f compose.pc4.api.yaml down
```
