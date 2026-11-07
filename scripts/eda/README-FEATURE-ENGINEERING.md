# PC3 — Feature Engineering del MEF

Requisitos: Python 3.10+; scripts principales sin paquetes externos. Para gráficos: `py -m pip install matplotlib`.

**Ejecutar en raíz del repositorio**, rama `feature/eda-preprocessing`:

```powershell
py -m unittest discover -s tests -p "test_feature_engineering.py" -v
py scripts/eda/feature_engineering.py
py scripts/eda/validate_features.py
py -m pip install matplotlib
py scripts/eda/plot_features.py
py scripts/eda/export_features_evidence.py
```

Si trabajas con otras rutas:

```powershell
py scripts/eda/feature_engineering.py --input "D:/MEF/municipality_year_features.csv" --preprocessing-report "D:/MEF/reporte_preprocesamiento.json" --output-dir "D:/MEF/features"
py scripts/eda/validate_features.py --source "D:/MEF/municipality_year_features.csv" --preprocessing-report "D:/MEF/reporte_preprocesamiento.json" --output-dir "D:/MEF/features"
py scripts/eda/plot_features.py --output-dir "D:/MEF/features"
```

## Archivos de salida

Carpeta `data/processed/features_mef/` (se recomienda excluirla de Git):

- `municipality_features_audit.csv`: todos los perfiles, razones de exclusión y métricas no escaladas.
- `municipality_features_scaled.csv`: claves y variables numéricas escaladas, perfiles elegibles.
- `kmeans_matrix.csv`: solo variables numéricas, ordenadas igual que el archivo de claves, para el trainer Go.
- `kmeans_keys.csv`: año, entidad y descripción en el mismo orden (NO son features numéricas).
- `feature_transformer.json`: winsorización, mediana, escalas y variables incluidas.
- `reporte_features.json`: conteos reales y justificación.
- `validacion_features.json`: PASS/FAIL; coherencia del número de perfiles, SHA-256 de entrada y reconstrucción de cada valor escalado.
- `resumen_features.md`, `resumen_validacion_features.md` y `graficos/*.png`.

**Importante:** no uses `apto_candidato` del archivo anterior como etiqueta; aquella regla excluía PIA=0. Esta fase vuelve a evaluar elegibilidad. Los resultados de K-Means en Go no estarán contenidos en este paquete.

## Git

```powershell
git add scripts/eda/feature_engineering.py scripts/eda/validate_features.py scripts/eda/plot_features.py scripts/eda/export_features_evidence.py scripts/eda/README-FEATURE-ENGINEERING.md tests/test_feature_engineering.py docs/datasets/04-feature-engineering-mef.md
git commit -m "feat(eda): prepare and validate municipality K-Means features"
git push origin feature/eda-preprocessing
```

**Para compartir resultados:** adjuntar `data/processed/features_mef_resultados.zip`. No adjuntar los cuatro CSV masivos del MEF.
