# Auditoría de suficiencia de datos — MEF

El script `audit_volume.py` inspecciona en streaming los cuatro CSV originales del MEF.

## Ejecución desde la raíz del repositorio

```powershell
py scripts/eda/audit_volume.py --mode quick
py scripts/eda/audit_volume.py --mode full
py -m unittest discover -s tests -p "test_audit_volume.py" -v
```

Si los CSV están en otro disco:

```powershell
py scripts/eda/audit_volume.py --mode full --data-dir "D:\\MEF"
```

## Salida

`data/processed/auditoria_volumen/resumen.md`, `reporte.json`, `inventario_volumen.csv` y
`data/processed/auditoria_volumen_mef_full.zip` (en modo full).

La salida queda ignorada por Git si `data/processed/*` está incluido en `.gitignore`.

## Interpretación

- La cuenta de registros locales se basa únicamente en etiquetas explícitas como `M` o `Gobiernos Locales`.
- Los códigos numéricos de `TIPO_ACT_PROY` se **reportan, pero no se interpretan automáticamente**.
- **No sumar** los registros de Seguimiento PI con los de Gasto Devengado; pueden solaparse y tener granularidades diferentes.
- El resultado `gobiernos_locales > 2M` es una primera comprobación de volumen: aún deben aplicarse filtros de proyectos y controles de calidad.
- El modo `quick` no confirma el número total de filas.
- No se realiza preprocesamiento definitivo ni entrenamiento hasta revisar encabezados, valores y granularidad con el equipo.
