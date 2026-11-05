#!/usr/bin/env python3
"""Auditoría inicial reproducible de volumen y cobertura de CSV grandes del MEF.

Lee en streaming, no modifica los CSV originales y no asume que códigos numéricos
representen proyectos o gobiernos locales sin un diccionario validado.

Ejemplos:
    py scripts/eda/audit_volume.py --mode quick
    py scripts/eda/audit_volume.py --mode full
    py scripts/eda/audit_volume.py --mode full --data-dir "D:/MEF"
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import time
import unicodedata
import zipfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ALIASES = {
    "2024_gasto": ("2024", "gasto", "devengado"),
    "2025_gasto": ("2025", "gasto", "devengado"),
    "2024_proyectos": ("2024", "seguimiento", "pi"),
    "2025_proyectos": ("2025", "seguimiento", "pi"),
}
NULLS = {"", "NULL", "N/A", "NA", "NAN", "NONE", "S/D", "SIN DATO"}
GOV_LOCAL = {"M", "LOCAL", "GOBIERNO LOCAL", "GOBIERNOS LOCALES", "MUNICIPAL"}
NULLS_NORMALIZED = {re.sub(r"[^A-Z0-9]+", "_", x.upper()).strip("_") for x in NULLS}
GOV_LOCAL_NORMALIZED = {re.sub(r"[^A-Z0-9]+", "_", x.upper()).strip("_") for x in GOV_LOCAL}


def normalize(s: str) -> str:
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[^A-Z0-9]+", "_", s.upper()).strip("_")


def is_null(s: str) -> bool:
    return normalize(s) in NULLS_NORMALIZED


def locate_files(folder: Path) -> tuple[list[tuple[str, Path]], list[str]]:
    if not folder.is_dir():
        raise FileNotFoundError(f"No existe el directorio: {folder}")
    files = [p for p in folder.iterdir() if p.is_file() and p.suffix.lower() == ".csv"]
    chosen, warnings = [], []
    for alias, parts in ALIASES.items():
        matching = sorted(p for p in files if all(w in normalize(p.stem).lower() for w in parts))
        if not matching:
            warnings.append(f"Falta {alias}: no se localizó CSV compatible")
        elif len(matching) > 1:
            warnings.append(f"{alias}: múltiples candidatos; se procesarán por separado: " + ", ".join(p.name for p in matching))
        for i, p in enumerate(matching):
            chosen.append((alias if i == 0 else f"{alias}_extra{i}", p))
    return chosen, warnings


def detect_format(path: Path) -> tuple[str, str]:
    with path.open("rb") as f:
        head = f.read(128 * 1024)
    if head.startswith(b"\xef\xbb\xbf"):
        enc = "utf-8-sig"
    elif head.startswith((b"\xff\xfe", b"\xfe\xff")):
        enc = "utf-16"
    else:
        sample = head[: head.rfind(b"\n") + 1] if b"\n" in head else head
        try:
            sample.decode("utf-8")
            enc = "utf-8-sig"
        except UnicodeDecodeError:
            enc = "cp1252"
    line = head.decode(enc, errors="replace").splitlines()[0]
    scores = []
    for delim in (";", ",", "|", "\t"):
        try:
            scores.append((len(next(csv.reader([line], delimiter=delim))), delim))
        except (csv.Error, StopIteration):
            continue
    return enc, max(scores, default=(1, ","))[1]


def find_column(columns: list[str], *preferred_names: str) -> str | None:
    normalized = {normalize(c): c for c in columns}
    for n in preferred_names:
        if normalize(n) in normalized:
            return normalized[normalize(n)]
    return None


def classify_local(raw: str) -> bool:
    """Conservador: códigos numéricos sin diccionario NO se adivinan."""
    norm = normalize(raw)
    return norm in GOV_LOCAL_NORMALIZED or norm.startswith("GOBIERNO_LOCAL_")


def classify_project_text(raw: str) -> bool:
    """Solo reconoce etiquetas explícitas; no presupone que '2' sea proyecto."""
    norm = normalize(raw)
    return norm in {"PROYECTO", "PROYECTOS", "PROYECTO_DE_INVERSION"} or norm.startswith("PROYECTO_")


def audit_file(alias: str, path: Path, mode: str = "quick", max_rows: int = 100_000,
               progress: int = 500_000) -> dict:
    start = time.monotonic()
    enc, sep = detect_format(path)
    r = {
        "id": alias, "archivo": path.name, "bytes": path.stat().st_size,
        "modo": mode, "conteo_completo": mode == "full", "encoding": enc,
        "delimitador": "TAB" if sep == "\t" else sep,
        "filas_leidas": 0, "filas_validas": 0, "filas_mal_formadas": 0,
        "gobiernos_locales": 0, "proyectos_etiquetados": 0,
        "locales_y_proyectos_etiquetados": 0, "entidades_locales_unicas": None,
        "advertencias": [], "faltantes_campos_clave": {},
    }
    with path.open("r", encoding=enc, errors="replace", newline="") as f:
        reader = csv.reader(f, delimiter=sep, strict=False)
        try:
            columns = [c.lstrip("\ufeff").strip() for c in next(reader)]
        except StopIteration as exc:
            raise ValueError(f"CSV vacío: {path.name}") from exc
        if not columns:
            raise ValueError(f"CSV sin encabezado: {path.name}")
        r["columnas"] = columns
        r["num_columnas"] = len(columns)
        government = find_column(columns, "NIVEL_GOBIERNO", "NIVEL_GOBIERNO_NOMBRE", "NIVEL_GOB")
        ptype = find_column(columns, "TIPO_ACT_PROY", "TIPO_ACT_PROY_NOMBRE", "TIPO_ACTIVIDAD_PROYECTO")
        entity = find_column(columns, "SEC_EJEC", "CODIGO_EJECUTORA", "EJECUTORA", "EJECUTORA_NOMBRE")
        year = find_column(columns, "ANO_EJE", "ANIO_EJE", "ANO", "ANIO")
        department = find_column(columns, "DEPARTAMENTO_EJECUTORA_NOMBRE", "DEPARTAMENTO_NOMBRE", "DEPARTAMENTO_EJECUTORA")
        project = find_column(columns, "PRODUCTO_PROYECTO", "CODIGO_UNICO_INVERSION", "CODIGO_UNICO", "CUI")
        r["columnas_detectadas"] = {"nivel_gobierno": government, "tipo_act_proy": ptype,
                                    "entidad": entity, "anio": year, "departamento": department,
                                    "proyecto": project}
        if not government:
            r["advertencias"].append("No se identificó NIVEL_GOBIERNO: no es posible contar gobiernos locales con certeza")
        if not ptype:
            r["advertencias"].append("No se identificó TIPO_ACT_PROY: no es posible identificar proyectos con certeza")
        levels, types, departments, years = Counter(), Counter(), Counter(), Counter()
        unique_local_entities: set[str] = set()
        key_cols = [c for c in (government, ptype, entity, year, department, project) if c]
        missing = Counter()
        idx = {name: i for i, name in enumerate(columns)}
        local_ambiguous = 0
        project_ambiguous = 0
        for values in reader:
            if mode == "quick" and r["filas_leidas"] >= max_rows:
                break
            r["filas_leidas"] += 1
            if len(values) != len(columns):
                r["filas_mal_formadas"] += 1
                continue
            r["filas_validas"] += 1
            for col in key_cols:
                if is_null(values[idx[col]]):
                    missing[col] += 1
            gov_val = values[idx[government]].strip() if government else ""
            type_val = values[idx[ptype]].strip() if ptype else ""
            dept_val = values[idx[department]].strip() if department else ""
            year_val = values[idx[year]].strip() if year else ""
            if government:
                levels[gov_val or "<VACIO>"] += 1
                if gov_val.isdigit():
                    local_ambiguous += 1
            if ptype:
                types[type_val or "<VACIO>"] += 1
                if type_val.isdigit():
                    project_ambiguous += 1
            if department:
                departments[dept_val or "<VACIO>"] += 1
            if year:
                years[year_val or "<VACIO>"] += 1
            is_local = bool(government and classify_local(gov_val))
            is_project = bool(ptype and classify_project_text(type_val))
            if is_local:
                r["gobiernos_locales"] += 1
                if entity:
                    entity_key = values[idx[entity]].strip()
                    if entity_key:
                        unique_local_entities.add((year_val or "", entity_key))
            if is_project:
                r["proyectos_etiquetados"] += 1
            if is_local and is_project:
                r["locales_y_proyectos_etiquetados"] += 1
            if progress > 0 and r["filas_leidas"] % progress == 0:
                print(f"    {path.name}: {r['filas_leidas']:,} registros", flush=True)
    r["entidades_locales_unicas"] = len(unique_local_entities) if government and entity else None
    r["niveles_gobierno"] = levels.most_common(100)
    r["tipos_act_proy"] = types.most_common(100)
    r["departamentos"] = departments.most_common(100)
    r["anios_observados"] = years.most_common(100)
    r["faltantes_campos_clave"] = dict(missing)
    r["filas_codigo_nivel_numerico_sin_interpretar"] = local_ambiguous
    r["filas_codigo_tipo_numerico_sin_interpretar"] = project_ambiguous
    if local_ambiguous:
        r["advertencias"].append("Hay códigos numéricos de nivel de gobierno sin interpretar; revisar diccionario")
    if project_ambiguous:
        r["advertencias"].append("Hay códigos numéricos de tipo de proyecto sin interpretar; revisar diccionario")
    if mode == "quick":
        r["advertencias"].append("MODO QUICK: los conteos son una muestra inicial, no todo el CSV")
    r["segundos"] = round(time.monotonic() - start, 2)
    return r


def summarize(reports: list[dict], mode: str) -> tuple[str, dict]:
    # No se suman Seguimiento PI y Devengado: distinta granularidad y posible solapamiento.
    gasto = [r for r in reports if r["id"] in ("2024_gasto", "2025_gasto") and not r.get("error")]
    both = len(gasto) == 2 and all(r["conteo_completo"] for r in gasto)
    count_all = sum(r["filas_validas"] for r in gasto)
    count_local = sum(r["gobiernos_locales"] for r in gasto)
    known_gov = bool(gasto and all(r["columnas_detectadas"]["nivel_gobierno"] for r in gasto))
    lines = ["# Auditoría de volumen y cobertura del MEF", "", f"Modo ejecutado: **{mode}**", "",
             "- Fuente principal propuesta: **Gasto Devengado**, años 2024 y 2025.",
             "- **Seguimiento PI no se suma** a Gasto Devengado porque puede describir los mismos proyectos con otra granularidad.",
             "- Los conteos estructurales NO demuestran ausencia de duplicados ni calidad final para K-Means.", ""]
    for r in reports:
        lines.extend([f"## {r['archivo']}", ""])
        if r.get("error"):
            lines.extend([f"ERROR: {r['error']}", ""])
            continue
        lines += [f"- Filas leídas: **{r['filas_leidas']:,}**",
                  f"- Filas con estructura válida: **{r['filas_validas']:,}**",
                  f"- Filas mal formadas: **{r['filas_mal_formadas']:,}**",
                  f"- Filas identificadas como gobierno local: **{r['gobiernos_locales']:,}**",
                  f"- Filas con etiqueta textual explícita de proyecto: **{r['proyectos_etiquetados']:,}**",
                  f"- Coincidencia local + proyecto etiquetado: **{r['locales_y_proyectos_etiquetados']:,}**",
                  f"- Entidades locales distintas (año, código): **{r['entidades_locales_unicas']}**",
                  f"- Columnas detectadas: `{json.dumps(r['columnas_detectadas'], ensure_ascii=False)}`", "",
                  "Niveles de gobierno más frecuentes:", ""]
        lines += [f"- `{v}`: {n:,}" for v, n in r["niveles_gobierno"][:15]] or ["- No disponible"]
        lines += ["", "Tipos de actividad/proyecto más frecuentes:", ""]
        lines += [f"- `{v}`: {n:,}" for v, n in r["tipos_act_proy"][:15]] or ["- No disponible"]
        if r["advertencias"]:
            lines += ["", "Advertencias:", ""] + [f"- {w}" for w in r["advertencias"]]
        lines.append("")
    lines += ["## Decisión preliminar sobre volumen", ""]
    decision = {"modo": mode, "gasto_2024_2025_completos": both,
                "gasto_filas_validas": count_all, "gasto_filas_locales_detectadas": count_local,
                "gasto_identificacion_gobierno_local_disponible": known_gov,
                "supera_2m_locales_preliminar": None}
    if not both or not known_gov:
        lines.append("**Pendiente**. Ejecutar `--mode full` y confirmar la columna de nivel de gobierno en ambos años.")
    else:
        decision["supera_2m_locales_preliminar"] = count_local > 2_000_000
        if count_local > 2_000_000:
            lines.append(f"**Sí, preliminarmente:** {count_local:,} filas de gobiernos locales en Gasto Devengado 2024–2025.")
        else:
            lines.append(f"**No alcanza todavía:** {count_local:,} filas identificadas como locales en Gasto Devengado 2024–2025.")
        lines.append("Esto NO confirma el volumen del subconjunto de obras/inversiones ni de registros depurados para K-Means.")
    lines += ["", "## Próximas verificaciones", "",
              "1. Confirmar con el diccionario qué códigos representan proyectos/inversiones.",
              "2. Evaluar la granularidad y posibles duplicados antes de unir datasets.",
              "3. Revisar tipos y calidad de PIA, PIM y devengados y el corte temporal de 2025.",
              "4. Definir si K-Means agrupará partidas, proyectos o perfiles municipales.", ""]
    return "\n".join(lines), decision


def write_reports(reports: list[dict], warnings: list[str], out: Path, mode: str) -> Path:
    out.mkdir(parents=True, exist_ok=True)
    md, decision = summarize(reports, mode)
    (out / "resumen.md").write_text(md, encoding="utf-8")
    (out / "reporte.json").write_text(json.dumps({"fecha_utc": datetime.now(timezone.utc).isoformat(),
      "modo": mode, "advertencias": warnings, "decision_preliminar": decision,
      "archivos": reports}, ensure_ascii=False, indent=2), encoding="utf-8")
    with (out / "inventario_volumen.csv").open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["archivo", "modo", "filas_leidas", "filas_validas", "mal_formadas", "gobiernos_locales",
                         "proyectos_etiqueta_textual", "locales_proyectos", "entidades_locales_distintas"])
        for r in reports:
            writer.writerow([r["archivo"], r.get("modo", ""), r.get("filas_leidas", ""), r.get("filas_validas", ""),
                             r.get("filas_mal_formadas", ""), r.get("gobiernos_locales", ""),
                             r.get("proyectos_etiquetados", ""), r.get("locales_y_proyectos_etiquetados", ""),
                             r.get("entidades_locales_unicas", "")])
    archive = out.parent / f"auditoria_volumen_mef_{mode}.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as z:
        for f in sorted(out.iterdir()):
            if f.is_file():
                z.write(f, f.name)
    return archive


def main() -> int:
    parser = argparse.ArgumentParser(description="Auditoría de volumen MEF, por streaming")
    parser.add_argument("--mode", choices=("quick", "full"), default="quick")
    parser.add_argument("--max-rows", type=int, default=100_000, help="Por CSV en modo quick")
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data" / "raw")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "data" / "processed" / "auditoria_volumen")
    parser.add_argument("--progress", type=int, default=500_000)
    args = parser.parse_args()
    if args.max_rows <= 0 or args.progress < 0:
        parser.error("--max-rows debe ser positivo; --progress no puede ser negativo")
    try:
        csv.field_size_limit(sys.maxsize)
    except OverflowError:
        csv.field_size_limit(2**31 - 1)
    try:
        files, warnings = locate_files(args.data_dir)
    except FileNotFoundError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    if not files:
        print("ERROR: no se encontraron CSV compatibles", file=sys.stderr)
        return 1
    reports = []
    for alias, path in files:
        print(f"Analizando {path.name} ({args.mode})...", flush=True)
        try:
            reports.append(audit_file(alias, path, args.mode, args.max_rows, args.progress))
        except (OSError, ValueError, UnicodeError, csv.Error) as e:
            print(f"ERROR en {path.name}: {e}", file=sys.stderr)
            reports.append({"id": alias, "archivo": path.name, "error": str(e)})
    path = write_reports(reports, warnings, args.output_dir, args.mode)
    print(f"Reporte: {args.output_dir / 'resumen.md'}")
    print(f"ZIP para compartir: {path}")
    return 2 if any("error" in r for r in reports) else 0


if __name__ == "__main__":
    raise SystemExit(main())
