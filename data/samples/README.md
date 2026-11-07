# Muestras sintéticas

`2024-Gasto-Devengado.csv` y `2025-Gasto-Devengado-Mensual.csv` son **muestras sintéticas pequeñas** generadas con
`go run ./cmd/gendata --out data/samples --scale 0.0006 --munis 60`. Tienen las mismas 73 columnas y el mismo
formato entrecomillado que los CSV del MEF, para probar el pipeline sin descargar los archivos oficiales:

```bash
go run ./cmd/etl --data-dir data/samples --out data/processed/sample_etl
go run ./cmd/trainer --in data/processed/sample_etl --kmax 6
```

No contienen datos reales del MEF; los nombres de ejecutoras son ficticios.
