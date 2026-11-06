# PC3 — Reglas auditables de preprocesamiento (MEF)

**Caso 6:** análisis de ejecución presupuestal municipal. **Fuente principal:** `Gasto Devengado` 2024 y 2025. **Complemento por estudiar:** `Seguimiento PI` (snapshots históricos; no sumarlos ni unirlos sin validar claves y significado temporal).

## Unidad de análisis y resultados

- **Fuente original:** línea presupuestaria, no obra o municipalidad única.
- **Líneas depuradas:** `budget_lines_clean.csv.gz` (opcional, detalle municipal por línea con fuente y número de fila).
- **Perfil municipal:** `municipality_year_features.csv` (una ejecutora y año). Es un **candidato** al clustering municipal, no una matriz lista para entrenar.
- **Perfil de proyecto:** `project_features.csv` (año, ejecutora y código de proyecto). Se agregan exclusivamente líneas `TIPO_ACT_PROY=PROYECTO` de Gasto Devengado. No equivale necesariamente a una obra físicamente única.

## Transformaciones permitidas

1. Retener `NIVEL_GOBIERNO=M`. Documentar el volumen descartado de R/N.
2. Preservar los códigos como texto (`SEC_EJEC`, `PRODUCTO_PROYECTO`). Nunca tratarlos como features numéricas continuas.
3. Convertir montos de texto a céntimos enteros **sin redondear**. Los ceros y negativos válidos permanecen.
4. Comprobar que la suma de los doce meses es igual al devengado anual por línea; las filas que no concilien o tengan montos inválidos van al registro de incidencias y **no** se suman a los agregados.
5. Conservar la procedencia (archivo y número de fila) en la salida opcional de líneas.
6. Agregar por año + ejecutora (perfil municipal). Agregar por año + ejecutora + proyecto SOLO cuando la línea se haya clasificado `PROYECTO` y el código exista.
7. No imputar, escalar, winsorizar ni eliminar outliers en esta fase; producir indicadores candidatos con denominadores no positivos como valores vacíos.
8. El validador independiente reconcilia conteos y montos de todas las salidas; puede contrastar los conteos contra `inventario_eda.csv`.

## Aspectos pendientes antes de K-Means

- Verificar **duplicados exactos** con una estrategia adecuada para millones de filas; el módulo no los elimina automáticamente.
- Investigar filas rechazadas, si las hubiera, y no considerar agregaciones parciales como cierre financiero definitivo.
- Verificar el alcance de mancomunidades y otras ejecutoras del nivel `M`.
- Comprobar la relación entre `Gasto Devengado` y `Seguimiento PI` con el significado de `ANO_EJE` en este último.
- Verificar si 2025 representa el cierre definitivo del ejercicio o un snapshot actualizado.
- Resolver comparabilidad de variables entre 2024, 2025 y cualquier incorporación de 2026.
- Seleccionar y escalar features solo después de examinar su distribución; usar benchmarks en Go sobre los datos procesados.

## Requisito del curso

La inspección y preparación auxiliar en Python **no sustituye** la carga concurrente ni el modelo K-Means paralelo que deben implementar en Go para la PC3. El procesamiento masivo observado antes de filtrar no equivale automáticamente al número de observaciones del modelo.
