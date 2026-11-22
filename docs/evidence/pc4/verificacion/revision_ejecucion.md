# PC4 – Revisión de hechos y evidencias

Fecha de ejecución: 2026-11-22 (hora local, Windows 11, PowerShell 5.1).
Directorio: `peru-budget-distributed` (raíz del repo).
No se modificó código, no se hizo commit ni push.

> **Aviso sobre la rama:** se pidió trabajar en `develop`, pero el repo estaba en `feature/pc4-cluster-tcp` y **no se cambió de rama**.
> `develop` va **1 commit por detrás** de esta rama (`git rev-list --left-right --count develop...HEAD` → `0 1`); el commit que falta es justo el del PC4 (`a950a71`). En `develop` no existe el código del PC4, así que todo lo que sigue se ejecutó en `feature/pc4-cluster-tcp`.

---

## 1. Estado del repo

### `git status`
```
On branch feature/pc4-cluster-tcp
Your branch is up to date with 'origin/feature/pc4-cluster-tcp'.

nothing to commit, working tree clean
```

### `git branch -a`
```
  develop
  feature/eda-preprocessing
  feature/parallel-kmeans
* feature/pc4-cluster-tcp
  feature/pc4-distributed-cluster
  main
  remotes/origin/develop
  remotes/origin/feature/eda-preprocessing
  remotes/origin/feature/parallel-kmeans
  remotes/origin/feature/pc4-cluster-tcp
```

### `git log --oneline -15` (solo hay 13 commits)
```
a950a71 feat(pc4): implement distributed TCP cluster, REST API, MongoDB and Redis
f292ae2 Merge pull request #4 from marck0820001/feature/parallel-kmeans
fdc582b feat: validation
7ec1655 Merge pull request #3 from marck0820001/feature/parallel-kmeans
45aa687 feat(pc3): finalize concurrent massive K-Means validation
9479e1a Merge pull request #2 from marck0820001/feature/parallel-kmeans
b837b01 feat: concurrent ML
d346404 Merge pull request #1 from marck0820001/feature/eda-preprocessing
6b3edf9 feat(eda): add feature engineering
40c7a33 feat(eda): add preprocesing file
c6645fc feat(eda): add inspeccion, statistical analysis and data quality profiling
d586753 chore: initialize project structure and gitignore
6f014bf chore: initial project setup
```

Fechas (de `git log --date=short`): commits del 2026-11-05 al 2026-11-07, y el commit del PC4 (`a950a71`) el **2026-11-21**.

### `git shortlog -sn --all`
```
     9	Marco
     4	Marco Antonio F.R.O.
```
("Marco Antonio F.R.O." aparece solo en los 4 merges de PR en GitHub. Los dos nombres parecen ser la misma persona.)

### `git log --since=2026-11-14 --format="%an %s"`
```
Marco feat(pc4): implement distributed TCP cluster, REST API, MongoDB and Redis
```
→ En el periodo del PC4 hay **un solo commit, de un solo autor**. El git user configurado en esta máquina (`DavidA`) no tiene ningún commit.

---

## 2. Entorno

### `go version`
```
go version go1.27.1 windows/amd64
```

### `docker version`
Primer intento (Docker Desktop estaba apagado):
```
Client:
 Version:           28.1.1
 API version:       1.49
 Go version:        go1.23.8
 Git commit:        4eba377
 Built:             Fri Apr 18 09:53:24 2025
 OS/Arch:           windows/amd64
 Context:           desktop-linux
error during connect: Get "http://%2F%2F.%2Fpipe%2FdockerDesktopLinuxEngine/v1.49/version": open //./pipe/dockerDesktopLinuxEngine: The system cannot find the file specified.
```
Se arrancó Docker Desktop (estuvo listo en unos 10 s) y se repitió:
```
Server: Docker Desktop 4.41.2 (191736)
 Engine:
  Version:          28.1.1
  API version:      1.49 (minimum version 1.24)
  Go version:       go1.23.8
  Git commit:       01f442b
  OS/Arch:          linux/amd64
 containerd:
  Version:          1.7.27
 runc:
  Version:          1.2.5
 docker-init:
  Version:          0.19.0
```

### `docker compose version`
```
Docker Compose version v2.35.1-desktop.1
```

---

## 3. Compilación y pruebas

### `go build ./...` → exit 0
Solo descargó dependencias (PowerShell muestra la salida de stderr de `go` como `NativeCommandError`, pero no es un error):
```
go: downloading go.mongodb.org/mongo-driver/v2 v2.9.2
go: downloading github.com/redis/go-redis/v9 v9.23.0
go: downloading go.uber.org/atomic v1.12.0
go: downloading github.com/cespare/xxhash/v2 v2.3.0
go: downloading golang.org/x/sys v0.48.0
go: downloading github.com/youmark/pkcs8 v0.0.0-20240726163527-a2c0da244d78
go: downloading github.com/xdg-go/scram v1.2.0
go: downloading github.com/xdg-go/stringprep v1.0.4
go: downloading github.com/klauspost/compress v1.19.2
go: downloading golang.org/x/crypto v0.53.0
go: downloading golang.org/x/text v0.39.0
```

### `go vet ./...` → exit 0, sin salida.

### `go test ./...` → exit 0
```
?   	github.com/marck0820001/peru-budget-distributed.git/cmd/api	[no test files]
?   	github.com/marck0820001/peru-budget-distributed.git/cmd/coordinator	[no test files]
?   	github.com/marck0820001/peru-budget-distributed.git/cmd/etl	[no test files]
?   	github.com/marck0820001/peru-budget-distributed.git/cmd/massivekmeans	[no test files]
?   	github.com/marck0820001/peru-budget-distributed.git/cmd/massiveprofile	[no test files]
?   	github.com/marck0820001/peru-budget-distributed.git/cmd/mlnode	[no test files]
?   	github.com/marck0820001/peru-budget-distributed.git/cmd/trainer	[no test files]
ok  	github.com/marck0820001/peru-budget-distributed.git/internal/api	0.622s
ok  	github.com/marck0820001/peru-budget-distributed.git/internal/ingestion	0.345s
ok  	github.com/marck0820001/peru-budget-distributed.git/internal/ml/kmeans	0.338s
ok  	github.com/marck0820001/peru-budget-distributed.git/internal/ml/massive	0.630s
?   	github.com/marck0820001/peru-budget-distributed.git/internal/storage	[no test files]
```

---

## 4. Datos

### `Get-ChildItem data/processed/massive_mef -Recurse | Select Name,Length`
```
Name                                          Length
----                                          ------
benchmarks_massive.csv                           832
benchmarks_resumen.csv                           398
benchmarks_resumen.md                            451
budget_lines.f64                           262260720
budget_lines_metadata.json                      1341
profile_k3_seed42.json                          3052
training_distributed_k3_nodes2_seed42.json      2778
training_k3_w1_seed42.json                      2823
training_k3_w2_seed42.json                      2819
training_k3_w4_seed42.json                      2822
training_k3_w8_seed42.json                      2826
validacion_final.json                           2534
validacion_final.md                             1618
```

- `budget_lines.f64`: **EXISTE**, 262 260 720 bytes (~250 MiB).
- `budget_lines_metadata.json`: **EXISTE**, 1 341 bytes.
- `data/processed/*` está en `.gitignore` (`.gitignore:15`), así que estos datos no se versionan: cada integrante tiene que generarlos en su máquina.

---

## 5. Clúster TCP (`compose.pc4.cluster.yaml`)

`docker compose -f compose.pc4.cluster.yaml up --build --abort-on-container-exit --exit-code-from coordinator` → **exit 0**.

### Logs del coordinador (el servicio solo escribió estas 4 líneas)
```
coordinator-1  | PC4: K-Means TCP | filas=3642510 | K=3 | nodos=[node-a:9101 node-b:9101]
coordinator-1  | PC4 OK: filas=3642510 | K=3 | nodos=2 | iteraciones=8 | convergió=true | inercia=15719788.266972363 | tiempos=16981 ms
coordinator-1  | Clusters=[1502969 1037720 1101821]
coordinator-1  | Reporte=/dataset/training_distributed_k3_nodes2_seed42.json
```

### `docker compose -f compose.pc4.cluster.yaml ps -a`
```
NAME                                    IMAGE                          COMMAND                  SERVICE       CREATED          STATUS                                PORTS
peru-budget-distributed-coordinator-1   perubudget/pc4-cluster:local   "/app/coordinator -m…"   coordinator   19 seconds ago   Exited (0) Less than a second ago
peru-budget-distributed-node-a-1        perubudget/pc4-cluster:local   "/app/mlnode -listen…"   node-a        21 seconds ago   Exited (143) Less than a second ago
peru-budget-distributed-node-b-1        perubudget/pc4-cluster:local   "/app/mlnode -listen…"   node-b        21 seconds ago   Exited (143) Less than a second ago
```
(Los nodos salen con 143 = SIGTERM, porque `--abort-on-container-exit` los detiene cuando termina el coordinador. Es lo esperado.)

### `docker compose -f compose.pc4.cluster.yaml down` (sin -v)
```
 Container peru-budget-distributed-coordinator-1  Stopping / Stopped / Removing / Removed
 Container peru-budget-distributed-node-a-1  Stopping / Stopped / Removing / Removed
 Container peru-budget-distributed-node-b-1  Stopping / Stopped / Removing / Removed
 Network peru-budget-distributed_ml-internal  Removing / Removed
```

Nota: el coordinador **reescribe** `data/processed/massive_mef/training_distributed_k3_nodes2_seed42.json` (montado en `/dataset`). Ese archivo está en .gitignore, así que no aparece en `git status`.

---

## 6. Stack completo (`compose.pc4.storage.yaml`)

Antes de levantarlo: `docker ps` estaba vacío y `netstat -ano | findstr :8080` no mostró nada → **ningún otro compose ocupaba el puerto 8080**. No hubo que detener nada.

`docker compose -f compose.pc4.storage.yaml up -d --build` → exit 0 (últimas líneas):
```
 Volume "peru-budget-distributed_pc4-mongo-data"  Created
 Container peru-budget-distributed-redis-1  Healthy
 Container peru-budget-distributed-mongodb-1  Healthy
 Container peru-budget-distributed-api-1  Starting
 Container peru-budget-distributed-api-1  Started
```

### `docker compose -f compose.pc4.storage.yaml ps`
```
NAME                                IMAGE                          COMMAND                  SERVICE   CREATED         STATUS                   PORTS
peru-budget-distributed-api-1       perubudget/pc4-storage:local   "/app/api -listen :8…"   api       2 minutes ago   Up 2 minutes             127.0.0.1:8080->8080/tcp
peru-budget-distributed-mongodb-1   mongo:8.0                      "docker-entrypoint.s…"   mongodb   2 minutes ago   Up 2 minutes (healthy)   27017/tcp
peru-budget-distributed-node-a-1    perubudget/pc4-storage:local   "/app/mlnode -listen…"   node-a    2 minutes ago   Up 2 minutes
peru-budget-distributed-node-b-1    perubudget/pc4-storage:local   "/app/mlnode -listen…"   node-b    2 minutes ago   Up 2 minutes
peru-budget-distributed-redis-1     redis:7.4-alpine               "docker-entrypoint.s…"   redis     2 minutes ago   Up 2 minutes (healthy)   6379/tcp
```
**La API nunca aparece como "healthy" porque el servicio `api` no tiene `healthcheck`** en `compose.pc4.storage.yaml` (solo lo tienen mongodb y redis). Se esperaron unos 120 s. Su funcionamiento se comprobó por HTTP (sección 7): responde bien. Los nodos tampoco tienen healthcheck.

---

## 7. Endpoints

### `Invoke-RestMethod http://127.0.0.1:8080/health`
```json
{
    "dataset_rows":  3642510,
    "features":  [
                     "signed_log_pia",
                     "signed_log_pim",
                     "signed_log_devengado",
                     "tasa_ejecucion_acotada",
                     "participacion_q4_acotada",
                     "meses_activos_fraccion",
                     "es_proyecto",
                     "pim_cero",
                     "devengado_cero"
                 ],
    "node_count":  2,
    "service":  "perubudget-pc4-api",
    "status":  "ok"
}
```

### `Invoke-RestMethod http://127.0.0.1:8080/api/v1/storage/health`
```json
{
    "mongodb":  "ok",
    "redis":  "ok"
}
```

### `Invoke-RestMethod http://127.0.0.1:8080/api/v1/cluster/nodes`
```json
{
    "nodes":  [
                  { "address":  "node-a:9101", "reachable":  true },
                  { "address":  "node-b:9101", "reachable":  true }
              ],
    "note":  "Reachable indica conexión TCP posible, no garantiza la ejecución del entrenamiento"
}
```

---

## 8. Entrenamiento y persistencia

`powershell -ExecutionPolicy Bypass -File scripts/pc4/verify_storage.ps1 -RunTraining -CheckRestart` → **exit 0**
```
=== Persistencia MongoDB + Redis ===
{
    "mongodb":  "ok",
    "redis":  "ok"
}
Nodos TCP OK
Job persistido: aa49266e2357533887629f78
Job=aa49266e2357533887629f78 Status=running
Job=aa49266e2357533887629f78 Status=running
Job=aa49266e2357533887629f78 Status=running
Job=aa49266e2357533887629f78 Status=running
Job=aa49266e2357533887629f78 Status=succeeded
Informe guardado; inercia=15719788.266972363; iteraciones=8
=== Reiniciando SOLO la API; preservando volÃºmenes y nodos ===
 Container peru-budget-distributed-api-1  Restarting
 Container peru-budget-distributed-api-1  Started
PASS: MongoDB conserva job e inercia despues de reiniciar la API.
Job ID: aa49266e2357533887629f78
OK: comprobar tambien docker compose logs api mongodb redis.
```
- La inercia (15719788.266972363) y las iteraciones (8) **coinciden exactamente** con la ejecución del clúster TCP de la sección 5.
- "volÃºmenes" sale con mojibake: el script tiene UTF-8 sin BOM y PowerShell 5.1 lo lee como ANSI.

---

## 9. Base de datos

### Comandos tal cual se pidieron (desde PowerShell 5.1) → **FALLARON**
`... mongosh --quiet --eval 'db.getSiblingDB("perubudget_pc4").training_jobs.countDocuments({})'`
```
ReferenceError: perubudget_pc4 is not defined
```
`... mongosh --quiet --eval 'printjson(db.getSiblingDB("perubudget_pc4").training_jobs.findOne({}, {payload:0}))'`
```
ReferenceError: perubudget_pc4 is not defined
```
Causa: PowerShell 5.1 quita las comillas dobles internas al pasar argumentos a un ejecutable nativo, así que mongosh recibe `getSiblingDB(perubudget_pc4)`. No es un fallo de la base de datos.

### Mismas consultas con comillas simples en el JS (alternativa) → OK
`mongosh --quiet --eval "db.getSiblingDB('perubudget_pc4').training_jobs.countDocuments({})"`
```
1
```
`mongosh --quiet --eval "printjson(db.getSiblingDB('perubudget_pc4').training_jobs.findOne({}, {payload:0}))"`
```
{
  _id: 'aa49266e2357533887629f78',
  started_at: ISODate('2026-11-22T03:57:48.215Z'),
  status: 'succeeded'
}
```

### `redis-cli DBSIZE`
```
1
```

### `redis-cli --scan --pattern "perubudget:pc4:job:*"`
```
perubudget:pc4:job:aa49266e2357533887629f78
```

---

## 10. Latencia (`scripts/pc4/benchmark_http.ps1`)

### Ejecución 1: comando tal cual se pidió → job/result fallaron
El script tiene **el JobId hardcodeado** (`scripts/pc4/benchmark_http.ps1:21` → `'24723f15a506976bbbcb2ceb'`). Ese job no existe en esta base de datos (el volumen Mongo se creó nuevo), así que `job` y `result` devuelven HTTP 404 en las 50 iteraciones:
```
ADVERTENCIA: Solicitud fallida: job, iteracion=1, HTTP=404
ADVERTENCIA: Solicitud fallida: result, iteracion=1, HTTP=404
... (igual hasta iteracion=50)

=== Resumen ===
Endpoint Requests HTTP200 Errors Under100 CompliancePct MedianMs  P95Ms  MaxMs
-------- -------- ------- ------ -------- ------------- --------  -----  -----
health         50      50      0       50           100   16.473 31.231 46.254
storage        50      50      0       50           100   17.436  32.22 41.559
nodes          50      50      0       50           100   17.655 28.129 43.043
job            50       0     50        0             0
result         50       0     50        0             0
```
Esta ejecución **sobrescribió** los tres archivos versionados `docs/evidence/pc4/latencias_http_{detalle.csv,resumen.csv,resumen.json}` con los resultados con error. Para no dejar evidencia mala en el repo, se guardó una copia en el scratchpad y **se restauraron esos 3 archivos con `git checkout --`** (vuelven a estar igual que en HEAD; `git status` queda limpio salvo este archivo).

### Ejecución 2: con el job real, salida al scratchpad (no toca el repo)
`benchmark_http.ps1 -JobId aa49266e2357533887629f78 -OutputDirectory <scratchpad>` → exit 0, 0 advertencias:
```
Endpoint Requests HTTP200 Errors Under100 CompliancePct MedianMs  P95Ms  MaxMs
-------- -------- ------- ------ -------- ------------- --------  -----  -----
health         50      50      0       50           100    17.16 29.173 38.038
storage        50      50      0       50           100   17.888 34.086 42.039
nodes          50      50      0       50           100    22.86 42.355 48.777
job            50      50      0       50           100   20.814 41.769 46.744
result         50      50      0       50           100    20.01 48.926  51.14
```
Resumen: **100 % de las solicitudes por debajo de 100 ms en los 5 endpoints**; la mediana está entre 17 y 23 ms, el P95 en ≤ 49 ms y el máximo en ≤ 52 ms. (Latencia medida de extremo a extremo desde PowerShell. Los logs de la API dicen que el servidor procesa cada petición en < 3 ms.)

---

## 11. Postman (`postman/PeruBudget_PC4_API.postman_collection.json`)

Colección: **"PeruBudget PC4 - API distribuida TCP"**. **No tiene carpetas** (los 7 requests están en la raíz) ni scripts a nivel de colección.

| # | Método | Request | URL | ¿pm.test? |
|---|---|---|---|---|
| 01 | GET | Health (<100ms) | `{{base_url}}/health` | Sí (2) |
| 02 | GET | Nodos TCP | `{{base_url}}/api/v1/cluster/nodes` | Sí (2) |
| 03 | POST | Iniciar entrenamiento (guarda job_id) | `{{base_url}}/api/v1/train` | Sí (2) |
| 04 | GET | Consultar job (repetir hasta succeeded) | `{{base_url}}/api/v1/jobs/{{job_id}}` | Sí (2) |
| 05 | GET | Obtener resultado (solo si succeeded) | `{{base_url}}/api/v1/jobs/{{job_id}}/result` | Sí (2) |
| 06 | GET | OpenAPI YAML | `{{base_url}}/openapi.yaml` | Sí (1) |
| 07 | GET | Swagger UI | `{{base_url}}/docs` | Sí (1) |

Los 7 requests tienen `pm.test`. **No hay ningún request para `/api/v1/storage/health`** (el endpoint de MongoDB/Redis). La colección **no se ejecutó** en Postman/Newman: NO EJECUTADO, porque no se pidió y Newman no está entre las herramientas verificadas.

---

## 12. Frontend

1. `frontend/` solo contiene carpetas vacías con `.gitkeep`: `public/`, `src/components`, `src/hooks`, `src/pages`, `src/services`, `src/types`.
2. No hay `package.json`, ni código fuente, ni README.
3. La estructura se creó en el commit inicial `d586753` ("chore: initialize project structure and gitignore") y no se ha tocado desde entonces.
4. Solo `.gitignore` (sección "FRONTEND - REACT / VITE") y `.dockerignore.pc3-template` lo mencionan; ningún compose ni script del PC4 lo usa.
5. Conclusión: es un esqueleto vacío pensado para React/Vite. **No forma parte del PC4** (el PC4 es backend: clúster TCP + API REST + MongoDB/Redis). Parece reservado para una entrega posterior o para otro curso. No hay nada implementado.

---

## PROBLEMAS

1. **Rama:** se pidió `develop`, pero el repo estaba en `feature/pc4-cluster-tcp` y no se cambió. `develop` no contiene el commit del PC4 (`a950a71`); está 1 commit por detrás. Ese commit tampoco está en `main`. Falta un PR/merge.
2. **Autoría:** todo el PC4 es **un solo commit de un solo autor ("Marco")**, del 2026-11-21. No hay commits de otros integrantes; el git user de esta máquina (`DavidA`) no aparece en el historial.
3. **Docker Desktop estaba apagado:** el primer `docker version` falló (`open //./pipe/dockerDesktopLinuxEngine: The system cannot find the file specified.`). Se arrancó Docker Desktop y todo siguió con normalidad.
4. **La API no tiene healthcheck** en `compose.pc4.storage.yaml`, así que `docker compose ps` nunca la marca "healthy" (los nodos tampoco tienen). Funciona bien por HTTP.
5. **Comandos mongosh del punto 9 fallan en PowerShell 5.1** con `ReferenceError: perubudget_pc4 is not defined` por cómo se pasan las comillas. Con comillas simples dentro del JS funcionan (count = 1). Si estos comandos van en un README o informe, hay que corregir las comillas para Windows.
6. **`benchmark_http.ps1` tiene el JobId hardcodeado** (`24723f15a506976bbbcb2ceb`, línea 21). En cualquier entorno nuevo, `job` y `result` dan 404 (100 % de errores) y el script **sobrescribe la evidencia versionada** en `docs/evidence/pc4/` aunque falle (sale con exit 0 igual). Se restauraron esos archivos con `git checkout --`. La medición válida se hizo pasando `-JobId` (sección 10, ejecución 2).
7. **Mojibake** en la salida de `verify_storage.ps1` ("volÃºmenes"): el script es UTF-8 sin BOM y PowerShell 5.1 lo lee como ANSI.
8. **El documento en Mongo sin `payload` solo tiene `_id`, `started_at` y `status`**: no hay `finished_at` ni la inercia a nivel raíz (seguramente están dentro de `payload`, que se excluyó). Es una observación, no un error.
9. **La colección Postman no tiene carpetas** ni un request para `/api/v1/storage/health`, y **no se ejecutó** en Postman/Newman (NO EJECUTADO).
10. **Sin tests** en `cmd/*` ni en `internal/storage` (`[no test files]`). La capa de MongoDB/Redis no tiene pruebas unitarias.
11. El coordinador del clúster reescribe `data/processed/massive_mef/training_distributed_k3_nodes2_seed42.json` en cada ejecución (está ignorado por git, así que es invisible en `git status`).
12. PowerShell 5.1 muestra la salida de stderr de `go`/`docker` como `NativeCommandError` aunque el exit code sea 0. Es ruido, no son errores reales.

**Estado final:** el stack `compose.pc4.storage.yaml` queda **levantado** (api, mongodb, redis, node-a, node-b), con 1 job `succeeded` persistido (`aa49266e2357533887629f78`). No se ejecutó `down`.
