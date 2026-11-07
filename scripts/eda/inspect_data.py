#!/usr/bin/env python3
"""Inspección reproducible de grandes CSV del MEF (sin dependencias externas).

Ejemplos (desde la raíz del repositorio):
    py scripts/eda/inspect_data.py --mode quick
    py scripts/eda/inspect_data.py --mode full
    py scripts/eda/inspect_data.py --data-dir "D:/Datasets/MEF" --mode quick

No entrena K-Means ni transforma los datos originales.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import re
import sys
import time
import zipfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
EXPECTED = {
    "2024_gasto": ("2024", "gasto", "devengado"),
    "2025_gasto": ("2025", "gasto", "devengado"),
    "2024_proyectos": ("2024", "seguimiento", "pi"),
    "2025_proyectos": ("2025", "seguimiento", "pi"),
}
NULL_TOKENS = {"", "NULL", "N/A", "NA", "NONE", "NAN", "SIN DATO", "S/D"}
AMOUNT_WORDS = (
    "MONTO", "PIA", "PIM", "DEVENG", "GIRADO", "COMPROM", "CERTIFIC",
    "COSTO", "SALDO", "IMPORTE", "EJECUCION", "EJECUCIÓN", "AVANCE", "PORC",
)
CATEGORY_WORDS = ("NIVEL_GOBIERNO", "DEPARTAMENTO", "TIPO_ACT", "ANO_EJE", "ANIO_EJE")


def encoding_from_bytes(head: bytes) -> str:
    if head.startswith(b"\xef\xbb\xbf"):
        return "utf-8-sig"
    if head.startswith((b"\xff\xfe", b"\xfe\xff")):
        return "utf-16"
    # Evita detectar erróneamente CP1252 cuando el corte cae en un carácter UTF-8.
    trimmed = head[:head.rfind(b"\n") + 1] if b"\n" in head else head
    try:
        trimmed.decode("utf-8")
        return "utf-8-sig"
    except UnicodeDecodeError:
        try:
            trimmed.decode("cp1252")
            return "cp1252"
        except UnicodeDecodeError:
            return "latin-1"


def delimiter_from_text(text: str) -> str:
    first_line = next((s for s in text.splitlines() if s.strip()), "")
    candidates = (";", ",", "|", "\t")
    # La cabecera se analiza respetando las comillas.
    scored = []
    for delimiter in candidates:
        try:
            fields = next(csv.reader([first_line], delimiter=delimiter))
            scored.append((len(fields), delimiter))
        except csv.Error:
            pass
    return max(scored, default=(1, ","))[1]


def resolve_files(data_dir: Path) -> tuple[list[tuple[str, Path]], list[str]]:
    if not data_dir.is_dir():
        raise FileNotFoundError(f"La carpeta de datos no existe: {data_dir}")
    available = [p for p in data_dir.iterdir() if p.is_file() and p.suffix.lower() == ".csv"]
    matches: list[tuple[str, Path]] = []
    warnings = []
    for alias, fragments in EXPECTED.items():
        files = [p for p in available if all(fragment in p.stem.lower() for fragment in fragments)]
        if not files:
            warnings.append(f"No se encontró el archivo {alias} en {data_dir}")
            continue
        if len(files) > 1:
            warnings.append(f"Múltiples archivos para {alias}; revisar duplicados: {', '.join(p.name for p in files)}")
        for index, file in enumerate(sorted(files)):
            matches.append((alias if index == 0 else f"{alias}_extra{index}", file))
    return matches, warnings


def is_amount_col(name: str) -> bool:
    upper = name.upper()
    return any(w in upper for w in AMOUNT_WORDS)


def is_category_col(name: str) -> bool:
    upper = name.upper()
    return any(w in upper for w in CATEGORY_WORDS)


def parse_number(raw: str) -> float | None:
    value = raw.strip().replace(" ", "").replace("\u00a0", "")
    if not value:
        return None
    if value.startswith(("S/", "$")):
        value = value[2:] if value.startswith("S/") else value[1:]
    # 1.234,56 y 1,234.56; si hay un único separador, suponer decimal.
    if "," in value and "." in value:
        if value.rfind(",") > value.rfind("."):
            value = value.replace(".", "").replace(",", ".")
        else:
            value = value.replace(",", "")
    elif "," in value:
        value = value.replace(",", ".")
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except ValueError:
        return None


def safe_preview(value: str, limit: int = 120) -> str:
    value = value.replace("\r", " ").replace("\n", " ").strip()
    return value[:limit] + ("…" if len(value) > limit else "")


def new_column_stats(name: str) -> dict[str, Any]:
    return {
        "columna": name,
        "vacios": 0,
        "no_vacios": 0,
        "ejemplos": [],
        "numericos_validos": 0,
        "numericos_no_parseables": 0,
        "numericos_negativos": 0,
        "numericos_cero": 0,
        "min_numerico": None,
        "max_numerico": None,
        "categorias": Counter() if is_category_col(name) else None,
        "categorias_omitidas": 0,
    }


def read_header(reader: csv.reader) -> list[str]:
    for row in reader:
        if any(x.strip() for x in row):
            return [col.lstrip("\ufeff").strip() for col in row]
    return []


def inspect_file(alias: str, path: Path, mode: str, quick_rows: int, examples: int, progress: int) -> dict[str, Any]:
    began = time.monotonic()
    size_bytes = path.stat().st_size
    with path.open("rb") as stream:
        head = stream.read(131072)
    encoding = encoding_from_bytes(head)
    delimiter = delimiter_from_text(head.decode(encoding, errors="replace"))
    max_rows = quick_rows if mode == "quick" else None

    report: dict[str, Any] = {
        "identificador": alias,
        "archivo": path.name,
        "tamano_bytes": size_bytes,
        "tamano_gib": round(size_bytes / (1024**3), 3),
        "codificacion_estimada": encoding,
        "separador": "TAB" if delimiter == "\t" else delimiter,
        "modo": mode,
        "filas_analizadas": 0,
        "filas_validas": 0,
        "filas_con_columnas_incorrectas": 0,
        "filas_totales_exactas": mode == "full",
        "ejemplos_de_filas_invalidas": [],
        "muestras": [],
        "advertencias": [],
    }
    if encoding in ("latin-1", "cp1252"):
        report["advertencias"].append("Codificación estimada; revisar acentos y símbolos en muestras")
    if mode == "quick":
        report["advertencias"].append("Conteos calculados solo sobre una muestra inicial; NO son totales del archivo")

    with path.open("r", encoding=encoding, errors="replace", newline="") as stream:
        reader = csv.reader(stream, delimiter=delimiter, strict=False)
        names = read_header(reader)
        if not names:
            raise ValueError("No se pudo leer el encabezado")
        report["columnas"] = names
        report["num_columnas"] = len(names)
        report["encabezados_repetidos"] = [x for x, n in Counter(names).items() if n > 1]
        profiles = [new_column_stats(c) for c in names]

        for row_number, values in enumerate(reader, start=1):
            if max_rows is not None and report["filas_analizadas"] >= max_rows:
                break
            report["filas_analizadas"] += 1
            if len(values) != len(names):
                report["filas_con_columnas_incorrectas"] += 1
                if len(report["ejemplos_de_filas_invalidas"]) < 5:
                    report["ejemplos_de_filas_invalidas"].append({
                        "numero_relativo": row_number, "columnas_encontradas": len(values),
                        "columnas_esperadas": len(names)
                    })
                continue
            report["filas_validas"] += 1
            if len(report["muestras"]) < examples:
                report["muestras"].append({name: safe_preview(value) for name, value in zip(names, values)})
            for pos, value in enumerate(values):
                cell = value.strip()
                profile = profiles[pos]
                if cell.upper() in NULL_TOKENS:
                    profile["vacios"] += 1
                    continue
                profile["no_vacios"] += 1
                if len(profile["ejemplos"]) < 3 and safe_preview(cell, 60) not in profile["ejemplos"]:
                    profile["ejemplos"].append(safe_preview(cell, 60))
                counts = profile["categorias"]
                if counts is not None:
                    if cell in counts or len(counts) < 500:
                        counts[cell] += 1
                    else:
                        profile["categorias_omitidas"] += 1
                if is_amount_col(names[pos]):
                    numeric = parse_number(cell)
                    if numeric is None:
                        profile["numericos_no_parseables"] += 1
                    else:
                        profile["numericos_validos"] += 1
                        profile["numericos_negativos"] += int(numeric < 0)
                        profile["numericos_cero"] += int(numeric == 0)
                        old_min = profile["min_numerico"]
                        old_max = profile["max_numerico"]
                        profile["min_numerico"] = numeric if old_min is None else min(old_min, numeric)
                        profile["max_numerico"] = numeric if old_max is None else max(old_max, numeric)
            if progress > 0 and report["filas_analizadas"] % progress == 0:
                print(f"    {report['filas_analizadas']:,} filas leídas", flush=True)

    columns = []
    for profile in profiles:
        categories = profile.pop("categorias")
        profile["top_categorias"] = categories.most_common(15) if categories is not None else []
        columns.append(profile)
    report["perfiles_columnas"] = columns
    report["duracion_segundos"] = round(time.monotonic() - began, 2)
    report["filas_por_segundo"] = round(report["filas_analizadas"] / max(report["duracion_segundos"], 0.001))
    if report["filas_con_columnas_incorrectas"]:
        report["advertencias"].append("Hay registros con número inesperado de columnas; revisar separador/comillas/formato")
    return report


def save_outputs(results: list[dict[str, Any]], warnings: list[str], output: Path, mode: str) -> Path:
    output.mkdir(parents=True, exist_ok=True)
    payload = {
        "generado_en_utc": datetime.now(timezone.utc).isoformat(),
        "fase": "inspeccion_inicial_mef", "modo": mode,
        "advertencias_globales": warnings, "archivos": results,
    }
    (output / "reporte.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    with (output / "inventario.csv").open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.writer(file)
        writer.writerow(["identificador", "archivo", "tamano_gib", "num_columnas", "filas_analizadas",
                         "filas_validas", "filas_incorrectas", "conteo_exactamente_total", "duracion_segundos", "error"])
        for r in results:
            writer.writerow([r.get("identificador"), r.get("archivo"), r.get("tamano_gib"), r.get("num_columnas"),
                             r.get("filas_analizadas"), r.get("filas_validas"),
                             r.get("filas_con_columnas_incorrectas"), r.get("filas_totales_exactas"),
                             r.get("duracion_segundos"), r.get("error", "")])
    with (output / "perfil_columnas.csv").open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.writer(file)
        writer.writerow(["archivo", "columna", "vacios", "no_vacios", "ejemplos", "numericos_validos",
                         "numericos_no_parseables", "numericos_negativos", "numericos_cero", "min_numerico",
                         "max_numerico", "top_categorias", "categorias_omitidas"])
        for r in results:
            for col in r.get("perfiles_columnas", []):
                writer.writerow([r["archivo"], col["columna"], col["vacios"], col["no_vacios"],
                                 " | ".join(col["ejemplos"]), col["numericos_validos"],
                                 col["numericos_no_parseables"], col["numericos_negativos"],
                                 col["numericos_cero"], col["min_numerico"], col["max_numerico"],
                                 json.dumps(col["top_categorias"], ensure_ascii=False), col["categorias_omitidas"]])
    summary = ["# Inspección de archivos del MEF", "", f"Modo: **{mode}**", "",
               "Este reporte no representa aún el EDA definitivo ni define el modelo.", ""]
    if mode == "quick":
        summary.append("**Atención:** los conteos corresponden solo a filas iniciales inspeccionadas, no al total.")
        summary.append("")
    for r in results:
        summary += [f"## {r['archivo']}", ""]
        if "error" in r:
            summary += [f"ERROR: {r['error']}", ""]
            continue
        summary += [f"- Tamaño: {r['tamano_gib']} GiB",
                    f"- Columnas: {r['num_columnas']}",
                    f"- Filas procesadas: {r['filas_analizadas']:,}",
                    f"- Filas con estructura correcta: {r['filas_validas']:,}",
                    f"- Filas con columnas incorrectas: {r['filas_con_columnas_incorrectas']:,}",
                    f"- Separador: `{r['separador']}` · codificación: `{r['codificacion_estimada']}`", "",
                    "**Encabezados:**", "",
                    ", ".join(f"`{n}`" for n in r['columnas']), ""]
        for warning in r["advertencias"]:
            summary.append(f"- Aviso: {warning}")
        summary.append("")
    if warnings:
        summary += ["## Advertencias generales", ""] + [f"- {w}" for w in warnings] + [""]
    (output / "resumen.md").write_text("\n".join(summary), encoding="utf-8")
    # Contenido exportable sin CSV originales: los reportes no contienen todas las filas.
    zip_path = output.parent / f"inspeccion_mef_{mode}.zip"
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as z:
        for path in sorted(output.iterdir()):
            if path.is_file():
                z.write(path, arcname=path.name)
    return zip_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Inspección de CSV del MEF sin cargar todo en RAM")
    parser.add_argument("--data-dir", type=Path, default=PROJECT_ROOT / "data" / "raw", help="Carpeta de CSV originales")
    parser.add_argument("--output-dir", type=Path, default=PROJECT_ROOT / "data" / "processed" / "inspeccion_mef", help="Carpeta de reportes")
    parser.add_argument("--mode", choices=("quick", "full"), default="quick", help="quick=muestra inicial; full=lectura de todo el CSV")
    parser.add_argument("--quick-rows", type=int, default=3000, help="Máximo de filas a inspeccionar en modo quick por archivo")
    parser.add_argument("--examples", type=int, default=3, help="Número de ejemplos de registros por archivo")
    parser.add_argument("--progress", type=int, default=250000, help="Mostrar progreso cada N filas (0 para desactivar)")
    args = parser.parse_args()
    if args.quick_rows < 1 or not (0 <= args.examples <= 20) or args.progress < 0:
        parser.error("--quick-rows debe ser positivo, --examples de 0 a 20 y --progress no negativo")
    csv.field_size_limit(sys.maxsize)
    try:
        found, warnings = resolve_files(args.data_dir.expanduser())
    except OSError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    if not found:
        print(f"ERROR: no se encontraron los CSV esperados en {args.data_dir}", file=sys.stderr)
        return 1
    output = args.output_dir.expanduser()
    results = []
    for alias, path in found:
        print(f"[{alias}] Leyendo {path.name} ({args.mode})", flush=True)
        try:
            results.append(inspect_file(alias, path, args.mode, args.quick_rows, args.examples, args.progress))
        except (OSError, ValueError, UnicodeError, csv.Error) as exc:
            print(f"  ERROR: {exc}", flush=True)
            results.append({"identificador": alias, "archivo": path.name, "error": str(exc)})
    archive = save_outputs(results, warnings, output, args.mode)
    print(f"\nReporte generado: {output / 'resumen.md'}")
    print(f"ZIP para compartir: {archive}")
    print("No se modificaron los CSV originales.")
    return 0 if all("error" not in r for r in results) else 2


if __name__ == "__main__":
    raise SystemExit(main())
