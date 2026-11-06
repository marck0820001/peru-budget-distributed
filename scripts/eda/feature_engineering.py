#!/usr/bin/env python3
"""PC3: matriz de K-Means de perfiles municipales MEF 2024-2025.

Usa el CSV de `preprocess_data.py` y su reporte de validación FULL.
No modifica datos del origen; no concatena Seguimiento PI.
No entrena un modelo. No utiliza paquetes externos.

Ejecutar desde la raíz del repositorio:
    py scripts/eda/feature_engineering.py
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import statistics
import unicodedata
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
INPUT_COLUMNS = (
    "ano_eje", "sec_ejec", "departamento", "ejecutora_nombre",
    "n_lineas", "n_lineas_proyecto", "pia_soles", "pim_soles",
    "devengado_soles", "pim_proyectos_soles", "devengado_proyectos_soles",
    "concentracion_q4", "cv_devengado_mensual", "n_lineas_excluidas",
    "n_codigos_proyecto_faltantes", "advertencias",
)
# Todas son métricas calculadas al nivel ejecutora-año, nunca al nivel de línea.
BASE_FEATURES = (
    "tasa_ejecucion",
    "modificacion_log_pim_pia",
    "participacion_devengado_proyectos",
    "concentracion_q4",
    "cv_devengado_mensual",
    "log1p_pim",
)
KEYS = ("ano_eje", "sec_ejec", "departamento", "ejecutora_nombre", "tipo_entidad")


def norm_name(value: str) -> str:
    text = unicodedata.normalize("NFD", value.upper().strip())
    return "".join(ch for ch in text if unicodedata.category(ch) != "Mn")


def entity_type(name: str) -> str:
    normalized = norm_name(name)
    if "MANCOMUNIDAD" in normalized:
        return "mancomunidad"
    if normalized.startswith("MUNICIPALIDAD"):
        return "municipalidad"
    return "otra_ejecutora_local"


def finite_decimal(text: str, label: str) -> Decimal:
    try:
        v = Decimal((text or "").strip())
    except (InvalidOperation, ValueError):
        raise ValueError(f"{label}: valor no numérico: {text!r}") from None
    if not v.is_finite():
        raise ValueError(f"{label}: NaN/infinito: {text!r}")
    return v


def get_float(text: str, label: str) -> float:
    d = finite_decimal(text, label)
    try:
        value = float(d)
    except (OverflowError, ValueError):
        raise ValueError(f"{label}: fuera de rango") from None
    if not math.isfinite(value):
        raise ValueError(f"{label}: fuera de rango")
    return value


def get_int(text: str, label: str) -> int:
    value = finite_decimal(text, label)
    if value != value.to_integral_value():
        raise ValueError(f"{label}: no es entero")
    return int(value)


def percentile(sorted_values: list[float], quantile: float) -> float:
    """Percentil por interpolación lineal; exacto para la población de elegibles."""
    if not sorted_values:
        raise ValueError("No hay valores para calcular percentiles")
    if len(sorted_values) == 1:
        return sorted_values[0]
    x = (len(sorted_values) - 1) * quantile
    lo = math.floor(x)
    hi = math.ceil(x)
    return sorted_values[lo] * (hi - x) + sorted_values[hi] * (x - lo) if lo != hi else sorted_values[lo]


def calculate_features(row: dict[str, str]) -> dict[str, float]:
    pia = get_float(row["pia_soles"], "pia_soles")
    pim = get_float(row["pim_soles"], "pim_soles")
    dev = get_float(row["devengado_soles"], "devengado_soles")
    project_dev = get_float(row["devengado_proyectos_soles"], "devengado_proyectos_soles")
    if pia < 0 or pim <= 0 or dev <= 0:
        raise ValueError("montos de perfil no aptos para ratios; se auditará la exclusión")
    q4 = get_float(row["concentracion_q4"], "concentracion_q4")
    cv = get_float(row["cv_devengado_mensual"], "cv_devengado_mensual")
    # No se usa modificacion_sobre_pia: dividiría entre cero si PIA=0.
    # Escala simétrica logarítmica del cambio entre PIA y PIM (ambos en soles).
    result = {
        "tasa_ejecucion": dev / pim,
        "modificacion_log_pim_pia": math.log1p(pim) - math.log1p(pia),
        "participacion_devengado_proyectos": project_dev / dev,
        "concentracion_q4": q4,
        "cv_devengado_mensual": cv,
        "log1p_pim": math.log1p(pim),
    }
    if not all(math.isfinite(v) for v in result.values()):
        raise ValueError("al menos una característica no es finita")
    return result


def read_input(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        raise FileNotFoundError(f"Falta el CSV de perfiles: {path}")
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            raise ValueError("CSV sin encabezado")
        missing = set(INPUT_COLUMNS) - set(reader.fieldnames)
        if missing:
            raise ValueError(f"Faltan columnas del preprocesamiento: {sorted(missing)}")
        result = list(reader)
    if not result:
        raise ValueError("CSV sin perfiles")
    return result


def verify_preprocessing_report(path: Path, input_rows: list[dict[str, str]], allow_smoke: bool) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"Falta reporte del preprocesamiento: {path}")
    report = json.loads(path.read_text(encoding="utf-8-sig"))
    if report.get("mode") != "full" and not allow_smoke:
        raise ValueError("Se requiere reporte del preprocesamiento en modo FULL")
    integrity = report.get("integrity", {})
    if not integrity or not all(v is True for v in integrity.values()):
        raise ValueError("El preprocesamiento no pasó todas las conciliaciones")
    expected = report.get("totals", {}).get("municipality_year_profiles")
    if expected is None or int(expected) != len(input_rows):
        raise ValueError(f"Perfiles CSV={len(input_rows)} no coinciden con el reporte={expected}")
    total_lines = sum(get_int(r["n_lineas"], "n_lineas") for r in input_rows)
    expected_lines = report.get("totals", {}).get("local_accepted")
    if expected_lines is None or total_lines != int(expected_lines):
        raise ValueError(f"Líneas agregadas={total_lines} no coinciden con aceptadas={expected_lines}")
    return report


def prepare(rows: list[dict[str, str]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], Counter]:
    audit = []
    eligible = []
    reason_counter = Counter()
    seen = set()
    for line_no, row in enumerate(rows, 2):
        ano, code = row["ano_eje"].strip(), row["sec_ejec"].strip()
        key = (ano, code)
        if not code or key in seen:
            raise ValueError(f"Código vacío o duplicado en línea {line_no}: {key}")
        seen.add(key)
        year = get_int(ano, "ano_eje")
        if year not in (2024, 2025):
            raise ValueError(f"Año inesperado: {year}")
        kind = entity_type(row["ejecutora_nombre"])
        reasons: list[str] = []
        warnings: list[str] = []
        if kind != "municipalidad":
            reasons.append("tipo_entidad_no_municipalidad")
        if not row["departamento"].strip():
            reasons.append("departamento_vacio")
        if not row["ejecutora_nombre"].strip():
            reasons.append("nombre_vacio")
        if get_int(row["n_lineas_excluidas"], "n_lineas_excluidas") > 0:
            reasons.append("agregado_incompleto")
        prior_warnings = [s.strip() for s in row.get("advertencias", "").split(";") if s.strip()]
        if "metadatos_inconsistentes" in prior_warnings:
            reasons.append("metadatos_inconsistentes")
        warnings.extend(prior_warnings)
        if get_int(row["n_codigos_proyecto_faltantes"], "n_codigos_proyecto_faltantes") > 0:
            warnings.append("proyecto_sin_codigo_incluido_en_agregado")
        try:
            # Se computan indicadores solo si son matemáticamente válidos.
            features = calculate_features(row)
        except ValueError as exc:
            features = {}
            reasons.append("indicadores_no_definidos")
            warnings.append(str(exc))
        if features:
            if not 0 <= features["participacion_devengado_proyectos"] <= 1:
                warnings.append("participacion_proyectos_fuera_0_1_por_ajustes")
            if not 0 <= features["concentracion_q4"] <= 1:
                warnings.append("concentracion_q4_fuera_0_1_por_ajustes")
            if features["tasa_ejecucion"] > 1:
                warnings.append("tasa_ejecucion_superior_a_1")
        meta = {
            "ano_eje": str(year), "sec_ejec": code,
            "departamento": row["departamento"].strip(),
            "ejecutora_nombre": row["ejecutora_nombre"].strip(),
            "tipo_entidad": kind,
        }
        reasons = sorted(set(reasons))
        record = dict(meta)
        record.update({"eligible": "1" if not reasons else "0",
                       "exclusion_reasons": ";".join(reasons),
                       "warnings": ";".join(sorted(set(warnings))),
                       "n_lineas": row["n_lineas"],
                       "pia_soles": row["pia_soles"], "pim_soles": row["pim_soles"],
                       "devengado_soles": row["devengado_soles"]})
        record.update({f: features.get(f, "") for f in BASE_FEATURES})
        audit.append(record)
        if reasons:
            reason_counter.update(reasons)
        else:
            eligible.append(dict(meta, **features))
    audit.sort(key=lambda r: (r["ano_eje"], r["sec_ejec"]))
    eligible.sort(key=lambda r: (r["ano_eje"], r["sec_ejec"]))
    if len(eligible) < 10:
        raise ValueError("Menos de 10 perfiles elegibles: revisar criterios antes del entrenamiento")
    return audit, eligible, reason_counter


def fit_transform(eligible: list[dict[str, Any]], low_quantile: float = 0.01,
                  high_quantile: float = 0.99) -> tuple[list[dict[str, str]], dict[str, Any], Counter]:
    if not (0 <= low_quantile < high_quantile <= 1):
        raise ValueError("Cuantiles de winsorización inválidos")
    parameter: dict[str, Any] = {}
    selected = []
    clipped_counts = Counter()
    for feature in BASE_FEATURES:
        vals = sorted(float(r[feature]) for r in eligible)
        low = percentile(vals, low_quantile)
        high = percentile(vals, high_quantile)
        clipped = sorted(min(max(v, low), high) for v in vals)
        median = percentile(clipped, 0.5)
        q25 = percentile(clipped, 0.25)
        q75 = percentile(clipped, 0.75)
        iqr = q75 - q25
        # Evitar dividir entre cero sin esconder las dimensiones constantes.
        if high - low < 1e-12:
            parameter[feature] = {"used": False, "reason": "sin_variacion", "p01": low, "p99": high}
            continue
        if iqr < 1e-12:
            # Dejar explícito que la desviación estándar reemplaza al IQR.
            scale = statistics.pstdev(clipped)
            scaling_method = "std_fallback"
        else:
            scale = iqr
            scaling_method = "iqr"
        if scale < 1e-12:
            parameter[feature] = {"used": False, "reason": "escala_cero", "p01": low, "p99": high}
            continue
        parameter[feature] = {
            "used": True, "p01": low, "p99": high,
            "center_median": median, "scale": scale, "scale_method": scaling_method,
            "clipped_below": sum(v < low for v in vals),
            "clipped_above": sum(v > high for v in vals),
        }
        clipped_counts.update({f"{feature}_inferior": parameter[feature]["clipped_below"],
                               f"{feature}_superior": parameter[feature]["clipped_above"]})
        selected.append(feature)
    if len(selected) < 2:
        raise ValueError("Menos de 2 features con variabilidad; K-Means no es viable")
    output: list[dict[str, str]] = []
    for row in eligible:
        transformed = {k: str(row[k]) for k in KEYS}
        for feature in selected:
            p = parameter[feature]
            winsor = min(max(float(row[feature]), p["p01"]), p["p99"])
            scaled = (winsor - p["center_median"]) / p["scale"]
            if not math.isfinite(scaled):
                raise ValueError(f"Feature no finita luego del escalamiento: {feature}")
            transformed[feature] = format(scaled, ".12g")
        output.append(transformed)
    return output, {"features": selected, "parameters": parameter,
                    "method": "winsor_p01_p99_then_robust_median_iqr"}, clipped_counts


def write_csv(path: Path, cols: list[str], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            block = f.read(1024 * 1024)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def run(input_path: Path, preprocessing_report: Path, out_dir: Path,
        allow_smoke: bool = False) -> dict[str, Any]:
    rows = read_input(input_path)
    parent_report = verify_preprocessing_report(preprocessing_report, rows, allow_smoke)
    audit, eligible, reasons = prepare(rows)
    scaled, scaler, clipping = fit_transform(eligible)
    out_dir.mkdir(parents=True, exist_ok=True)
    audit_columns = list(KEYS) + ["eligible", "exclusion_reasons", "warnings", "n_lineas",
                                   "pia_soles", "pim_soles", "devengado_soles"] + list(BASE_FEATURES)
    write_csv(out_dir / "municipality_features_audit.csv", audit_columns, audit)
    write_csv(out_dir / "municipality_features_scaled.csv", list(KEYS) + scaler["features"], scaled)
    write_csv(out_dir / "kmeans_matrix.csv", scaler["features"], scaled)
    write_csv(out_dir / "kmeans_keys.csv", list(KEYS), scaled)
    report = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "source_csv": input_path.name,
        "source_csv_sha256": sha256_file(input_path),
        "preprocessing_mode": parent_report["mode"],
        "input_profiles": len(rows), "eligible_profiles": len(eligible),
        "excluded_profiles": len(rows)-len(eligible),
        "excluded_by_reason": dict(reasons),
        "entity_type_counts": dict(Counter(r["tipo_entidad"] for r in audit)),
        "year_counts_eligible": dict(Counter(r["ano_eje"] for r in scaled)),
        "selected_features": scaler["features"], "winsorized_counts": dict(clipping),
        "matrix_rows": len(scaled), "matrix_columns": len(scaler["features"]),
        "notes": [
            "PIA=0 no es causal de exclusión; se usa cambio logarítmico sin división por PIA.",
            "Se excluyen mancomunidades de clustering municipal, pero se preservan en auditoría.",
            "Los ceros y los ajustes válidos se conservan en la base de origen.",
            "Winsorización y escalamiento ajustados sobre perfiles elegibles 2024-2025 solamente.",
            "Escalamiento no es clustering; los >3.6M registros son ETL, no filas de esta matriz.",
            "Seguimiento PI no se ha integrado; la presencia de valores atípicos no implica irregularidad.",
        ],
    }
    (out_dir / "feature_transformer.json").write_text(
        json.dumps(scaler, indent=2, ensure_ascii=False, allow_nan=False), encoding="utf-8")
    (out_dir / "reporte_features.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False), encoding="utf-8")
    md = ["# Feature Engineering — MEF", "",
          f"Perfiles originales: **{len(rows):,}**",
          f"Perfiles aptos para clustering municipal: **{len(eligible):,}**",
          f"Perfiles excluidos (preservados en auditoría): **{len(rows)-len(eligible):,}**", "",
          "## Variables seleccionadas", "",
          *(f"- `{f}`" for f in scaler["features"]), "",
          "## Exclusiones", "",
          *(f"- `{k}`: {v}" for k, v in reasons.most_common()), "",
          "## Precauciones", "",
          "- No es el algoritmo K-Means: esta matriz requiere entrenamiento Go posterior.",
          "- Las tasas y proporciones pueden exceder 0-1 por ajustes presupuestarios.",
          "- Valores extremos se winsorizan 1%-99% solo en matriz; originales quedan en auditoría.",
          "- Las mancomunidades no son municipalidades distritales/provinciales convencionales.",
          "- K-Means municipal opera en miles de perfiles, no en millones de líneas presupuestarias.", ""]
    (out_dir / "resumen_features.md").write_text("\n".join(md), encoding="utf-8")
    return report


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--input", type=Path,
                   default=ROOT / "data/processed/preprocessing_mef/municipality_year_features.csv")
    p.add_argument("--preprocessing-report", type=Path,
                   default=ROOT / "data/processed/preprocessing_mef/reporte_preprocesamiento.json")
    p.add_argument("--output-dir", type=Path,
                   default=ROOT / "data/processed/features_mef")
    p.add_argument("--allow-smoke", action="store_true", help="Solo para pruebas con muestras")
    args = p.parse_args()
    result = run(args.input, args.preprocessing_report, args.output_dir, args.allow_smoke)
    print(f"PERFILES: {result['input_profiles']}; ELEGIBLES: {result['eligible_profiles']}; "
          f"EXCLUIDOS: {result['excluded_profiles']}")
    print(f"FEATURES: {', '.join(result['selected_features'])}")
    print(f"Resultados en: {args.output_dir}")


if __name__ == "__main__":
    main()
