#!/usr/bin/env python3
"""Comprime un resumen pequeño del preprocesamiento para revisar o adjuntar.

No incluye los CSV originales ni el CSV comprimido de millones de filas.
"""
import argparse
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FILES = (
    "reporte_preprocesamiento.json",
    "resumen_preprocesamiento.md",
    "validacion_preprocesamiento.json",
    "resumen_validacion.md",
    "municipality_year_features.csv",
    "project_features.csv",
    "incidencias_preprocesamiento.csv",
)


def export_evidence(source: Path, output: Path) -> None:
    missing = [n for n in FILES if not (source / n).is_file()]
    if missing:
        raise FileNotFoundError(f"Faltan resultados: {missing}. Ejecuta antes preprocesamiento y validación.")
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED, compresslevel=7) as z:
        for name in FILES:
            z.write(source / name, arcname=name)
    print(f"ZIP generado: {output}")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--input-dir", type=Path,
                   default=ROOT / "data" / "processed" / "preprocessing_mef")
    p.add_argument("--out", type=Path,
                   default=ROOT / "data" / "processed" / "preprocesamiento_mef_resultados.zip")
    args = p.parse_args()
    export_evidence(args.input_dir, args.out)


if __name__ == "__main__":
    main()
