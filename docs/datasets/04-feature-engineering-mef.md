# PC3 — Feature Engineering para K-Means municipal

## Entradas

- `data/processed/preprocessing_mef/municipality_year_features.csv`
- `data/processed/preprocessing_mef/reporte_preprocesamiento.json` (modo `full`, conciliaciones `True`)

No usar `municipalidades_indicadores_exploratorios.csv` de EDA: tiene columnas y precisión distintas.

## Unidad de análisis

Una observación = una ejecutora municipal en un ejercicio fiscal (`ano_eje`, `sec_ejec`).
La matriz del modelo **no** contiene 3.6 millones de observaciones: los 3,642,510 son líneas de origen, utilizadas para el procesamiento masivo. Es incorrecto afirmar que K-Means municipal entrena sobre millones.

## Población y reglas

- Se conservan en el archivo de auditoría **todos** los perfiles y se distinguen mancomunidades y otras ejecutoras por nombre. La tipificación es preliminar y necesita contraste con padrón institucional.
- K-Means principal incluye entidades cuyo nombre comienza por `MUNICIPALIDAD`, con metadatos coherentes, PIM y devengado positivos, PIA no negativo y agregación íntegra.
- PIA cero **no** se excluye y **no** se imputa. La modificación presupuestaria se calcula como diferencia de logaritmos para evitar la división por cero.
- Las líneas con ajustes negativos no se eliminan del origen. Las razones de exclusión y advertencias se registran.
- Mancomunidades quedan en auditoría y fuera del modelo principal. Confirmar nombres y categorías antes de presentar resultados definitivos.

## Indicadores numéricos candidatos

1. `tasa_ejecucion`: devengado/PIM.
2. `modificacion_log_pim_pia`: `log1p(PIM) - log1p(PIA)`.
3. `participacion_devengado_proyectos`: devengado proyectos/devengado total.
4. `concentracion_q4`: devengado oct-dic/devengado anual (del preprocesamiento).
5. `cv_devengado_mensual`: coeficiente de variación mensual (del preprocesamiento).
6. `log1p_pim`: escala del presupuesto institucional modificado.

## Transformación y trazabilidad

- Winsorización entre percentiles 1 % y 99 % calculados sobre perfiles elegibles 2024–2025, sin alterar valores originales de auditoría.
- Mediana e IQR de los valores winsorizados para robust scaling; si IQR es cero, desviación estándar como alternativa documentada. Se excluyen variables sin variabilidad.
- Todos los parámetros se guardan en `feature_transformer.json`; **no volver a calcularlos con 2026** cuando se use como dato nuevo.
- Los centroids e interpretaciones deben estimarse únicamente tras seleccionar `K` y ejecutar K-Means en Go.
- El escalamiento robusto puede favorecer unas variables frente a otras. Revisar correlaciones y hacer un análisis de sensibilidad tras el primer entrenamiento.

## Validación e investigación pendientes

- Confirmar que la clasificación basada en `EJECUTORA_NOMBRE` corresponde al padrón de municipalidades.
- Revisar `exclusion_reasons` y cuántos perfiles presentan ajustes o proporciones fuera de [0,1].
- Verificar resultados de `validate_features.py`, que reconstruye todas las operaciones numéricas y los IDs.
- Para **PC3**, demostrar carga de >1M registros con Go + goroutines/channels, además de K-Means paralelo; Python es solo auxiliar de EDA.
- Seguimiento PI no se fusiona todavía; no atribuir a K-Means detección de corrupción o eficacia gubernamental.
