#!/usr/bin/env python3
"""Validacion independiente de salidas del preprocesamiento MEF.

Uso: py scripts/eda/validate_data.py --require-full \
      --compare-eda data/processed/eda_estadistico/inventario_eda.csv \
      --check-lines
"""
from __future__ import annotations

import argparse
import csv
import gzip
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from preprocess_data import ROOT, MONTHS, parse_cents


def load_rows(path: Path):
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        yield from csv.DictReader(stream)


def as_cents(row: dict, key: str) -> int:
    value, err = parse_cents(row[key])
    if err:
        raise ValueError(f"{key} inválido: {row.get(key)!r} ({err})")
    assert value is not None
    return value


def validate(out_dir: Path, require_full: bool = False, compare_eda: Path | None = None,
             check_lines: bool = False) -> dict:
    report = json.loads((out_dir / "reporte_preprocesamiento.json").read_text(encoding="utf-8"))
    totals = report["totals"]
    findings: list[dict] = []

    def check(name: str, condition: bool, details: str = "", severity: str = "error") -> None:
        findings.append({"check": name, "passed": bool(condition),
                         "severity": severity, "details": details})

    check("balance_filas_origen", report["integrity"]["row_balance"])
    check("balance_aggregados", report["integrity"]["totals_equal_aggregates"])
    check("balance_proyectos", report["integrity"]["projects_equal_with_missing_key_adjustment"])
    if report["totals"]["local_rejected"]:
        check("filas_con_incidencias_pendientes", False,
              f"{report['totals']['local_rejected']} filas municipales excluidas del agregado",
              severity="warning")
    if require_full:
        check("modo_completo", report["mode"] == "full",
              "--require-full impide validar muestras como si fueran EDA completo")

    municipal_keys = set()
    municipal_rows = 0
    municipal_pia = municipal_pim = municipal_dev = 0
    municipal_project_pim = municipal_project_dev = 0
    candidate_rows = 0
    warning_counts = Counter()
    for r in load_rows(out_dir / "municipality_year_features.csv"):
        municipal_rows += 1
        key = (r["ano_eje"], r["sec_ejec"])
        check("clave_municipal_unica", key not in municipal_keys,
              f"clave {key}") if key in municipal_keys else None
        municipal_keys.add(key)
        municipal_pia += as_cents(r, "pia_soles")
        municipal_pim += as_cents(r, "pim_soles")
        municipal_dev += as_cents(r, "devengado_soles")
        municipal_project_pim += as_cents(r, "pim_proyectos_soles")
        municipal_project_dev += as_cents(r, "devengado_proyectos_soles")
        candidate_rows += r["apto_candidato"] == "1"
        for warning in filter(None, r["advertencias"].split(";")):
            warning_counts[warning] += 1
        for key_name in ("tasa_ejecucion", "modificacion_sobre_pia",
                         "participacion_devengado_proyectos", "concentracion_q4",
                         "cv_devengado_mensual", "log1p_pim"):
            if r[key_name]:
                try:
                    from math import isfinite
                    if not isfinite(float(r[key_name])):
                        check("features_finitas", False, f"{key}: {key_name} no finito")
                except (ValueError, OverflowError):
                    check("features_numericas", False, f"{key}: {key_name} inválido")
    if not candidate_rows:
        check("sin_perfiles_candidatos", False,
              "No hay ejecutoras con indicadores completos bajo el criterio conservador",
              severity="warning")
    check("cantidad_perfiles_municipales",
          municipal_rows == totals["municipality_year_profiles"])
    check("suma_municipal_pia", municipal_pia == as_cents(totals, "sum_local_pia_soles"))
    check("suma_municipal_pim", municipal_pim == as_cents(totals, "sum_local_pim_soles"))
    check("suma_municipal_devengado", municipal_dev == as_cents(totals, "sum_local_dev_soles"))
    check("suma_municipal_pim_proyectos",
          municipal_project_pim == as_cents(totals, "sum_local_project_pim_soles"))
    check("suma_municipal_devengado_proyectos",
          municipal_project_dev == as_cents(totals, "sum_local_project_dev_soles"))

    project_count = 0
    projects_keys = set()
    project_pim = project_dev = 0
    ambiguous_names = 0
    for r in load_rows(out_dir / "project_features.csv"):
        project_count += 1
        key = (r["ano_eje"], r["sec_ejec"], r["producto_proyecto"])
        if key in projects_keys:
            check("clave_proyecto_unica", False, f"{key}")
        projects_keys.add(key)
        project_pim += as_cents(r, "pim_soles")
        project_dev += as_cents(r, "devengado_soles")
        ambiguous_names += int(r["nombres_distintos"]) > 1
    check("cantidad_perfiles_proyecto", project_count == totals["project_executor_year_profiles"])
    check("proyectos_pim_mas_codigos_vacios", project_pim +
          as_cents(totals, "sum_projects_missing_code_pim_soles") == municipal_project_pim)
    check("proyectos_dev_mas_codigos_vacios", project_dev +
          as_cents(totals, "sum_projects_missing_code_dev_soles") == municipal_project_dev)

    incident_count = sum(1 for _ in load_rows(out_dir / "incidencias_preprocesamiento.csv"))
    check("filas_rechazadas_identificadas", incident_count ==
          totals["local_rejected"] + totals["malformed_rows"])

    if compare_eda:
        expected_by_file = {}
        for r in load_rows(compare_eda):
            if r.get("archivo", "").lower().endswith(".csv") and "gasto" in r.get("dataset", ""):
                expected_by_file[r["archivo"]] = int(r["filas_gobierno_local"])
        for src in report["sources"]:
            if src["file"] in expected_by_file:
                check(f"volumen_eda_{src['expected_year']}",
                      src["local_rows"] == expected_by_file[src["file"]],
                      f"EDA={expected_by_file[src['file']]}, procesado={src['local_rows']}")
            else:
                check(f"fuente_en_inventario_eda_{src['expected_year']}", False,
                      f"Archivo no reconocido: {src['file']}")

    lines_checked = 0
    line_pia = line_pim = line_dev = 0
    if check_lines:
        lines_path = out_dir / "budget_lines_clean.csv.gz"
        check("lineas_exportadas", lines_path.exists(), str(lines_path))
        if lines_path.exists():
            with gzip.open(lines_path, "rt", encoding="utf-8", newline="") as s:
                for r in csv.DictReader(s):
                    lines_checked += 1
                    pia = as_cents(r, "monto_pia")
                    pim = as_cents(r, "monto_pim")
                    dev = as_cents(r, "monto_devengado_anual")
                    line_pia += pia
                    line_pim += pim
                    line_dev += dev
                    month_sum = sum(as_cents(r, "devengado_" + m.lower()) for m in MONTHS)
                    if dev != month_sum:
                        check("lineas_mes_anual", False,
                              f"linea exportada {lines_checked}: no concilia")
            check("cantidad_lineas_exportadas", lines_checked == totals["local_accepted"])
            check("pia_lineas_vs_agregado", line_pia == municipal_pia)
            check("pim_lineas_vs_agregado", line_pim == municipal_pim)
            check("dev_lineas_vs_agregado", line_dev == municipal_dev)

    errors = [f for f in findings if not f["passed"] and f["severity"] == "error"]
    warnings = [f for f in findings if not f["passed"] and f["severity"] == "warning"]
    output = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "status": "PASS" if not errors else "FAIL",
        "mode": report["mode"],
        "counts": {"municipality_profiles": municipal_rows,
                   "project_executor_year_profiles": project_count,
                   "candidate_municipality_profiles": candidate_rows,
                   "reported_rows_accepted": totals["local_accepted"],
                   "incident_rows": incident_count,
                   "project_keys_multiple_names": ambiguous_names,
                   "line_rows_checked": lines_checked},
        "warning_counts": dict(warning_counts),
        "checks": findings,
        "errors": errors,
        "warnings": warnings,
        "limitations": [
            "No se han identificado/eliminado duplicados exactos entre filas originales.",
            "No valida la veracidad administrativa de los montos publicados por MEF.",
            "No implica calidad o separacion de clusters K-Means.",
            "No prueba equivalencia de Gasto Devengado con Seguimiento PI.",
        ],
    }
    (out_dir / "validacion_preprocesamiento.json").write_text(
        json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = ["# Validacion de preprocesamiento MEF", "",
             f"Estado: **{output['status']}**. Modo: **{report['mode']}**.", "",
             "## Estadisticas", "",
             *(f"- {k}: {v:,}" for k, v in output["counts"].items()), "",
             "## Reglas comprobadas", "",
             *(f"- {'OK' if c['passed'] else 'ERROR'} — {c['check']}"
               for c in findings), "",
             "## Limites", "",
             *(f"- {x}" for x in output["limitations"]), ""]
    (out_dir / "resumen_validacion.md").write_text("\n".join(lines), encoding="utf-8")
    return output


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--out-dir", type=Path, default=ROOT / "data" / "processed" / "preprocessing_mef")
    p.add_argument("--compare-eda", type=Path, default=None)
    p.add_argument("--check-lines", action="store_true")
    p.add_argument("--require-full", action="store_true")
    args = p.parse_args()
    report = validate(args.out_dir, args.require_full, args.compare_eda, args.check_lines)
    print(f"Validación {report['status']}: {args.out_dir / 'resumen_validacion.md'}")
    if report["errors"]:
        for error in report["errors"][:15]:
            print(f"ERROR {error['check']}: {error['details']}")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
