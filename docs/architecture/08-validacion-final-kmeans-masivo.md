# PC3 — Validación final reproducible del K-Means masivo

Se mantienen separados el modelo de municipalidades (3,783 perfiles ejecutora–año) y el experimento de escalabilidad a nivel de línea presupuestaria (3,642,510 registros, 9 características).

## Pasos

En PowerShell, desde la raíz del repositorio y después de ejecutar el entrenamiento con workers=1,2,4,8 y el perfilado:

```powershell
go test -race ./internal/...
go vet ./...
py -m unittest discover -s tests -p "test_validate_massive_pc3.py" -v
py scripts/validation/validate_massive_pc3.py
```

Produce `data/processed/massive_mef/validacion_final.json` y `validacion_final.md`.

## Qué comprueba

- Concordancia de los conteos oficiales utilizados en el experimento: 5,596,932 filas de origen, 3,642,510 municipales y 578,956 de proyectos municipales.
- Coincidencia de nueve características y tres clústeres entre metadatos, cuatro reportes de entrenamiento y perfilado.
- Convergencia y asignación exacta de todas las filas según los reportes, equivalencia de tamaños de grupos, centroides e inercias entre workers.
- Concordancia de inercia y centroides entre entrenamiento y perfilado.
- Cálculo independiente de medianas, speedup y eficiencia en el CSV original de doce ejecuciones, y su conciliación con el CSV de resumen.

## Límites

El script valida la **consistencia de reportes generados**: no reitera la lectura del archivo binario ni puede verificar la veracidad administrativa de cada registro. Se deben conservar los logs originales y las pruebas Go. Las características signed_log_* son importes transformados; tasas y Q4 son medias simples por línea y no razones financieras agregadas. Si PIM=0, la función de extracción asigna 0 a la tasa de ejecución acotada y registra la condición con `pim_cero`; esto no indica una tasa real del 0 %.

No se estimó silueta ni selección óptima de K para el experimento masivo. Ese entrenamiento tiene finalidad exploratoria y de desempeño concurrente, diferente al modelo municipal principal.
