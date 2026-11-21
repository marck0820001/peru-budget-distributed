# PeruBudget Distributed — PC4 / Etapa 1: clúster K-Means TCP

## 0. Alcance

**Nuevo:** `cmd/coordinator`, `cmd/mlnode`, `internal/ml/massive/distributed.go`, 2 nodos TCP y Docker Compose. **No sustituye ni modifica** el K-Means municipal (`cmd/trainer`) ni el K-Means masivo PC3 (`cmd/massivekmeans`).

Los dos nodos son **procesos independientes** que leen un intervalo disjunto del binario original y envían `counts`, `sums` e `inertia` al coordinador sobre sockets TCP. El coordinador calcula los centroides actualizados e itera hasta converger. Se usa la misma muestra inicial K-Means++ de PC3 (`seed=42`, `init-sample=10000`). Se realiza un escaneo final para medir inercia y tamaños usando los centroides definitivos.

## 1. Preparación (Windows, PowerShell)

Desde la **raíz del repositorio** y en una rama de funcionalidad PC4:

```powershell
git switch develop
git pull --ff-only origin develop
git switch -c feature/pc4-cluster-tcp

Test-Path 'data/processed/massive_mef/budget_lines.f64'
Test-Path 'data/processed/massive_mef/budget_lines_metadata.json'
```

Los dos `Test-Path` deben dar `True`. Si no existen, primero repetir la preparación de PC3 con:

```powershell
go run ./cmd/massivekmeans -mode prepare -expect-rows 3642510 -out data/processed/massive_mef
```

El binario completo contiene 3,642,510 filas × 9 variables; no incluye Seguimiento-PI.

## 2. Copiar archivos nuevos

Extraer el ZIP de esta etapa **en la raíz del repositorio**, respetando las rutas. No sobrescribir `go.mod`, `cmd/massivekmeans`, `internal/ml/massive/train.go` ni archivos de resultados PC3.

```powershell
go test ./...
docker compose -f compose.pc4.cluster.yaml config
```

## 3. Ejecutar el clúster real con Docker

```powershell
docker compose -f compose.pc4.cluster.yaml up --build --abort-on-container-exit --exit-code-from coordinator
```

Cuando finalice:

```powershell
docker compose -f compose.pc4.cluster.yaml logs node-a node-b coordinator
```

El coordinador genera:

```text
data/processed/massive_mef/training_distributed_k3_nodes2_seed42.json
```

**Capturas para PC4:** (i) terminal del coordinador con `filas`, `K`, `nodos`, `iteraciones`, `convergió` e `inercia`; (ii) logs de `node-a` y `node-b` mostrando intervalos disjuntos e iteraciones; (iii) `docker compose -f compose.pc4.cluster.yaml ps -a`; (iv) JSON de salida.

Apagar los servicios:

```powershell
docker compose -f compose.pc4.cluster.yaml down
```

## 4. Validación comparativa con la PC3

Los informes JSON deben corresponder a las mismas 3,642,510 líneas, las mismas 9 variables, `K=3`, `seed=42`, `init-sample=10000`, `clip-z=5`, `tol=1e-4`, `max-iter=25`.

Referencia PC3: tamaños aproximados `[1502969, 1037720, 1101821]`, 8 iteraciones, inercia 15,719,788.267. El orden de sumas flotantes puede generar **diferencias pequeñas**, y los IDs de clúster no deben interpretarse semánticamente sin el perfilado. No reportar equivalencia antes de contrastar los archivos.

```powershell
$pc3 = Get-Content 'data/processed/massive_mef/training_k3_w4_seed42.json' -Raw | ConvertFrom-Json
$pc4 = Get-Content 'data/processed/massive_mef/training_distributed_k3_nodes2_seed42.json' -Raw | ConvertFrom-Json
[PSCustomObject]@{
    FilasPC3 = $pc3.rows
    FilasPC4 = $pc4.rows
    IteracionesPC3 = $pc3.iterations
    IteracionesPC4 = $pc4.iterations
    InerciaPC3 = $pc3.inertia
    InerciaPC4 = $pc4.inertia
    DiferenciaInerciaRelativa = [math]::Abs($pc3.inertia - $pc4.inertia) / $pc3.inertia
    ClustersPC3 = ($pc3.cluster_sizes -join ',')
    ClustersPC4 = ($pc4.cluster_sizes -join ',')
}
```

## 5. Prueba sin Docker (diagnóstico)

En dos terminales:

```powershell
# Nodo A
 go run ./cmd/mlnode -listen :9101 -id node-a
# Nodo B
 go run ./cmd/mlnode -listen :9102 -id node-b
```

En una tercera:

```powershell
go run ./cmd/coordinator -nodes 127.0.0.1:9101,127.0.0.1:9102
```

## 6. Próxima etapa

Este paquete solo implementa **el motor distribuido**. Aún faltan API REST/Swagger, pruebas de latencia, MongoDB, Redis y su integración. No presentar esta etapa como PC4 completa.
