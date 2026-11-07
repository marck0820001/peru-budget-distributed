#!/usr/bin/env python3
"""Empaqueta resultados pequeños para compartir; exige validación PASS."""
from __future__ import annotations

import argparse
import json
import zipfile
from pathlib import Path
from feature_engineering import ROOT

FILES = (
    "reporte_features.json", "validacion_features.json", "feature_transformer.json",
    "resumen_features.md", "resumen_validacion_features.md",
    "municipality_features_audit.csv", "municipality_features_scaled.csv",
    "kmeans_matrix.csv", "kmeans_keys.csv",
)


def export(out_dir: Path, zip_path: Path) -> Path:
    validation = out_dir / "validacion_features.json"
    if not validation.is_file() or json.loads(validation.read_text(encoding="utf-8"))["status"] != "PASS":
        raise ValueError("Ejecuta validate_features.py y confirma PASS antes de exportar")
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED,
                         compresslevel=7) as archive:
        for filename in FILES:
            file = out_dir / filename
            if not file.is_file():
                raise FileNotFoundError(file)
            archive.write(file, filename)
        plots = out_dir / "graficos"
        if plots.is_dir():
            for png in sorted(plots.glob("*.png")):
                archive.write(png, f"graficos/{png.name}")
    return zip_path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "data/processed/features_mef")
    parser.add_argument("--zip", type=Path, default=ROOT / "data/processed/features_mef_resultados.zip")
    args = parser.parse_args()
    print("ZIP generado:", export(args.output_dir, args.zip))


if __name__ == "__main__":
    main()
