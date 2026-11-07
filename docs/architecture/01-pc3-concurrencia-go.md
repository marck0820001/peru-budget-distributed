# PC3 — Diseño concurrente en Go (Partes A y B)

## Parte A — Cargador concurrente (`internal/ingestion`)

| Elemento | Decisión | Justificación |
|---|---|---|
| Lectura | 1 goroutine productor (`Split`) lee el archivo en bloques de 20 000 registros | El disco es secuencial; varios lectores sobre el mismo archivo compiten por I/O. Separar lectura y parseo solapa ambas etapas. |
| Integridad del bloque | `readRecord` respeta comillas: un campo con salto de línea nunca se parte | El CSV del MEF tiene campos entrecomillados con comas internas (`"PLANEAMIENTO, GESTION…"`). |
| Distribución | canal `chunks` con capacidad `2×workers` | **Backpressure**: el lector se bloquea si los workers van atrasados; la memoria queda acotada aunque el archivo pese 2.6 GB. |
| Procesamiento | N workers (pool) parsean, validan y agregan | Parseo de CSV + conversión exacta de 15 montos por fila es CPU-bound y paralelizable. |
| Estado | cada worker agrega en su **propio mapa** (fase map) | Sin candados en el bucle caliente: no hay contención ni condiciones de carrera. |
| Fusión | fan-in por canal `partials` + `Merge` (fase reduce) | Montos en céntimos enteros ⇒ suma asociativa y exacta: el resultado es idéntico al secuencial. |
| Estado compartido | detector de duplicados con 64 particiones y un `sync.Mutex` por partición; inserción por lote | *Lock striping*: dos workers rara vez bloquean la misma partición; un lock por partición y bloque en vez de uno por fila. |
| Incidencias | canal `incCh` hacia un único goroutine escritor | El archivo de incidencias nunca se escribe en paralelo. |
| Sincronización | `sync.WaitGroup` para cerrar `partials` cuando todos los workers terminan | Patrón estándar de fan-in seguro. |

Patrones: **pipeline**, **worker pool**, **fan-out/fan-in**, **map-reduce con agregación local**, **lock striping**.

## Parte B — K-Means paralelo (`internal/ml/kmeans`)

```
for iter := 1..MaxIter:
    snapshot := copia(centroides)              // solo lectura, compartida
    para cada worker s (en paralelo):          // fan-out por canal tasks
        Partial[s] = asignar(X[lo_s:hi_s], snapshot)   // sumas, conteos, inercia
    esperar a todos (barrera)                  // fan-in por canal reply
    centroides = Σ_s Partial[s].Sums / Σ_s Partial[s].Counts   // en orden de s
    si nadie cambió de cluster o desplazamiento < tol: parar
```

- **Particionamiento de datos** (*data parallelism*): cada worker es dueño de un rango contiguo de filas durante todo el entrenamiento (goroutine de larga vida).
- **Sin carreras**: los centroides se difunden como copia inmutable; las etiquetas se escriben en rangos disjuntos; los parciales viajan por canal. Verificado con `go test -race`.
- **Determinismo**: la reducción suma los parciales en orden de partición, y `k-means++` usa semilla fija; la versión paralela produce las mismas etiquetas que la secuencial (`TestParallelEqualsSequential`).
- **Clusters vacíos**: se reubican en el punto más lejano reportado por los workers.
- **Preparado para PC4**: `Coordinate` trabaja con la interfaz `ShardWorker`; `Partial` tiene etiquetas JSON y será el mensaje TCP entre el coordinador y los nodos.

## Selección de K y atípicos

- K se evalúa entre 2 y 10 con inercia (codo), **silueta** (paralela, O(n²)) y Davies-Bouldin; se elige la silueta máxima.
- Atípico: distancia al centroide > Q3 + 1.5·IQR de las distancias **de su propio cluster** (Tukey), o pertenencia a un micro-cluster (<4 perfiles).
