# EDA estadístico del MEF — Caso 6

Herramientas **auxiliares** de Python para estudiar los CSV antes de seleccionar variables de K-Means paralelo en **Go**. No implementan el algoritmo de Machine Learning ni la carga concurrente requerida en la PC3.

## Archivos de entrada (en `data/raw/`)

- `2024-Gasto-Devengado.csv`
- `2025-Gasto-Devengado-Mensual.csv`
- `2024-Seguimiento-PI.csv`
- `2025-Seguimiento-PI.csv`

Los nombres pueden contener variantes siempre que incluyan `2024`/`2025` + `Gasto` + `Devengado`, o `Seguimiento` + `PI`. Si existen varias coincidencias para el mismo alias, el script **se detiene** para evitar usar dos versiones sin querer.

## Instalación

Python 3.10+; el análisis estadístico **no requiere dependencias externas**. Para gráficos PNG, opcionalmente:

```powershell
py -m pip install matplotlib
```

## Ejecución desde la raíz del repositorio

```powershell
# Prueba de esquema y ejecución. NO es muestra representativa.
py scripts/eda/exploratory_analysis.py --mode quick --quick-rows 10000

# Análisis estadístico completo, leyendo los 4 CSV íntegramente.
py scripts/eda/exploratory_analysis.py --mode full

# Genera gráficos a partir de reportes (no relee los CSV originales).
py scripts/eda/plot_eda.py

# Pruebas unitarias del módulo nuevo
py -m unittest discover -s tests -p "test_exploratory_analysis.py" -v
```

Si los CSV están fuera del repositorio:

```powershell
py scripts/eda/exploratory_analysis.py --mode full --data-dir "D:\\datasets\\MEF"
```

## Salidas

Ruta base `data/processed/eda_estadistico/` (fuera de Git gracias a `.gitignore`):

- `resumen_eda.md`: lectura inmediata de volumen y advertencias.
- `inventario_eda.csv`: conteos estructurales y de gobierno local; contraste de devengado mensual/anual.
- `calidad_montos.csv`: nulos, no numéricos, ceros, negativos, mínimos, máximos, promedio y percentiles estimados.
- `evolucion_mensual_local.csv`: montos por mes **solo gobierno local** y número de registros con importes distintos de cero.
- `cobertura_local_departamento.csv`: registros por departamento, año y publicación.
- `anos_disponibles.csv`: distribución de `ANO_EJE`, especialmente importante en Seguimiento PI.
- `tipos_actividad_proyecto.csv` y `PI_codigos_descripcion.csv`: relación entre código `TIPO_ACT_PROY` y descripción explícita.
- `municipalidades_indicadores_exploratorios.csv`: sumatorias e indicadores **candidatos**, no dataset de entrenamiento definitivo.
- `reporte_eda.json`: conteos, advertencias y metadatos para reproducibilidad.
- `graficos/*.png`: tres gráficos para evidencias (ejecutar segundo script).

Se crea también `data/processed/eda_estadistico_mef_full.zip` (o `...quick.zip`) con las tablas y el resumen. **Adjunta ese ZIP a la conversación** para examinar resultados.

## Precauciones metodológicas

1. La base `Seguimiento PI` de 2025 contiene valores `ANO_EJE` históricos. No se puede sumar a la base PI 2024 como proyectos independientes. Las claves compartidas entre ambas publicaciones se reportan como indicio de solapamiento, **no como duplicados exactos**.
2. Los CSV de Gasto Devengado tienen filas de **clasificación presupuestaria**. La combinación de `(ANO_EJE, SEC_EJEC, PRODUCTO_PROYECTO)` repetida puede ser legítima por distintos clasificadores/fuentes de financiamiento.
3. El modo `quick` inspecciona el **inicio** de cada CSV. Si está ordenado por nivel de gobierno puede no contener municipales; jamás extrapolar sus porcentajes.
4. En `calidad_montos.csv`, los conteos de montos son exactos **dentro de las filas locales analizadas**; los percentiles p01–p99 son **aproximados** por reservoir sampling (muestra limitada) y existen únicamente para campos priorizados. Montos inválidos no se imputan automáticamente.
5. El resumen de 2025 no se considera año completo sin revisar el **último mes con devengado**. Para comparaciones interanuales igualar el mes de corte.
6. Los indicadores de municipalidades se calculan sumando líneas de Gasto Devengado por `(ANO_EJE, SEC_EJEC)`. **No son aptos para modelar hasta verificar duplicidades, las reglas de suma y representatividad.** El PIM de una obra no equivale a su avance físico.
7. Se lee en streaming, sin cargar los CSV íntegros a RAM. Sin embargo se almacenan claves de proyectos para analizar su granularidad y solapamiento; el consumo de memoria **crece con el número de claves únicas**. En caso de memoria insuficiente, habrá que migrar el conteo exacto de claves a una tabla SQLite o DuckDB en disco.
8. Este script no elimina valores extremos ni transforma definitivamente los datos. Eso se implementará tras revisar evidencias.

## Qué decisiones tomar con los resultados

- ¿Los registros locales siguen superando 2M después de controles de calidad?
- ¿`2025` tiene los doce meses disponibles o un corte anterior?
- ¿El código `TIPO_ACT_PROY = 2` de Seguimiento PI se describe como proyecto?
- ¿Cuánto solapamiento existe entre los archivos de Seguimiento PI?
- ¿Cuántos proyectos distintos hay frente a líneas presupuestarias por proyecto?
- ¿Qué porcentaje de montos PIA, PIM y devengado es nulo, negativo o atípico?
- ¿Agrupar partidas/proyectos (gran volumen) o municipalidades-año (mayor interpretabilidad)?

No unir datasets ni entrenar K-Means hasta resolver estas preguntas.
