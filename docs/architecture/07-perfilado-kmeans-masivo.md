# PC3 — Caracterización de clústeres masivos en Go

Este módulo **añade** `cmd/massiveprofile/` y dos archivos a `internal/ml/massive/`. No sobrescribe el entrenador ni el ETL. Está diseñado para la solución de K-Means sobre **3,642,510 líneas presupuestarias**, que **no** son municipios.

## Integración

Extraer el ZIP en la raíz del repositorio y ejecutar:

```powershell
go test -race ./internal/ml/massive/...
go vet ./...
go build -o massiveprofile.exe ./cmd/massiveprofile
```

El módulo Go debe coincidir con `github.com/marck0820001/peru-budget-distributed.git`.

## Ejecutar sobre los datos reales

```powershell
.\massiveprofile.exe `
  -out "data/processed/massive_mef" `
  -report "training_k3_w4_seed42.json" `
  -workers 4
```

Salida: `data/processed/massive_mef/profile_k3_seed42.json`, con los tamaños observados, la proporción de proyectos, PIM cero, devengado cero, participación media del Q4, meses activos y las medias de las 9 variables originales y de los z-scores acotados.

**Validaciones automáticas**: las 3,642,510 filas se asignan exactamente una vez, las cantidades por grupo coinciden con el reporte del entrenamiento, el archivo binario tiene el tamaño previsto y la inercia coincide dentro de tolerancia de redondeo.

## Interpretación técnica

- `MeanOriginal` son medias de *características ya extraídas*, antes de normalización. Para `signed_log_pia/pim/devengado` son **logaritmos con signo**, NO importes en soles.
- `tasa_ejecucion_acotada` y `participacion_q4_acotada` son promedios de cocientes **por línea**: no son indicadores financieros consolidados de una municipalidad, no deben presentarse como tales.
- `es_proyecto`, `pim_cero`, `devengado_cero` son variables 0/1: su media permite conocer la fracción de registros del grupo con esa condición.
- El análisis no calcula silueta ni verifica por sí solo K óptimo; para el modelo principal de municipalidades se eligió provisionalmente K=3 por interpretabilidad.
- Si grupos se diferencian principalmente por `pim_cero` o `devengado_cero`, el resultado es una segmentación exploratoria de **tipos de líneas contables** y **evidencia de escalabilidad**, NO un sistema de detección automática de anomalías administrativas.

## Guardar en Git

```powershell
git add cmd/massiveprofile internal/ml/massive/profile.go internal/ml/massive/profile_test.go README-PERFILADO-MASIVO-PC3.md
git commit -m "feat(ml): validate and profile massive K-Means clusters"
git push origin feature/parallel-kmeans
```

NO subir `data/raw`, `data/processed`, `budget_lines.f64`, `.exe` o archivos de más de 100 MB.
