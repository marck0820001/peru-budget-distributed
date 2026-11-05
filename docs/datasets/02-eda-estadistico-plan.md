# PC3 · Caso 6 — Plan de análisis estadístico

**Proyecto:** `peru-budget-distributed`  
**Branch:** `feature/eda-preprocessing`  
**Fuente:** Ministerio de Economía y Finanzas (MEF), Gasto Devengado 2024-2025 y Seguimiento de Proyectos de Inversión (snapshots 2024-2025).

## Línea de base verificada (auditoría anterior)

| Fuente | Filas totales | Gobierno local | Local + etiqueta PROYECTO |
|---|---:|---:|---:|
| Gasto 2024 | 2,789,756 | 1,829,290 | 293,159 |
| Gasto 2025 | 2,807,176 | 1,813,220 | 285,797 |
| PI 2024 | 722,358 | 632,761 | No determinado por etiqueta textual en auditoría inicial |
| PI 2025 | 708,068 | 619,257 | No determinado por etiqueta textual en auditoría inicial |

**Nota:** 3,642,510 filas locales de Gasto en total; 578,956 líneas locales clasificadas explícitamente como `PROYECTO`. Son registros iniciales; la auditoría aún no ha demostrado ausencia de duplicidades ni idoneidad para modelado.

## Objetivo del nuevo EDA

1. Validar que `MONTO_PIA`, `MONTO_PIM` y `MONTO_DEVENGADO_ANUAL` tienen suficientes valores numéricos interpretables y analizar distribuciones.
2. Verificar integridad de la relación entre devengado mensual y anual, y detectar el mes de corte de 2025.
3. Cuantificar la diferencia entre proyectos y partidas y estudiar las coincidencias de identificadores entre ambas publicaciones PI.
4. Construir **solo como candidatos** indicadores de ejecución municipal, manteniendo el nivel de agregación explícito.
5. Definir con resultados reproducibles las transformaciones necesarias antes de implementar paralelismo y K-Means en Go.

## Cuestiones abiertas

- Identidad presupuestaria exacta de cada fila y cómo verificar duplicados reales.
- Interpretación contable exacta de montos negativos y correcciones.
- Comparabilidad temporal de las variables 2024 y 2025.
- Si la unidad principal del clustering será partida, proyecto o municipalidad-año.
- Relación entre `PRODUCTO_PROYECTO` de Gasto y Seguimiento PI (la coincidencia del código no demuestra unión uno a uno).

## Evidencias para informe

- `resumen_eda.md`, `inventario_eda.csv`, `calidad_montos.csv`, `anos_disponibles.csv`.
- Capturas/gráficos de `01_devengado_mensual.png`, `02_tasa_ejecucion.png`, `03_cobertura_departamentos.png`.
- Comandos reproducibles y conclusiones del equipo. No inventar resultados numéricos antes de ejecutar con CSV reales.
