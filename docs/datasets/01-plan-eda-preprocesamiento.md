# PC3 — Plan de EDA y preprocesamiento del MEF

## Objetivo del primer corte

Determinar si la fuente Gasto Devengado contiene suficiente volumen efectivo de gobiernos locales para el caso 6; estudiar la estructura de Seguimiento PI como fuente complementaria **sin sumar o unir filas indiscriminadamente**.

## Etapas

1. Inventario y estructura: nombres, codificación, separadores, tipos esperables, período.
2. Volumen y cobertura: total por archivo, gobiernos locales, categorías de proyectos, departamentos.
3. Integridad: filas mal formadas, nulos en claves, codificaciones pendientes.
4. Granularidad y claves: combinación que define una fila; cardinalidad de municipalidades, proyectos y años; posibles duplicados.
5. EDA numérico: PIA, PIM, devengados, valores extremos, ejecución mensual y comparación a igual período.
6. Definición y preprocesamiento de variables: transformaciones, escalamiento, cero-denominadores, datos faltantes.
7. Decisión de modelado: K-Means en partidas/proyectos/perfiles municipales, con métricas y benchmarking.

## Criterios de decisión

- **Más de 2 M filas:** objetivo específico sugerido para el caso 6; comprobarlo en registros válidos del conjunto a modelar, no por tamaño del archivo.
- **Más de 1 M filas:** requisito general de carga y procesamiento concurrente (se demostrará en Go, no con este script Python).
- Distinguir proyectos de actividades y obras; sin diccionario válido no asumir que un código numérico tenga un significado específico.
- Los conjuntos de Seguimiento PI y Devengado no se concatenan como si fueran registros homogéneos.
- 2025 podría representar un corte parcial; se comprueba antes de contrastar con 2024.
- No se modifica el CSV original. El código Python es auxiliar EDA; ETL concurrente y K-Means deberán implementarse en Go.

## Evidencias para PC3

Reportes y pruebas reproducibles, cantidades reales, decisiones de limpieza, diagramas de flujo, cambios versionados en GitHub y tareas en Kanban.
