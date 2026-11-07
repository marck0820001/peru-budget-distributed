# Módulo MEF — Preprocesamiento y validación (PC3)

## Instalación

No requiere librerías externas para estos dos scripts (Python 3.10+). Colocar los cuatro CSV originales en `data/raw/`. En esta etapa solo se procesan los **dos Gasto Devengado**; `Seguimiento PI` queda reservado hasta definir su integración.

## Antes de ejecutar

Verificar rama de trabajo:

```powershell
git branch --show-current
# feature/eda-preprocessing
```

Usar aproximadamente 2.6 GB por archivo de entrada. El modo `full --write-lines` crea un archivo comprimido adicional; comprobar espacio disponible.

## Primera prueba (SMOKE)

```powershell
py -m unittest discover -s tests -p "test_preprocess_data.py" -v
py scripts/eda/preprocess_data.py --mode smoke --smoke-local 500
py scripts/eda/validate_data.py
```

**Importante:** los CSV están ordenados por nivel de gobierno: el modo smoke puede recorrer muchas filas antes de encontrar las primeras 500 locales. Nunca presentar sus conteos como proporciones nacionales.

## Ejecutar todos los datos

```powershell
py scripts/eda/preprocess_data.py --mode full --write-lines
py scripts/eda/validate_data.py --require-full --check-lines
py scripts/eda/export_evidence.py
```

Si `inventario_eda.csv` existe en `data/processed/eda_estadistico/`, ejecutar:

```powershell
py scripts/eda/validate_data.py --require-full --check-lines `
  --compare-eda "data/processed/eda_estadistico/inventario_eda.csv"
```

Si los CSV están fuera del repositorio:

```powershell
py scripts/eda/preprocess_data.py --mode full --write-lines --data-dir "D:/Datos/MEF"
```

Para evitar escribir `budget_lines_clean.csv.gz`, omitir `--write-lines`. En ese caso no utilizar `--check-lines` con el validador.

## Salidas

`data/processed/preprocessing_mef/` (IGNORADA por Git):

- `reporte_preprocesamiento.json`: recuentos, incidencias y balances exactos.
- `resumen_preprocesamiento.md`: lectura breve del resultado.
- `incidencias_preprocesamiento.csv`: filas rechazadas y motivos.
- `municipality_year_features.csv`: perfiles candidatos por ejecutora-año.
- `project_features.csv`: perfiles de proyectos de Gasto Devengado por ejecutora-año-código.
- `budget_lines_clean.csv.gz`: opcional, líneas validadas con su procedencia.
- `validacion_preprocesamiento.json` y `resumen_validacion.md`: pruebas de coherencia.
- `data/processed/preprocesamiento_mef_resultados.zip`: ZIP pequeño, sin datasets de varios GB, para compartir en el chat.

No subir datos grandes al repositorio. Compartir solamente reportes reducidos y resultados agregados revisados.

## Interpretación de errores

- Si la suma mensual difiere del devengado anual, no modificar el dato para que encaje: revisar la incidencia y el período/corte de publicación.
- Si un monto tiene coma decimal ambigua o más de dos decimales, se rechaza hasta verificar el formato. No se redondea silenciosamente.
- Si `--require-full` falla, se ejecutó una muestra. Correr `--mode full` antes de reportar resultados.
- Si aparece `FAIL`, no entrenar y revisar `resumen_validacion.md`.

## Próximas etapas

1. Revisar discrepancias e indicadores con alta concentración/extremos.
2. Definir y documentar matriz de entrenamiento, escalamiento y criterio de K.
3. Implementar ingestión concurrente y K-Means paralelo en **Go**, con experimentos 1/2/4/8 workers y métricas de speedup y convergencia.
