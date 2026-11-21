# PeruBudget PC4 — Etapa 3: persistencia MongoDB + caché Redis

## Estado del paquete

- Extiende **Etapa 2**, ya validada localmente por el equipo con **3,642,510 registros**, K=3, 2 nodos TCP e inercia **15,719,788.266972**.
- **No modifica** `internal/ml/massive/`, `cmd/mlnode/`, los datasets ni los reportes PC3.
- MongoDB es la **fuente de verdad** de los trabajos; Redis mantiene una copia temporal (TTL 60 segundos). Los JSON completos de entrenamiento se siguen guardando en `data/processed/pc4_api/`, con un volumen Docker.
- Se añadieron pruebas unitarias del contrato de persistencia con una implementación simulada. **MongoDB/Redis en Docker no se han podido probar en esta sesión**: deben validarse en el equipo del grupo.

## 1. Requisitos

Estar en tu rama actual de **PC4** con la Etapa 2 y Docker funcionando. Desde la raíz del repositorio, incorporar las rutas de este ZIP **sin crear una carpeta adicional**. Archivos importantes:

```text
cmd/api/main.go                         (actualizado)
cmd/api/openapi.yaml                    (actualizado)
internal/api/server.go                  (actualizado)
internal/api/server_test.go             (igual etapa 2)
internal/api/storage_test.go            (nuevo)
internal/storage/mongoredis.go          (nuevo)
deployments/docker/Dockerfile.pc4-api   (actualizado)
compose.pc4.storage.yaml                (nuevo, en la raíz)
scripts/pc4/install_storage_dependencies.ps1 (nuevo)
scripts/pc4/verify_storage.ps1          (nuevo)
```

## 2. Instalar dependencias Go **antes de Docker**

```powershell
powershell -ExecutionPolicy Bypass -File scripts/pc4/install_storage_dependencies.ps1
Test-Path go.sum

go test ./...
go test -race ./internal/api
go vet ./...
```

El script ejecuta `go get go.mongodb.org/mongo-driver/v2@v2.9.2 github.com/redis/go-redis/v9@v9.23.0`, y después `go mod tidy`. Esto modifica `go.mod` y crea/actualiza `go.sum`; conservar ambos bajo control de versiones. La **primera ejecución necesita Internet** para obtener las librerías y las imágenes Docker. Se utiliza Go 1.27.

## 3. Levantar la nueva composición (cinco servicios)

```powershell
# Detener ANTES los servicios de la etapa 2 para liberar localhost:8080.
docker compose -f compose.pc4.api.yaml down
New-Item -ItemType Directory -Path 'data/processed/pc4_api' -Force | Out-Null

docker compose -f compose.pc4.storage.yaml config
docker compose -f compose.pc4.storage.yaml up -d --build
docker compose -f compose.pc4.storage.yaml ps
```

Servicios esperados: **api**, **node-a**, **node-b**, **mongodb**, **redis**. Solo la API publica el puerto `127.0.0.1:8080`. Las bases no se exponen en Windows.

## 4. Verificar antes de entrenar

```powershell
Invoke-RestMethod http://localhost:8080/health
Invoke-RestMethod http://localhost:8080/api/v1/storage/health
Invoke-RestMethod http://localhost:8080/api/v1/cluster/nodes
powershell -ExecutionPolicy Bypass -File scripts/pc4/verify_storage.ps1
```

Esperado de `/api/v1/storage/health`: `mongodb: ok`, `redis: ok`. Si responde 503, revisar logs del servicio API, MongoDB y Redis.

## 5. Entrenar y demostrar la persistencia tras reiniciar API

```powershell
powershell -ExecutionPolicy Bypass -File scripts/pc4/verify_storage.ps1 -RunTraining -CheckRestart
```

Este script inicia **un entrenamiento nuevo**, espera `succeeded`, descarga el JSON, reinicia solamente la API y consulta el **mismo job ID**. Debe persistir después del reinicio con idéntica inercia y posibilidad de descargar el reporte.

*Nota:* Las ejecuciones que hiciste antes de integrar MongoDB estaban solo en memoria y no se migran automáticamente a la base de datos; los JSON anteriores permanecen intactos en disco.

## 6. Evidencias MongoDB y Redis

```powershell
# Cuenta total de documentos MongoDB para los trabajos nuevos
docker compose -f compose.pc4.storage.yaml exec -T mongodb mongosh --quiet --eval 'db.getSiblingDB("perubudget_pc4").training_jobs.countDocuments({})'

# Redis: cuántas claves están en caché
docker compose -f compose.pc4.storage.yaml exec -T redis redis-cli DBSIZE

# Logs para evidencia
docker compose -f compose.pc4.storage.yaml logs --tail=70 api mongodb redis
```

**Swagger UI:** http://localhost:8080/docs. **OpenAPI:** http://localhost:8080/openapi.yaml.

Evidencias a tomar: Docker Desktop mostrando cinco servicios; consola de endpoints `/health` y `/api/v1/storage/health`; `POST /api/v1/train` (202), GET `succeeded`, GET reporte; reinicio API seguido de GET exitoso con el mismo ID; MongoDB documento almacenado y Redis con clave. Nunca usar el tiempo de entrenamiento como latencia HTTP.

## 7. Precauciones

- **No ejecutar** `docker compose ... down -v`: ese `-v` borra los volúmenes persistentes de MongoDB y Redis.
- El nombre `mongodb://mongodb:27017` solo funciona desde la red interna de Docker. MongoDB y Redis no tienen credenciales en esta **demostración local**; no publicar su red ni la API a Internet.
- Si el programa se reinicia durante un entrenamiento, el trabajo persistente pasa a `failed` por interrupción; **no se reanuda** automáticamente.
- Redis es un caché con TTL de 60 segundos. La persistencia es de MongoDB, no de Redis.
- La API sigue admitiendo un solo entrenamiento activo por instancia; no es un scheduler distribuido general.
- Un `/health` correcto comprueba el proceso API; `/api/v1/storage/health` comprueba los servidores MongoDB/Redis. Las mediciones de latencia <100 ms deben hacerse con series de requests en Postman.

## 8. Para continuar

Al completar la prueba, enviar: salida de `docker compose ... ps`, salida de `verify_storage.ps1 -RunTraining -CheckRestart`, JSON de `estado_storage_*.json`, y capturas Swagger/MongoDB/Redis. Después haremos la validación final y la documentación PC4.
