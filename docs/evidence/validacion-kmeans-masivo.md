# PC3 — Evidencia automatizada del entrenamiento K-Means masivo

**Estado: PASS** — Validación de reportes (no sustituto de los tests Go).

- Filas municipales: **3,642,510**; líneas de proyectos: **578,956**.
- K=3; características=9; iteraciones=8.
- Tamaños: **[1502969, 1037720, 1101821]**.
- Inercia: entrenamiento=15719788.266976278; recalculada=15719788.266963078.
- Diferencia relativa de inercia: **8.397e-13**.
- Máxima diferencia de centroides entre workers: **3.018e-11**.

## Perfilado de clústeres (proporciones de líneas, no municipalidades)

| Clúster | Líneas | % del total | % proyectos | % PIM=0 | % Devengado=0 |
|---:|---:|---:|---:|---:|---:|
| 0 | 1,502,969 | 41.26% | 17.23% | 95.98% | 0.00% |
| 1 | 1,037,720 | 28.49% | 3.97% | 48.30% | 99.33% |
| 2 | 1,101,821 | 30.25% | 25.30% | 5.56% | 97.22% |

## Benchmarks de entrenamiento

| Workers | Mediana | Speedup | Eficiencia |
|---:|---:|---:|---:|
| 1 | 4641 ms | 1.000× | 100.0% |
| 2 | 3150 ms | 1.473× | 73.7% |
| 4 | 2633 ms | 1.763× | 44.1% |
| 8 | 1943 ms | 2.389× | 29.9% |

## Limitaciones

- Las unidades de observación son líneas presupuestarias, no municipalidades.
- Las tasas de ejecución y Q4 promediadas por línea NO representan razones agregadas.
- PIM=0 fija a cero la variable tasa_ejecucion_acotada; no equivale a ejecución real de 0%.
- Los importes signed_log_* NO están expresados directamente en soles.
- No se estimó Silhouette Score para el experimento masivo.
- Las validaciones usan reportes y metadatos: no recalculan los 3.64M registros sin el binario.
