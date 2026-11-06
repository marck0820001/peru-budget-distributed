#!/usr/bin/env python3
"""Preprocesamiento auditable de Gasto Devengado MEF (2024-2025).

CLI (desde la raiz del repositorio):
    py scripts/eda/preprocess_data.py --mode smoke
    py scripts/eda/preprocess_data.py --mode full --write-lines
    py scripts/eda/preprocess_data.py --mode full --data-dir D:/MEF

No fusiona los snapshots de Seguimiento PI ni entrena modelos.
No deduplica filas (una combinacion proyecto-ejecutora repetida NO implica duplicado).
El modo smoke encuentra algunas filas locales incluso si el CSV comienza con R.
Las cifras monetarias se interpretan en centimos sin redondeo silencioso.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import json
import math
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, TextIO

ROOT = Path(__file__).resolve().parents[2]
MONTHS = (
    "ENERO", "FEBRERO", "MARZO", "ABRIL", "MAYO", "JUNIO",
    "JULIO", "AGOSTO", "SEPTIEMBRE", "OCTUBRE", "NOVIEMBRE", "DICIEMBRE",
)
MONTH_COLS = tuple(f"MONTO_DEVENGADO_{m}" for m in MONTHS)
MONEY_COLS = ("MONTO_PIA", "MONTO_PIM", "MONTO_DEVENGADO_ANUAL", *MONTH_COLS)
REQUIRED_COLS = (
    "ANO_EJE", "NIVEL_GOBIERNO", "SEC_EJEC", "EJECUTORA_NOMBRE",
    "DEPARTAMENTO_EJECUTORA_NOMBRE", "TIPO_ACT_PROY", "PRODUCTO_PROYECTO",
    "PRODUCTO_PROYECTO_NOMBRE", *MONEY_COLS,
)
NULL_TOKENS = {"", "NULL", "N/A", "NA", "NAN", "NONE", "S/D", "SIN DATO"}
OUTPUT_LINE_COLS = (
    "source_file", "source_row", "ano_eje", "sec_ejec", "ejecutora_nombre",
    "departamento", "tipo_act_proy", "producto_proyecto", "producto_proyecto_nombre",
    "monto_pia", "monto_pim", "monto_devengado_anual",
    *(f"devengado_{m.lower()}" for m in MONTHS),
)
FEATURE_COLS = (
    "ano_eje", "sec_ejec", "departamento", "ejecutora_nombre", "n_lineas",
    "n_lineas_proyecto", "pia_soles", "pim_soles", "devengado_soles",
    "pim_proyectos_soles", "devengado_proyectos_soles",
    "tasa_ejecucion", "modificacion_sobre_pia",
    "participacion_devengado_proyectos", "concentracion_q4",
    "cv_devengado_mensual", "log1p_pim", "n_ajustes_mensuales_negativos",
    "n_montos_negativos", "n_lineas_excluidas", "n_codigos_proyecto_faltantes", "apto_candidato",
    "advertencias",
)
PROJECT_COLS = (
    "ano_eje", "sec_ejec", "producto_proyecto", "producto_proyecto_nombre",
    "departamento", "ejecutora_nombre", "lineas_presupuestarias",
    "pia_soles", "pim_soles", "devengado_soles", "nombres_distintos",
)


def find_gasto_files(data_dir: Path) -> list[tuple[int, Path]]:
    if not data_dir.is_dir():
        raise FileNotFoundError(f"No existe carpeta: {data_dir}")
    output = []
    for year in (2024, 2025):
        matches = sorted(data_dir.glob(f"{year}-Gasto-Devengado*.csv"))
        if len(matches) != 1:
            raise FileNotFoundError(
                f"Se esperaba exactamente 1 Gasto Devengado de {year} en {data_dir}; "
                f"encontrados: {[m.name for m in matches]}"
            )
        output.append((year, matches[0]))
    return output


def parse_cents(value: str) -> tuple[int | None, str | None]:
    """Devuelve (centimos, error). No convierte vacios en ceros ni redondea."""
    s = (value or "").strip().replace("\u00a0", "").replace(" ", "")
    if s.upper() in NULL_TOKENS:
        return None, "vacio"
    if s.startswith("S/"):
        s = s[2:]
    if s.startswith("$"):
        s = s[1:]
    # Los CSV revisados vienen con coma de campo y punto decimal.
    # No aceptar separador decimal ambiguo sin confirmacion.
    if "," in s:
        return None, "formato_ambiguo"
    if not re.fullmatch(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?", s):
        return None, "no_numerico"
    try:
        d = Decimal(s)
        if not d.is_finite():
            return None, "no_finito"
        cents = d * 100
        if cents != cents.to_integral_value():
            return None, "mas_de_dos_decimales"
        return int(cents), None
    except (InvalidOperation, ValueError, OverflowError):
        return None, "no_numerico"


def soles(cents: int) -> str:
    symbol = "-" if cents < 0 else ""
    n = abs(cents)
    return f"{symbol}{n // 100}.{n % 100:02d}"


def ratio(a: int, b: int) -> str:
    return f"{a / b:.8f}" if b > 0 else ""


def empty_bucket(year: int, ent: str, dept: str, name: str) -> dict[str, Any]:
    return {
        "year": year, "sec_ejec": ent, "department": dept, "name": name,
        "rows": 0, "project_rows": 0,
        "pia": 0, "pim": 0, "dev": 0,
        "project_pim": 0, "project_dev": 0,
        "months": [0] * 12, "neg_months": 0, "neg_amounts": 0,
        "missing_project_codes": 0, "inconsistent_metadata": False,
    }


def safe_csv_writer(path: Path, fieldnames: tuple[str, ...]) -> tuple[TextIO, csv.DictWriter]:
    path.parent.mkdir(parents=True, exist_ok=True)
    stream = path.open("w", encoding="utf-8-sig", newline="")
    writer = csv.DictWriter(stream, fieldnames=fieldnames)
    writer.writeheader()
    return stream, writer


def process(data_dir: Path, out_dir: Path, mode: str = "full", smoke_local: int = 500,
            write_lines: bool = False, progress: int = 250000) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    files = find_gasto_files(data_dir)
    municipality: dict[tuple[int, str], dict[str, Any]] = {}
    projects: dict[tuple[int, str, str], dict[str, Any]] = {}
    report: dict[str, Any] = {
        "run_timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "mode": mode, "not_full_dataset": mode != "full",
        "deduplicacion_exacta": "NO_REALIZADA; no se eliminan filas por repetir codigo de proyecto",
        "fuentes": [], "totals": {},
        "rules": [
            "Gobiernos locales: NIVEL_GOBIERNO=M",
            "No se unifican los snapshots de Seguimiento PI",
            "Montos convertidos exactamente a centimos; no se redondea",
            "Lineas con montos invalidos o discrepancia mensual se excluyen de agregados y se auditan",
            "Los ceros y montos negativos validos se conservan",
            "Indicadores son candidatos, SIN imputacion ni escalamiento",
        ],
    }
    overall = Counter()
    rejected_by_municipality = Counter()
    source_stats = []
    reject_path = out_dir / "incidencias_preprocesamiento.csv"
    reject_stream, reject_writer = safe_csv_writer(
        reject_path, ("source_file", "source_row", "ano_eje", "sec_ejec", "reason")
    )
    line_stream = None
    line_writer = None
    if write_lines:
        line_path = out_dir / "budget_lines_clean.csv.gz"
        line_stream = gzip.open(line_path, "wt", encoding="utf-8", newline="", compresslevel=5)
        line_writer = csv.DictWriter(line_stream, fieldnames=OUTPUT_LINE_COLS)
        line_writer.writeheader()
    try:
        for expected_year, path in files:
            stats = Counter()
            with path.open("r", encoding="utf-8-sig", errors="strict", newline="") as stream:
                reader = csv.reader(stream, delimiter=",")
                try:
                    headers = [h.lstrip("\ufeff").strip() for h in next(reader)]
                except StopIteration as exc:
                    raise ValueError(f"CSV vacío: {path}") from exc
                if len(headers) != len(set(headers)):
                    raise ValueError(f"Columnas duplicadas en {path.name}")
                idx = {h: i for i, h in enumerate(headers)}
                missing = sorted(set(REQUIRED_COLS) - idx.keys())
                if missing:
                    raise ValueError(f"Faltan columnas en {path.name}: {missing}")

                for i, row in enumerate(reader, start=2):
                    stats["rows_read"] += 1
                    if len(row) != len(headers):
                        stats["malformed_rows"] += 1
                        reject_writer.writerow({"source_file": path.name, "source_row": i,
                                                "reason": f"columnas_{len(row)}_esperadas_{len(headers)}"})
                        continue
                    get = lambda key: row[idx[key]].strip()
                    if get("NIVEL_GOBIERNO").upper() != "M":
                        stats["non_local_rows"] += 1
                        continue
                    stats["local_rows"] += 1
                    year_text = get("ANO_EJE")
                    ent = get("SEC_EJEC")
                    reason = None
                    if year_text != str(expected_year):
                        reason = "ano_eje_no_coincide_archivo"
                    elif not ent:
                        reason = "sec_ejec_vacio"
                    values = {}
                    errors = Counter()
                    if reason is None:
                        for col in MONEY_COLS:
                            parsed, err = parse_cents(get(col))
                            if err:
                                errors[f"{col}:{err}"] += 1
                            values[col] = parsed
                        if errors:
                            reason = "montos_invalidos: " + ";".join(errors)
                            stats["local_rows_invalid_monetary"] += 1
                            for code, num in errors.items():
                                stats[f"money_error::{code}"] += num
                        elif sum(values[c] for c in MONTH_COLS) != values["MONTO_DEVENGADO_ANUAL"]:
                            reason = "suma_meses_difiere_devengado_anual"
                            stats["local_monthly_mismatches"] += 1
                    if reason:
                        stats["local_rejected"] += 1
                        if year_text == str(expected_year) and ent:
                            rejected_by_municipality[(expected_year, ent)] += 1
                        reject_writer.writerow({"source_file": path.name, "source_row": i,
                                                "ano_eje": year_text, "sec_ejec": ent,
                                                "reason": reason})
                        continue
                    pia, pim, dev = (values["MONTO_PIA"], values["MONTO_PIM"],
                                     values["MONTO_DEVENGADO_ANUAL"])
                    months = [values[c] for c in MONTH_COLS]
                    atype = get("TIPO_ACT_PROY").upper()
                    is_project = atype == "PROYECTO"
                    dept = get("DEPARTAMENTO_EJECUTORA_NOMBRE")
                    name = get("EJECUTORA_NOMBRE")
                    project_code = get("PRODUCTO_PROYECTO")
                    project_name = get("PRODUCTO_PROYECTO_NOMBRE")
                    key = (expected_year, ent)
                    if key not in municipality:
                        municipality[key] = empty_bucket(expected_year, ent, dept, name)
                    m = municipality[key]
                    if m["department"] != dept or m["name"] != name:
                        m["inconsistent_metadata"] = True
                        stats["local_rows_inconsistent_names"] += 1
                    m["rows"] += 1
                    m["project_rows"] += int(is_project)
                    m["pia"] += pia
                    m["pim"] += pim
                    m["dev"] += dev
                    m["neg_amounts"] += int(pia < 0) + int(pim < 0) + int(dev < 0)
                    m["neg_months"] += sum(n < 0 for n in months)
                    for k, val in enumerate(months):
                        m["months"][k] += val
                    stats["local_accepted"] += 1
                    stats["local_pia_cents"] += pia
                    stats["local_pim_cents"] += pim
                    stats["local_dev_cents"] += dev
                    if is_project:
                        m["project_pim"] += pim
                        m["project_dev"] += dev
                        stats["local_project_rows"] += 1
                        stats["local_project_pim_cents"] += pim
                        stats["local_project_dev_cents"] += dev
                        if not project_code:
                            m["missing_project_codes"] += 1
                            stats["local_project_rows_missing_code"] += 1
                            stats["local_project_pim_missing_code_cents"] += pim
                            stats["local_project_dev_missing_code_cents"] += dev
                        else:
                            pkey = (expected_year, ent, project_code)
                            if pkey not in projects:
                                projects[pkey] = {
                                    "year": expected_year, "ent": ent, "code": project_code,
                                    "names": set(), "dept": dept, "ent_name": name,
                                    "rows": 0, "pia": 0, "pim": 0, "dev": 0,
                                }
                            p = projects[pkey]
                            if project_name:
                                p["names"].add(project_name)
                            p["rows"] += 1
                            p["pia"] += pia
                            p["pim"] += pim
                            p["dev"] += dev
                    if line_writer is not None:
                        output_row = {
                            "source_file": path.name, "source_row": i, "ano_eje": expected_year,
                            "sec_ejec": ent, "ejecutora_nombre": name, "departamento": dept,
                            "tipo_act_proy": atype, "producto_proyecto": project_code,
                            "producto_proyecto_nombre": project_name,
                            "monto_pia": soles(pia), "monto_pim": soles(pim),
                            "monto_devengado_anual": soles(dev),
                        }
                        output_row.update({f"devengado_{mon.lower()}": soles(val)
                                           for mon, val in zip(MONTHS, months)})
                        line_writer.writerow(output_row)
                    if progress and stats["rows_read"] % progress == 0:
                        print(f"[{path.name}] {stats['rows_read']:,} filas; "
                              f"{stats['local_accepted']:,} municipales aceptadas", flush=True)
                    if mode == "smoke" and stats["local_accepted"] >= smoke_local:
                        break
            # note: smoke mode may read more rows if all early rows are non-local.
            meta = {"file": path.name, "expected_year": expected_year,
                    "size_bytes": path.stat().st_size, **dict(stats)}
            source_stats.append(meta)
            overall.update(stats)
            print(f"Finalizado {path.name}: "
                  f"locales={stats['local_rows']:,}, aceptadas={stats['local_accepted']:,}",
                  flush=True)
    finally:
        reject_stream.close()
        if line_stream:
            line_stream.close()

    if not write_lines and (out_dir / "budget_lines_clean.csv.gz").exists():
        (out_dir / "budget_lines_clean.csv.gz").unlink()
    feat_path = out_dir / "municipality_year_features.csv"
    with feat_path.open("w", encoding="utf-8-sig", newline="") as stream:
        w = csv.DictWriter(stream, fieldnames=FEATURE_COLS)
        w.writeheader()
        for key in sorted(municipality):
            m = municipality[key]
            annual = m["dev"]
            mean = annual / 12.0
            cv = ""
            if mean > 0:
                sd = math.sqrt(sum((v-mean)**2 for v in m["months"]) / 12.0)
                cv = f"{sd/mean:.8f}"
            pim = m["pim"]
            pia = m["pia"]
            warnings = []
            if m["inconsistent_metadata"]:
                warnings.append("metadatos_inconsistentes")
            if pia <= 0:
                warnings.append("pia_no_positivo")
            if pim <= 0:
                warnings.append("pim_no_positivo")
            if annual <= 0:
                warnings.append("devengado_no_positivo")
            if m["missing_project_codes"]:
                warnings.append("proyecto_sin_codigo")
            if rejected_by_municipality[key]:
                warnings.append("agregado_incompleto_por_filas_excluidas")
            if m["neg_amounts"]:
                warnings.append("montos_negativos")
            if m["neg_months"]:
                warnings.append("ajustes_mensuales_negativos")
            w.writerow({
                "ano_eje": m["year"], "sec_ejec": m["sec_ejec"],
                "departamento": m["department"], "ejecutora_nombre": m["name"],
                "n_lineas": m["rows"], "n_lineas_proyecto": m["project_rows"],
                "pia_soles": soles(pia), "pim_soles": soles(pim),
                "devengado_soles": soles(annual),
                "pim_proyectos_soles": soles(m["project_pim"]),
                "devengado_proyectos_soles": soles(m["project_dev"]),
                "tasa_ejecucion": ratio(annual, pim),
                "modificacion_sobre_pia": ratio(pim-pia, pia),
                "participacion_devengado_proyectos": ratio(m["project_dev"], annual),
                "concentracion_q4": ratio(sum(m["months"][9:]), annual),
                "cv_devengado_mensual": cv,
                "log1p_pim": f"{math.log1p(pim / 100):.8f}" if pim >= 0 else "",
                "n_ajustes_mensuales_negativos": m["neg_months"],
                "n_montos_negativos": m["neg_amounts"],
                "n_lineas_excluidas": rejected_by_municipality[key],
                "n_codigos_proyecto_faltantes": m["missing_project_codes"],
                "apto_candidato": int(pim > 0 and pia > 0 and annual > 0 and
                                        not m["inconsistent_metadata"] and
                                        not m["missing_project_codes"] and
                                        not rejected_by_municipality[key]),
                "advertencias": ";".join(warnings),
            })

    proj_path = out_dir / "project_features.csv"
    with proj_path.open("w", encoding="utf-8-sig", newline="") as stream:
        w = csv.DictWriter(stream, fieldnames=PROJECT_COLS)
        w.writeheader()
        for key in sorted(projects):
            p = projects[key]
            names = sorted(p["names"])
            w.writerow({
                "ano_eje": p["year"], "sec_ejec": p["ent"],
                "producto_proyecto": p["code"],
                "producto_proyecto_nombre": names[0] if names else "",
                "departamento": p["dept"], "ejecutora_nombre": p["ent_name"],
                "lineas_presupuestarias": p["rows"],
                "pia_soles": soles(p["pia"]), "pim_soles": soles(p["pim"]),
                "devengado_soles": soles(p["dev"]),
                "nombres_distintos": len(names),
            })

    total_m = {"pia": sum(m["pia"] for m in municipality.values()),
               "pim": sum(m["pim"] for m in municipality.values()),
               "dev": sum(m["dev"] for m in municipality.values()),
               "project_pim": sum(m["project_pim"] for m in municipality.values()),
               "project_dev": sum(m["project_dev"] for m in municipality.values())}
    report["sources"] = source_stats
    report["totals"] = {
        "source_rows_read": overall["rows_read"],
        "non_local_rows": overall["non_local_rows"],
        "local_rows": overall["local_rows"],
        "local_accepted": overall["local_accepted"],
        "local_rejected": overall["local_rejected"],
        "malformed_rows": overall["malformed_rows"],
        "local_project_rows": overall["local_project_rows"],
        "municipality_year_profiles": len(municipality),
        "project_executor_year_profiles": len(projects),
        "sum_local_pia_soles": soles(total_m["pia"]),
        "sum_local_pim_soles": soles(total_m["pim"]),
        "sum_local_dev_soles": soles(total_m["dev"]),
        "sum_local_project_pim_soles": soles(total_m["project_pim"]),
        "sum_local_project_dev_soles": soles(total_m["project_dev"]),
        "sum_projects_with_code_pim_soles": soles(sum(p["pim"] for p in projects.values())),
        "sum_projects_with_code_dev_soles": soles(sum(p["dev"] for p in projects.values())),
        "sum_projects_missing_code_pim_soles": soles(overall["local_project_pim_missing_code_cents"]),
        "sum_projects_missing_code_dev_soles": soles(overall["local_project_dev_missing_code_cents"]),
    }
    report["sufficiency"] = {
        "original_local_rows_above_2m": overall["local_rows"] > 2_000_000,
        "accepted_local_rows_above_2m": overall["local_accepted"] > 2_000_000,
        "accepted_local_rows_above_1m": overall["local_accepted"] > 1_000_000,
        "important_note": "Las filas presupuestarias no equivalen a observaciones de K-Means municipal",
    }
    report["integrity"] = {
        "totals_equal_aggregates": (
            total_m["pia"] == overall["local_pia_cents"] and
            total_m["pim"] == overall["local_pim_cents"] and
            total_m["dev"] == overall["local_dev_cents"]
        ),
        "projects_equal_with_missing_key_adjustment": (
            total_m["project_dev"] ==
            sum(p["dev"] for p in projects.values()) + overall["local_project_dev_missing_code_cents"]
        ),
        "row_balance": (
            overall["rows_read"] == overall["non_local_rows"] +
            overall["local_accepted"] + overall["local_rejected"] +
            overall["malformed_rows"]
        ),
    }
    report["artifacts"] = ["municipality_year_features.csv", "project_features.csv",
                           "incidencias_preprocesamiento.csv"] + (
                           ["budget_lines_clean.csv.gz"] if write_lines else [])
    (out_dir / "reporte_preprocesamiento.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    md = ["# Preprocesamiento de Gasto Devengado — MEF", "",
          f"Modo: **{mode}**. Conteos completos: **{'SI' if mode == 'full' else 'NO'}**.", "",
          f"- Filas leídas: **{overall['rows_read']:,}**",
          f"- Filas municipales: **{overall['local_rows']:,}**",
          f"- Aceptadas para agregación: **{overall['local_accepted']:,}**",
          f"- Municipales con incidencias: **{overall['local_rejected']:,}**",
          f"- Perfiles ejecutora-año: **{len(municipality):,}**",
          f"- Perfiles ejecutora-proyecto-año: **{len(projects):,}**", "",
          "## Suficiencia (registros de líneas; no perfiles municipales)", "",
          *(f"- {k}: **{v}**" for k, v in report["sufficiency"].items() if k != "important_note"), "",
          "## Reconciliaciones", "",
          *(f"- {k}: **{v}**" for k, v in report["integrity"].items()), "",
          "## Advertencias", "",
          "- El archivo Seguimiento PI NO ha sido fusionado.",
          "- No se han eliminado duplicados exactos ni se han imputado valores.",
          "- Una fila de proyecto es una línea presupuestaria, NO una obra única.",
          "- Los candidatos a K-Means NO estan escalados ni constituyen dataset de entrenamiento final.",
          "- Los montos de filas rechazadas no se contabilizan; revisar incidencias antes del modelo.",
          "- Datos y artefactos grandes se mantienen fuera de GitHub."]
    (out_dir / "resumen_preprocesamiento.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data" / "raw")
    parser.add_argument("--out-dir", type=Path,
                        default=ROOT / "data" / "processed" / "preprocessing_mef")
    parser.add_argument("--mode", choices=("smoke", "full"), default="smoke")
    parser.add_argument("--smoke-local", type=int, default=500)
    parser.add_argument("--write-lines", action="store_true",
                        help="Exportar lineas municipales validadas a CSV comprimido")
    parser.add_argument("--progress", type=int, default=250000)
    args = parser.parse_args()
    if args.smoke_local <= 0 or args.progress < 0:
        parser.error("--smoke-local debe ser positivo y --progress no negativo")
    print("Inicio de preprocesamiento; no une Seguimiento PI", flush=True)
    report = process(args.data_dir, args.out_dir, args.mode, args.smoke_local,
                     args.write_lines, args.progress)
    print(f"OK: {args.out_dir / 'reporte_preprocesamiento.json'}", flush=True)
    print("Integridad:", report["integrity"])
    if not all(report["integrity"].values()):
        raise SystemExit("ERROR: las reconciliaciones no coinciden")


if __name__ == "__main__":
    main()
