# Arquitectura de entrenamiento sobre líneas presupuestarias (PC3)

Entrada CSV MEF 2024/2025 (5,596,932 filas originales)
  -> filtro `NIVEL_GOBIERNO=M`
  -> validación estricta de importes en céntimos
  -> nueve características específicas de LINEA PRESUPUESTARIA
  -> archivo binario de registros f64 (3,642,510 × 9 × 8 bytes esperado)
  -> media/std globales, documentadas en JSON
  -> inicialización K-Means++ sobre muestra uniforme de 10,000 líneas
  -> iteraciones Lloyd exactas sobre TODOS los vectores, normalizados por bloque
  -> workers concurrentes ReadAt + goroutines, reducción por channel
  -> coordinador sincroniza centroides al terminar la iteración
  -> reporte de inercia, tamaños de clúster, convergencia y tiempos

## Por qué dos modelos

- **Municipalidad/año**: 3,783 perfiles y seis variables derivadas; análisis sustantivo municipal. K=3 favorece interpretación; K=2 maximiza la silueta observada.
- **Línea presupuestaria**: millones de registros y nueve variables propias; experimento de complejidad y escalabilidad. K y etiquetas no son comparables con los del primer modelo.

## Memoria y concurrencia

Los datos brutos están en disco; la memoria de entrenamiento crece aproximadamente con `workers * batch_rows * features` más 10,000 puntos de muestra y K centroides. Los workers tienen rangos disjuntos y sumas locales. El coordinador realiza reducción en orden fijo de worker para mejorar reproducibilidad. Los resultados de punto flotante pueden cambiar ligeramente entre cantidades de workers por el orden de sumas; los benchmarks deben evaluar tolerancia numérica.

## Limitaciones

- Inicialización aproximada K-Means++ basada en una muestra uniforme, pero Lloyd completo.
- Transformación z-score y truncamiento ±5, no necesariamente los mejores para todas las líneas.
- Predominio de montos cero y registros presupuestarios con semánticas diferentes.
- No se almacena la asignación por línea, solo conteos, inercia y centroides.
- Concurrencia en una máquina; distribución TCP como evolución PC4.
- Los clústeres no determinan corrupción ni incumplimientos.
