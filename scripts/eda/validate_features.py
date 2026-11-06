#!/usr/bin/env python3
"""Valida la matriz de K-Means y los metadatos de feature_engineering.py.

Compara orden, conteos, IDs y reconstruye todas las transformaciones numéricas.
Salida: validacion_features.json y resumen_validacion.md.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
from collections import Counter
from pathlib import Path
from typing import Any

from feature_engineering import ROOT, KEYS, get_int, sha256_file


def read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        rd = csv.DictReader(f)
        if not rd.fieldnames:
            raise ValueError(f"CSV sin encabezado: {path}")
        return list(rd.fieldnames), list(rd)


def validate(out_dir: Path, source_path: Path, preprocessing_report: Path) -> dict[str, Any]:
    errors: list[str] = []
    required = ["reporte_features.json", "feature_transformer.json",
                "municipality_features_audit.csv", "municipality_features_scaled.csv",
                "kmeans_matrix.csv", "kmeans_keys.csv"]
    for filename in required:
        if not (out_dir / filename).is_file():
            raise FileNotFoundError(f"Falta {out_dir / filename}")
    report = json.loads((out_dir / "reporte_features.json").read_text(encoding="utf-8"))
    scaler = json.loads((out_dir / "feature_transformer.json").read_text(encoding="utf-8"))
    preprocess = json.loads(preprocessing_report.read_text(encoding="utf-8-sig"))
    audit_hdr, audit = read_csv(out_dir / "municipality_features_audit.csv")
    scaled_hdr, scaled = read_csv(out_dir / "municipality_features_scaled.csv")
    matrix_hdr, matrix = read_csv(out_dir / "kmeans_matrix.csv")
    keys_hdr, keys = read_csv(out_dir / "kmeans_keys.csv")
    features = scaler["features"]
    if not features or len(features) < 2:
        errors.append("Se necesitan por lo menos dos features")
    if scaled_hdr != list(KEYS) + features:
        errors.append("Encabezado de municipality_features_scaled no coincide")
    if matrix_hdr != features:
        errors.append("Encabezado de kmeans_matrix no coincide")
    if keys_hdr != list(KEYS):
        errors.append("Encabezado de kmeans_keys no coincide")
    if len(audit) != report["input_profiles"]:
        errors.append("Conteo de auditoría != perfiles de entrada")
    if len(scaled) != len(matrix) or len(matrix) != len(keys):
        errors.append("Filas de matriz, escalado y claves no coinciden")
    if len(matrix) != report["eligible_profiles"] or len(matrix) != report["matrix_rows"]:
        errors.append("Número de filas de matriz != reporte_features")
    if len(features) != report["matrix_columns"]:
        errors.append("Cantidad de features != reporte_features")
    eligible_audit = [r for r in audit if r["eligible"] == "1"]
    if len(eligible_audit) != len(matrix):
        errors.append("Auditoría de elegibles != filas del modelo")
    if len(audit) != len(matrix) + report["excluded_profiles"]:
        errors.append("Balance de perfiles inválido")
    if report["source_csv_sha256"] != sha256_file(source_path):
        errors.append("CSV de entrada cambió desde feature_engineering")
    if preprocess["totals"]["municipality_year_profiles"] != len(audit):
        errors.append("Número de perfiles no coincide con preprocesamiento")
    if sum(get_int(r["n_lineas"], "n_lineas") for r in audit) != preprocess["totals"]["local_accepted"]:
        errors.append("Suma de líneas no coincide con preprocesamiento")
    if preprocess.get("mode") != "full":
        errors.append("Preprocesamiento no es FULL: evidencia no apta para PC3")
    if any(v is not True for v in preprocess.get("integrity", {}).values()):
        errors.append("Integridad anterior no aprobada")
    if not preprocess.get("integrity"):
        errors.append("No hay pruebas de integridad en reporte anterior")
    audit_map = {(r["ano_eje"], r["sec_ejec"]): r for r in eligible_audit}
    if len(audit_map) != len(eligible_audit):
        errors.append("Identificadores duplicados en la auditoría de elegibles")
    seen_ids = set()
    bad_numeric = Counter()
    max_dif = 0.0
    for row_idx, (r_scaled, r_matrix, r_keys) in enumerate(zip(scaled, matrix, keys), start=2):
        identifier = (r_keys["ano_eje"], r_keys["sec_ejec"])
        if identifier in seen_ids:
            errors.append(f"Clave duplicada ({identifier})")
        seen_ids.add(identifier)
        source = audit_map.get(identifier)
        if source is None:
            errors.append(f"ID fuera de los elegibles: {identifier}")
            continue
        if any(r_scaled[k] != r_keys[k] or source[k] != r_keys[k] for k in KEYS):
            errors.append(f"Metadatos de fila no coinciden: {identifier}")
        for f in features:
            try:
                x = float(r_scaled[f])
                y = float(r_matrix[f])
                raw = float(source[f])
                p = scaler["parameters"][f]
                reconstructed = (min(max(raw, p["p01"]), p["p99"]) - p["center_median"]) / p["scale"]
                if not all(math.isfinite(v) for v in (x, y, raw, reconstructed)):
                    raise ValueError("valor no finito")
                diff = max(abs(x-y), abs(x-reconstructed))
                max_dif = max(max_dif, diff)
                if diff > 1e-7 * max(1, abs(x), abs(y), abs(reconstructed)):
                    bad_numeric[f] += 1
            except (ValueError, TypeError, KeyError, ZeroDivisionError):
                bad_numeric[f] += 1
    if len(seen_ids) != len(eligible_audit):
        errors.append("No coinciden los IDs elegibles y la matriz")
    if bad_numeric:
        errors.append(f"Problemas numéricos por variable: {dict(bad_numeric)}")
    if any((not scaler["parameters"][f]["used"] or scaler["parameters"][f]["scale"] <= 0)
           for f in features):
        errors.append("Parámetros de escalamiento inválidos")
    # El conjunto de mancomunidades debe quedar en auditoría pero fuera de clustering.
    if any(r["tipo_entidad"] != "municipalidad" for r in eligible_audit):
        errors.append("Una entidad no municipal entró al modelo")
    result = {
        "status": "PASS" if not errors else "FAIL",
        "errors": errors,
        "perfiles_auditados": len(audit),
        "perfiles_modelo": len(matrix),
        "dimensiones_modelo": len(features),
        "features": features,
        "max_diferencia_transformacion": max_dif,
        "tipos_entidad_auditoria": dict(Counter(r["tipo_entidad"] for r in audit)),
        "notas": [
            "PASS verifica integridad de archivos de features, NO calidad de clústeres.",
            "No implica que Go ya haya cargado millones de filas concurrentemente.",
            "2026 no está incluido en este entrenamiento; debe reutilizar el transformador guardado.",
        ],
    }
    (out_dir / "validacion_features.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    text = ["# Validación de Feature Engineering", "",
            f"Estado: **{result['status']}**", "",
            f"Perfiles analizados: **{len(audit):,}**", "",
            f"Perfiles aptos: **{len(matrix):,}**", "",
            f"Variables: **{len(features)}**", "",
            "## Errores", ""] + ([f"- {e}" for e in errors] if errors else ["- Sin errores detectados"])
    (out_dir / "resumen_validacion_features.md").write_text("\n".join(text) + "\n", encoding="utf-8")
    return result


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output-dir", type=Path, default=ROOT / "data/processed/features_mef")
    p.add_argument("--source", type=Path, default=ROOT / "data/processed/preprocessing_mef/municipality_year_features.csv")
    p.add_argument("--preprocessing-report", type=Path, default=ROOT / "data/processed/preprocessing_mef/reporte_preprocesamiento.json")
    args = p.parse_args()
    result = validate(args.output_dir, args.source, args.preprocessing_report)
    print(f"ESTADO: {result['status']}")
    if result["errors"]:
        for error in result["errors"]:
            print(" -", error)
        raise SystemExit(1)
    print(f"Matriz: {result['perfiles_modelo']} x {result['dimensiones_modelo']}")


if __name__ == "__main__":
    main()
