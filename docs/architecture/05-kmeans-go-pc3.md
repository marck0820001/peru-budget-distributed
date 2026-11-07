# PC3 — Diseño del algoritmo de K-Means en Go

## Unidad de análisis

La matriz `kmeans_matrix.csv` contiene 3,783 perfiles ejecutora-año y seis indicadores presupuestarios escalados. No representa los 3,642,510 registros presupuestarios originales.

## Algoritmo

1. K-Means++ inicializa K centroides reproducibles con semilla fija.
2. Cada worker recibe un rango disjunto de observaciones (Data Parallelism).
3. Asigna cada vector a su centroide más cercano mediante distancia euclidiana al cuadrado.
4. Cada worker calcula sumas y conteos locales por clúster y los transmite por un canal.
5. El coordinador reduce resultados por orden de worker para minimizar diferencias numéricas y actualiza centroides.
6. Se detiene por convergencia del desplazamiento de centroides o máximo de iteraciones.
7. Se reasignan los registros a los centroides **finales** y se calcula la inercia correspondiente.

Ningún worker modifica centroides compartidos. La sincronización es al final de cada iteración.

## Validación

- `go test ./internal/...` comprueba datos invalidos y concordancia entre 1, 2, 4, 8 workers en un conjunto sintético.
- Ejecutar con la misma K/semilla/tolerancia para comparar el tiempo de entrenamiento sin incluir carga del CSV.
- Medir mediana de al menos 3 repeticiones para reducir ruido; calcular speedup y eficiencia.
- `cmd/etl` realiza **otra prueba separada** de carga/procesamiento concurrente en Go de más de 1M de filas de Gasto Devengado.
- La salida del ETL Go debe conciliar sus conteos/montos con el preprocesamiento Python, no sustituirlo a priori.

## Limitaciones

- Una agrupación atípica no constituye prueba de corrupción.
- `SampleSilhouette` es una estimación basada en muestra, no silueta exacta.
- Las operaciones en coma flotante no son perfectamente asociativas; tolerancias pequeñas son esperables.
- Las observaciones de 2024 y 2025 contienen ejecutoras repetidas; al aplicar a 2026 no reentrenar escalador con datos futuros.
- No se demuestra aprendizaje masivo sobre 3.64M por entrenar únicamente sobre 3,783 perfiles. La evaluación de un K-Means masivo sobre partidas queda como experimento distinto a diseñar según granulidad y variables válidas.
