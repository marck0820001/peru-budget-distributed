# PC4 — Medición reproducible de latencias HTTP

## Instalación

Copia `benchmark_pc4_http.ps1` a `scripts/pc4/benchmark_http.ps1` dentro de `peru-budget-distributed`.

Desde la raíz del repositorio, en Windows PowerShell:

```powershell
docker compose -f compose.pc4.storage.yaml ps
Invoke-RestMethod http://localhost:8080/health
powershell -ExecutionPolicy Bypass -File scripts/pc4/benchmark_http.ps1 -Iterations 50
```

El script realiza 3 solicitudes de calentamiento por endpoint y **50 solicitudes medidas por cada uno de los cinco endpoints GET**: `health`, `storage`, `nodes`, `job` y `result` (250 solicitudes medidas en total). **No realiza POST ni inicia entrenamientos**.

Si el identificador de entrenamiento cambia:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/pc4/benchmark_http.ps1 `
    -Iterations 50 -JobId 'ID_NUEVO'
```

## Evidencias generadas

- `docs/evidence/pc4/latencias_http_detalle.csv`: una fila por solicitud (fecha, endpoint, iteración, HTTP, milisegundos y error).
- `docs/evidence/pc4/latencias_http_resumen.csv`: número de respuestas HTTP 200, fallos, porcentaje bajo 100 ms, mediana, P95 y máximo.
- `docs/evidence/pc4/latencias_http_resumen.json`: resumen estructurado para informes.

El tiempo **se mide desde el cliente PowerShell**, con `Invoke-WebRequest`, e incluye el tiempo de la solicitud y el tratamiento básico de la respuesta. No equivale a la duración de entrenamiento K-Means, ni necesariamente al tiempo que Postman registre. El P95 es el percentil de rango más cercano entre solicitudes HTTP 200; los errores HTTP se reportan aparte y no se descartan del porcentaje de cumplimiento.

## Postman

Para evidencia propia de Postman, crea una colección con esos mismos cinco endpoints GET. En cada solicitud coloca en **Tests**:

```javascript
pm.test('HTTP 200', () => pm.response.to.have.status(200));
pm.test('Latencia menor a 100 ms', () => {
    pm.expect(pm.response.responseTime).to.be.below(100);
});
```

Guarda las solicitudes y utiliza **Run collection → Iterations = 50** (250 solicitudes). Desmarca cualquier solicitud POST. Exporta los resultados cuando tu versión de Postman lo permita y toma capturas del resumen de tests, tiempos y fallos.

## Interpretación

- **Correctitud**: 100 % de respuestas HTTP 200 y, cuando aplique, verificaciones funcionales del contenido JSON.
- **Latencia**: comparar mediana, P95 y máximo con el umbral de **100 ms** solicitado. Si P95 supera 100 ms, no afirmar que cumple el umbral a P95.
- **Caché**: al existir calentamiento, las medidas representan principalmente el comportamiento en caliente (warm cache). Conviene medir adicionalmente arranque en frío para un análisis exhaustivo.
- **Límites**: las llamadas HTTP de consulta no ejecutan el algoritmo de entrenamiento, que puede tardar segundos. La respuesta del `POST /api/v1/train` es asíncrona; la latencia de aceptación se mide por separado.

No utilizar `docker compose down -v`: los volúmenes MongoDB y Redis contienen las evidencias persistentes.
