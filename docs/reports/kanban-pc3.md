# Tablero Kanban — tarjetas del Entregable 1 (PC3)

Crear en GitHub → Projects → *Board* con columnas **Backlog · To do · In progress · Review · Done**.
Cada tarjeta enlaza su rama `feature/*` y su Pull Request hacia `develop`.

| # | Tarjeta | Etiquetas | Rama | Estado PC3 |
|---|---|---|---|---|
| 1 | Definir caso, pregunta de impacto social y alcance | docs | — | Done |
| 2 | Auditoría de volumen de los 4 CSV del MEF | data, python | feature/eda-preprocessing | Done |
| 3 | EDA estadístico (calidad de montos, cobertura, mes de corte) | data, python | feature/eda-preprocessing | Done |
| 4 | Reglas de preprocesamiento auditables + validador | data, python | feature/eda-preprocessing | Done |
| 5 | Feature engineering municipal (6 indicadores, winsor, robust scaling) | data, python | feature/eda-preprocessing | Done |
| 6 | Cargador concurrente en Go (pipeline, worker pool, fan-in) | go, concurrency | feature/go-concurrent-etl-kmeans | Done |
| 7 | Limpieza en Go: céntimos exactos, conciliación mensual, incidencias, duplicados | go | feature/go-concurrent-etl-kmeans | Done |
| 8 | Features y matriz K-Means en Go (compatibles con Python) | go, ml | feature/go-concurrent-etl-kmeans | Done |
| 9 | K-Means paralelo MapReduce + k-means++ + silueta/DB | go, ml, concurrency | feature/go-concurrent-etl-kmeans | Done |
| 10 | Detección de perfiles atípicos | go, ml | feature/go-concurrent-etl-kmeans | Done |
| 11 | Pruebas unitarias, `-race` y benchmarks 1/2/4/8 workers | go, test | feature/go-concurrent-etl-kmeans | Done |
| 12 | Ejecutar ETL + trainer con los CSV reales y actualizar cifras del informe | data, docs | — | To do |
| 13 | Informe PC3 + reporte de participación | docs | — | Review |
| 14 | Nodos ML por TCP (ShardWorker remoto) | go, distributed | feature/tcp-cluster | Backlog (PC4) |
| 15 | API coordinadora REST/WebSocket + Swagger | go, api | feature/api | Backlog (PC4) |
| 16 | MongoDB (resultados) + Redis (caché) | db | feature/storage | Backlog (PC4) |
| 17 | SPA React: dashboard, resultados y panel admin | frontend | feature/frontend | Backlog (TB2) |
| 18 | Docker Compose de toda la solución | devops | feature/docker-compose | Backlog (TB2) |
