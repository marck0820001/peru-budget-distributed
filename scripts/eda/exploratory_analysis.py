#!/usr/bin/env python3
"""EDA estadístico reproducible del MEF: lectura secuencial en streaming (RAM acotada).

Este script NO realiza limpieza definitiva, fusiones entre fuentes ni entrenamiento.
No considera que Seguimiento PI 2024/2025 sean años independientes: son publicaciones
con registros ANO_EJE históricos, cuya relación se audita sin sumarlos.

Uso desde raíz de repositorio:
  py scripts/eda/exploratory_analysis.py --mode quick
  py scripts/eda/exploratory_analysis.py --mode full
  py scripts/eda/exploratory_analysis.py --mode full --data-dir "D:/MEF"
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import random
import re
import sys
import time
import zipfile
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EXPECTED = {
    "2024_gasto": ("2024", "gasto", "devengado"),
    "2025_gasto": ("2025", "gasto", "devengado"),
    "2024_pi": ("2024", "seguimiento", "pi"),
    "2025_pi": ("2025", "seguimiento", "pi"),
}
MONTHS = ("ENERO", "FEBRERO", "MARZO", "ABRIL", "MAYO", "JUNIO",
          "JULIO", "AGOSTO", "SEPTIEMBRE", "OCTUBRE", "NOVIEMBRE", "DICIEMBRE")
AMOUNTS_GASTO = ("MONTO_PIA", "MONTO_PIM", "MONTO_CERTIFICADO_ANUAL",
                 "MONTO_COMPROMETIDO_ANUAL", *(f"MONTO_DEVENGADO_{m}" for m in MONTHS),
                 "MONTO_DEVENGADO_ANUAL", "MONTO_GIRADO_ANUAL")
AMOUNTS_PI = ("COSTO_ACTUAL", "MONTO_EJECUCION_HASTA_HACE_2_ANOS",
              "MONTO_EJECUCION_ANO_ANTERIOR", "MONTO_PIA", "MONTO_PIM",
              "MONTO_DEVENGADO_ANO_EJE", "MONTO_EJECUCION_TOTAL")
NUMERIC_SAMPLES = {"MONTO_PIA", "MONTO_PIM", "MONTO_DEVENGADO_ANUAL", "COSTO_ACTUAL",
                   "MONTO_EJECUCION_TOTAL", "MONTO_DEVENGADO_ANO_EJE"}
NULLS = {"", "NULL", "N/A", "NA", "NAN", "NONE", "SIN DATO", "S/D"}


def locate_files(folder: Path) -> tuple[dict[str, Path], list[str]]:
    if not folder.is_dir():
        raise FileNotFoundError(f"No existe la carpeta de CSV: {folder}")
    files = [f for f in folder.iterdir() if f.is_file() and f.suffix.lower() == ".csv"]
    found, warnings = {}, []
    for alias, parts in EXPECTED.items():
        candidates = sorted(f for f in files if all(p in f.stem.lower() for p in parts))
        if len(candidates) != 1:
            warnings.append(f"{alias}: se esperó 1 archivo, se encontraron {len(candidates)}: "
                            + ", ".join(f.name for f in candidates))
            continue
        found[alias] = candidates[0]
    return found, warnings


def csv_format(file: Path) -> tuple[str, str]:
    with file.open("rb") as f:
        head = f.read(131072)
    if head.startswith(b"\xef\xbb\xbf"):
        encoding = "utf-8-sig"
    elif head.startswith((b"\xff\xfe", b"\xfe\xff")):
        encoding = "utf-16"
    else:
        trimmed = head[:head.rfind(b"\n")+1] if b"\n" in head else head
        try:
            trimmed.decode("utf-8")
            encoding = "utf-8-sig"
        except UnicodeDecodeError:
            encoding = "cp1252"
    text = head.decode(encoding, errors="replace")
    first = text.splitlines()[0]
    options = []
    for delim in (",", ";", "|", "\t"):
        options.append((len(next(csv.reader([first], delimiter=delim))), delim))
    return encoding, max(options)[1]


def parse_money(raw: str) -> float | None:
    """Convierte montos monetarios; nunca inventa valores para nulos/errores.

    Para importes ambiguos fuera del formato usual del MEF, la lectura debe
    verificarse contra los CSV antes de aceptar el preprocesamiento final.
    """
    s = raw.strip().replace("\u00a0", "").replace(" ", "")
    if s.upper() in NULLS:
        return None
    if s.startswith("S/"):
        s = s[2:]
    if s.startswith("$"):
        s = s[1:]
    if "," in s and "." in s:
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        if re.fullmatch(r"[-+]?\d{1,3}(,\d{3})+", s):
            s = s.replace(",", "")
        else:
            s = s.replace(",", ".")
    try:
        value = float(s)
        return value if math.isfinite(value) else None
    except ValueError:
        return None


@dataclass
class NumberProfile:
    # Los percentiles se estiman a partir de una muestra reservoir aleatoria.
    cap: int = 4000
    seen: int = 0
    missing: int = 0
    invalid: int = 0
    zero: int = 0
    negative: int = 0
    pos: int = 0
    sum_value: float = 0.0
    minimum: float | None = None
    maximum: float | None = None
    sample: list[float] = field(default_factory=list)
    rng: random.Random = field(default_factory=lambda: random.Random(20261105))

    def add(self, raw: str, store_sample: bool) -> float | None:
        if raw.strip().upper() in NULLS:
            self.missing += 1
            return None
        value = parse_money(raw)
        if value is None:
            self.invalid += 1
            return None
        self.seen += 1
        self.zero += value == 0
        self.negative += value < 0
        self.pos += value > 0
        self.sum_value += value
        self.minimum = value if self.minimum is None else min(self.minimum, value)
        self.maximum = value if self.maximum is None else max(self.maximum, value)
        if store_sample:
            if len(self.sample) < self.cap:
                self.sample.append(value)
            else:
                candidate = self.rng.randrange(self.seen)
                if candidate < self.cap:
                    self.sample[candidate] = value
        return value

    def result(self) -> dict:
        sample = sorted(self.sample)
        def quantile(q: float) -> float | None:
            if not sample:
                return None
            x = (len(sample) - 1) * q
            lo, hi = math.floor(x), math.ceil(x)
            return round(sample[lo] * (hi-x) + sample[hi] * (x-lo), 4) if lo != hi else round(sample[lo], 4)
        return {
            "validos": self.seen, "vacios": self.missing, "no_numericos": self.invalid,
            "ceros": self.zero, "negativos": self.negative, "positivos": self.pos,
            "min": self.minimum, "p01_aprox": quantile(.01), "p25_aprox": quantile(.25),
            "mediana_aprox": quantile(.50), "p75_aprox": quantile(.75),
            "p99_aprox": quantile(.99), "max": self.maximum,
            "promedio": round(self.sum_value/self.seen, 4) if self.seen else None,
            "muestra_percentiles": len(sample),
        }


def safe_ratio(a: float, b: float) -> float | None:
    return round(a / b, 6) if b > 0 else None


def init_municipality(year: str, entity: str, department: str, name: str) -> dict:
    return {"ano_eje": year, "sec_ejec": entity, "departamento_ejecutora": department,
            "ejecutora_nombre": name, "filas": 0, "filas_proyecto": 0,
            "filas_montos_faltantes_o_invalidos": 0, "pia": 0.0, "pim": 0.0,
            "devengado": 0.0, "pim_proyectos": 0.0, "devengado_proyectos": 0.0,
            "devengado_mensual": [0.0] * 12}


def process_file(alias: str, path: Path, mode: str, quick_rows: int, reservoir: int,
                 municipalities: dict, pi_keys: dict, progress: int) -> tuple[dict, list[dict], dict]:
    is_gasto = alias.endswith("gasto")
    begin = time.monotonic()
    encoding, sep = csv_format(path)
    summary = {
        "dataset": alias, "archivo": path.name, "tamano_bytes": path.stat().st_size,
        "modo": mode, "conteo_completo": mode == "full", "filas": 0, "validas": 0,
        "mal_formadas": 0, "filas_gobierno_local": 0, "filas_local_proyecto": 0,
        "anio_eje_en_nombre_archivo": alias[:4],
        "anio_eje_distinto_nombre_archivo": 0,
        "comparacion_devengado_mes_anual": 0, "diferencias_devengado_mensual_anual": 0,
        "advertencias": [],
    }
    if mode == "quick":
        summary["advertencias"].append("Muestra de primeras filas: no representativa si el archivo está ordenado")
    type_counts, pi_type_name, gov_counts, years = Counter(), Counter(), Counter(), Counter()
    local_department = Counter()
    monthly = defaultdict(lambda: {"no_vacios": 0, "no_ceros": 0, "suma": 0.0})
    key_projects = set() if is_gasto else pi_keys[alias]
    # En PI reutilizamos el set para evitar duplicar memoria. Clave NO equivale a fila única.
    project_lines = Counter()
    numeric = {}
    with path.open("r", encoding=encoding, errors="replace", newline="") as stream:
        reader = csv.reader(stream, delimiter=sep)
        try:
            fields = [c.lstrip("\ufeff").strip() for c in next(reader)]
        except StopIteration as exc:
            raise ValueError(f"Archivo vacío: {path.name}") from exc
        pos = {c: i for i, c in enumerate(fields)}
        required = {"ANO_EJE", "NIVEL_GOBIERNO", "SEC_EJEC", "PRODUCTO_PROYECTO", "TIPO_ACT_PROY"}
        missing = required - set(pos)
        if missing:
            raise ValueError(f"{path.name}: faltan columnas obligatorias {sorted(missing)}")
        amounts = AMOUNTS_GASTO if is_gasto else AMOUNTS_PI
        present = [name for name in amounts if name in pos]
        summary["columnas_ausentes_montos"] = sorted(set(amounts) - set(present))
        numeric = {name: NumberProfile(cap=reservoir) for name in present}
        month_fields = [f"MONTO_DEVENGADO_{m}" for m in MONTHS]
        for row in reader:
            if mode == "quick" and summary["filas"] >= quick_rows:
                break
            summary["filas"] += 1
            if len(row) != len(fields):
                summary["mal_formadas"] += 1
                continue
            summary["validas"] += 1
            def val(name: str) -> str:
                return row[pos[name]].strip() if name in pos else ""
            year = val("ANO_EJE")
            gov = val("NIVEL_GOBIERNO").upper()
            atype = val("TIPO_ACT_PROY").upper()
            gov_counts[gov or "<VACIO>"] += 1
            years[year or "<VACIO>"] += 1
            type_counts[atype or "<VACIO>"] += 1
            if not is_gasto:
                pi_type_name[(atype, val("TIPO_ACT_PROY_NOMBRE"))] += 1
            if year != alias[:4]:
                summary["anio_eje_distinto_nombre_archivo"] += 1
            if gov != "M":
                if progress and summary["filas"] % progress == 0:
                    print(f"  {path.name}: {summary['filas']:,} filas", flush=True)
                continue
            summary["filas_gobierno_local"] += 1
            local_department[(year, val("DEPARTAMENTO_EJECUTORA_NOMBRE") or "<VACIO>")] += 1
            if is_gasto and atype == "PROYECTO":
                summary["filas_local_proyecto"] += 1
            money = {name: numeric[name].add(val(name), store_sample=name in NUMERIC_SAMPLES)
                     for name in present}
            ent = val("SEC_EJEC")
            project = val("PRODUCTO_PROYECTO")
            if project and ent:
                key_projects.add((year, ent, project))
                if is_gasto and atype == "PROYECTO":
                    project_lines[(year, ent, project)] += 1
            if is_gasto:
                key = (year, ent)
                if key not in municipalities:
                    municipalities[key] = init_municipality(
                        year, ent, val("DEPARTAMENTO_EJECUTORA_NOMBRE"), val("EJECUTORA_NOMBRE"))
                m = municipalities[key]
                m["filas"] += 1
                m["filas_proyecto"] += atype == "PROYECTO"
                pia, pim, dev = (money.get("MONTO_PIA"), money.get("MONTO_PIM"),
                                 money.get("MONTO_DEVENGADO_ANUAL"))
                if pia is None or pim is None or dev is None:
                    m["filas_montos_faltantes_o_invalidos"] += 1
                m["pia"] += pia if pia is not None else 0.0
                m["pim"] += pim if pim is not None else 0.0
                m["devengado"] += dev if dev is not None else 0.0
                if atype == "PROYECTO":
                    m["pim_proyectos"] += pim if pim is not None else 0.0
                    m["devengado_proyectos"] += dev if dev is not None else 0.0
                months = [money.get(n) for n in month_fields]
                for i, v in enumerate(months):
                    if v is not None:
                        month = monthly[(year, MONTHS[i])]
                        month["no_vacios"] += 1
                        month["no_ceros"] += v != 0
                        month["suma"] += v
                        m["devengado_mensual"][i] += v
                if dev is not None and all(v is not None for v in months):
                    summary["comparacion_devengado_mes_anual"] += 1
                    if abs(sum(months) - dev) > max(0.05, abs(dev) * 1e-7):
                        summary["diferencias_devengado_mensual_anual"] += 1
            else:
                # PI contiene ANO_EJE históricos en cada snapshot; NO se suman montos al gasto.
                # El conjunto key_projects ya contiene las claves PI.
                pass
            if progress and summary["filas"] % progress == 0:
                print(f"  {path.name}: {summary['filas']:,} filas", flush=True)
    summary["nivel_gobierno"] = dict(gov_counts)
    summary["tipo_act_proy"] = dict(type_counts)
    summary["tipo_proyecto_descripcion"] = [
        {"codigo": code, "descripcion": desc, "filas": n}
        for (code, desc), n in sorted(pi_type_name.items())]
    summary["anios_observados"] = dict(years)
    summary["cantidad_anio_sec_ejec_producto_unicos_locales"] = len(key_projects)
    summary["multiplicidad_lineas_proyecto_locales"] = (
        {"proyectos_con_multiples_lineas": sum(n > 1 for n in project_lines.values()),
         "max_lineas_en_un_proyecto": max(project_lines.values(), default=0),
         "proyectos_con_mas_lineas": [
             {"ano_eje": k[0], "sec_ejec": k[1], "producto_proyecto": k[2], "lineas": n}
             for k, n in project_lines.most_common(10)]} if is_gasto else None)
    summary["departamentos_locales"] = sorted([
        {"ano_eje": yr, "departamento": dept, "filas": count}
        for (yr, dept), count in local_department.items()],
        key=lambda x: (x["ano_eje"], x["departamento"]))
    summary["ejecucion_mensual_local"] = sorted([
        {"ano_eje": yr, "mes": month, "numero_mes": MONTHS.index(month)+1,
         **{k: round(v, 2) if k == "suma" else v for k, v in values.items()}}
        for (yr, month), values in monthly.items()],
        key=lambda x: (x["ano_eje"], x["numero_mes"]))
    summary["calidad_montos_locales"] = [
        {"dataset": alias, "columna": name, **profile.result()} for name, profile in numeric.items()]
    summary["segundos"] = round(time.monotonic() - begin, 2)
    return summary, summary["calidad_montos_locales"], summary["departamentos_locales"]


def municipality_output(municipalities: dict) -> list[dict]:
    result = []
    for x in municipalities.values():
        record = {key: round(value, 2) if isinstance(value, float) else value
                  for key, value in x.items() if key != "devengado_mensual"}
        record["tasa_ejecucion_sobre_pim"] = safe_ratio(x["devengado"], x["pim"])
        record["modificacion_sobre_pia"] = (round((x["pim"]-x["pia"])/x["pia"], 6)
                                            if x["pia"] > 0 else None)
        record["proporcion_devengado_proyecto"] = safe_ratio(
            x["devengado_proyectos"], x["devengado"])
        record["concentracion_q4_sobre_devengado"] = safe_ratio(
            sum(x["devengado_mensual"][9:]), x["devengado"])
        record["nota"] = "Indicadores exploratorios; NO son features finales ni prueba de eficiencia"
        result.append(record)
    return sorted(result, key=lambda y: (y["ano_eje"], y["sec_ejec"]))


def write_csv(path: Path, rows: list[dict], columns: list[str] | None = None) -> None:
    if not rows and columns is None:
        return
    fieldnames = columns or list(rows[0])
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def analyze(data_dir: Path, out_dir: Path, mode: str, quick_rows: int,
            reservoir: int, progress: int) -> dict:
    paths, errors = locate_files(data_dir)
    if errors:
        raise ValueError("No se identificaron exactamente 4 archivos:\n" + "\n".join(errors))
    out_dir.mkdir(parents=True, exist_ok=True)
    municipalities, pi_keys = {}, defaultdict(set)
    all_summaries, quality, coverage = [], [], []
    for alias, path in paths.items():
        print(f"Inspeccionando {path.name} ...", flush=True)
        summary, numbers, geo = process_file(alias, path, mode, quick_rows,
                                              reservoir, municipalities, pi_keys, progress)
        all_summaries.append(summary)
        quality.extend(numbers)
        coverage.extend({"dataset": alias, **r} for r in geo)
    overlap = pi_keys["2024_pi"] & pi_keys["2025_pi"]
    metrics = {
        "filas_locales_gasto": sum(r["filas_gobierno_local"] for r in all_summaries if r["dataset"].endswith("gasto")),
        "filas_proyectos_municipales_gasto": sum(r["filas_local_proyecto"] for r in all_summaries if r["dataset"].endswith("gasto")),
        "entidades_anio_unicas_gasto": len(municipalities),
        "claves_PI_2024_locales": len(pi_keys["2024_pi"]),
        "claves_PI_2025_locales": len(pi_keys["2025_pi"]),
        "claves_PI_en_ambas_publicaciones": len(overlap),
        "nota_claves_PI": "Coincidencia de (ANO_EJE, SEC_EJEC, PRODUCTO_PROYECTO); no son filas duplicadas probadas",
    }
    # Archivos de salida tabulares para informe; no se agregan PI y Gasto en un solo total.
    write_csv(out_dir / "inventario_eda.csv", [
        {k: r[k] for k in ("dataset", "archivo", "tamano_bytes", "modo", "filas", "validas",
                            "mal_formadas", "filas_gobierno_local", "filas_local_proyecto",
                            "anio_eje_distinto_nombre_archivo", "comparacion_devengado_mes_anual",
                            "diferencias_devengado_mensual_anual", "segundos")}
        for r in all_summaries])
    write_csv(out_dir / "calidad_montos.csv", quality)
    write_csv(out_dir / "cobertura_local_departamento.csv", coverage)
    write_csv(out_dir / "evolucion_mensual_local.csv", [
        {"dataset": r["dataset"], **month}
        for r in all_summaries for month in r["ejecucion_mensual_local"]])
    write_csv(out_dir / "municipalidades_indicadores_exploratorios.csv",
              municipality_output(municipalities))
    write_csv(out_dir / "PI_codigos_descripcion.csv", [
        {"dataset": r["dataset"], **entry}
        for r in all_summaries for entry in r["tipo_proyecto_descripcion"]],
        ["dataset", "codigo", "descripcion", "filas"])
    write_csv(out_dir / "anos_disponibles.csv", [
        {"dataset": r["dataset"], "ano_eje": yr, "filas": count}
        for r in all_summaries for yr, count in r["anios_observados"].items()])
    write_csv(out_dir / "tipos_actividad_proyecto.csv", [
        {"dataset": r["dataset"], "tipo_act_proy": typ, "filas": count}
        for r in all_summaries for typ, count in r["tipo_act_proy"].items()])
    (out_dir / "reporte_eda.json").write_text(
        json.dumps({"fecha_utc": datetime.now(timezone.utc).isoformat(),
                    "modo": mode, "indicadores": metrics, "archivos": all_summaries},
                   indent=2, ensure_ascii=False), encoding="utf-8")
    complete = mode == "full"
    note = "**Son conteos completos del CSV**" if complete else "**Son muestras INICIALES no representativas**"
    text = ["# EDA estadístico — MEF", "", f"Modo: **{mode}**. {note}.", "",
            "## Volumen inicial", "",
            "| Archivo | Filas | Gobierno local | Local + proyecto | Año distinto al nombre |",
            "|---|---:|---:|---:|---:|"]
    for r in all_summaries:
        text.append(f"| {r['archivo']} | {r['filas']:,} | {r['filas_gobierno_local']:,} | "
                    f"{r['filas_local_proyecto']:,} | {r['anio_eje_distinto_nombre_archivo']:,} |")
    text += ["", "## Suficiencia inicial (NO representa filas aptas para entrenar)", "",
             f"- Filas de Gasto Devengado de gobiernos locales: **{metrics['filas_locales_gasto']:,}**.",
             f"- Filas locales clasificadas PROYECTO en Gasto Devengado: **{metrics['filas_proyectos_municipales_gasto']:,}**.",
             f"- Entidades-año en Gasto Devengado: **{metrics['entidades_anio_unicas_gasto']:,}**.",
             f"- Claves compartidas entre publicaciones Seguimiento PI: **{metrics['claves_PI_en_ambas_publicaciones']:,}**.",
             "", "## Interpretación y precauciones", "",
             "- En Gasto, cada fila es una línea de clasificación presupuestaria; una fila NO equivale a una obra única.",
             "- En Seguimiento PI, ANO_EJE puede ser histórico dentro del snapshot: no sumar 2024 + 2025 indiscriminadamente.",
             "- Las claves (año, ejecutora, proyecto) repetidas dentro de Gasto pueden ser partidas de un mismo proyecto; NO representan duplicados exactos.",
             "- `SEC_EJEC` no es una feature numérica; es un identificador para agregación.",
             "- Los percentiles en calidad_montos.csv son aproximados con reservoir sampling; mínimos, máximos y conteos son exactos dentro del alcance analizado.",
             "- Montos inválidos/vacíos se excluyeron de sumatorias exploratorias: revisar su volumen antes de entrenar.",
             "- Los indicadores municipales son candidatos y podrían requerir comparación a igual corte temporal.",
             "- El EDA Python no sustituye la implementación concurrente ni K-Means paralelo en Go que exige PC3.",
             "", "## Siguiente decisión", "",
             "1. Comprobar calidad y consistencia de montos y meses de 2025.",
             "2. Validar granularidad y duplicación exacta antes de combinar fuentes.",
             "3. Elegir unidad estadística para K-Means y estrategia de escalamiento."]
    (out_dir / "resumen_eda.md").write_text("\n".join(text) + "\n", encoding="utf-8")
    zip_file = out_dir.parent / f"eda_estadistico_mef_{mode}.zip"
    with zipfile.ZipFile(zip_file, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for file in sorted(out_dir.iterdir()):
            if file.suffix.lower() in {".csv", ".md", ".json"}:
                archive.write(file, arcname=file.name)
    print(f"\nReporte generado: {out_dir / 'resumen_eda.md'}")
    print(f"ZIP para compartir: {zip_file}")
    return {"indicadores": metrics, "archivos": all_summaries, "zip": str(zip_file)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["quick", "full"], default="quick")
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data/raw")
    parser.add_argument("--out-dir", type=Path, default=ROOT / "data/processed/eda_estadistico")
    parser.add_argument("--quick-rows", type=int, default=10_000)
    parser.add_argument("--reservoir", type=int, default=4000)
    parser.add_argument("--progress", type=int, default=500_000)
    args = parser.parse_args()
    if args.quick_rows <= 0 or args.reservoir < 0 or args.progress < 0:
        parser.error("quick-rows debe ser >0 y reservoir/progress >=0")
    try:
        analyze(args.data_dir, args.out_dir, args.mode,
                args.quick_rows, args.reservoir, args.progress)
    except (OSError, ValueError, csv.Error) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
