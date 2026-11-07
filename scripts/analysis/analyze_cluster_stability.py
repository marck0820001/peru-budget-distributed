#!/usr/bin/env python3
"""Analiza estabilidad de K-Means y describe clústeres en escala original.

Solo usa Python estándar. Los clústeres se comparan mediante ARI, que no depende
los números arbitrarios de los clústeres. No mezcla filas de años diferentes.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import re
import statistics
from collections import Counter, defaultdict
from itertools import combinations
from pathlib import Path

FEATURES = (
    "tasa_ejecucion", "modificacion_log_pim_pia",
    "participacion_devengado_proyectos", "concentracion_q4",
    "cv_devengado_mensual", "log1p_pim",
)
RAW_MONEY = ("pia_soles", "pim_soles", "devengado_soles")
KEY = ("ano_eje", "sec_ejec")


def read_rows(path: Path):
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            raise ValueError(f"CSV sin encabezado: {path}")
        for r in reader:
            yield r


def key_of(r):
    return tuple(str(r[k]).strip() for k in KEY)


def load_assignments(path: Path):
    data = {}
    for row in read_rows(path):
        key = key_of(row)
        if key in data:
            raise ValueError(f"Clave ejecutora-año duplicada {key} en {path}")
        cluster = int(row["cluster"])
        if cluster < 0:
            raise ValueError(f"Clúster negativo en {path}: {key}")
        d = float(row["distancia_centroide"])
        if not math.isfinite(d) or d < 0:
            raise ValueError(f"Distancia inválida en {path}: {key}")
        data[key] = {"cluster": cluster, "dist": d, "row": row}
    if not data:
        raise ValueError(f"Asignaciones vacías: {path}")
    return data


def choose2(n):
    return n * (n - 1) / 2


def adjusted_rand_index(a: dict, b: dict):
    """ARI desde una tabla de contingencia, con guardas para casos degenerados."""
    if set(a) != set(b):
        raise ValueError("Conjuntos de claves diferentes; ARI requiere mismas observaciones")
    n = len(a)
    if n < 2:
        raise ValueError("ARI requiere al menos dos observaciones")
    cells = Counter((a[k]["cluster"], b[k]["cluster"]) for k in a)
    count_a = Counter(a[k]["cluster"] for k in a)
    count_b = Counter(b[k]["cluster"] for k in a)
    nij = sum(choose2(v) for v in cells.values())
    ai = sum(choose2(v) for v in count_a.values())
    bj = sum(choose2(v) for v in count_b.values())
    expected = ai * bj / choose2(n)
    maximum = (ai + bj) / 2
    denom = maximum - expected
    if abs(denom) < 1e-12:
        return 1.0 if abs(nij - expected) < 1e-12 else 0.0
    return (nij - expected) / denom


def load_audit(path):
    result = {}
    for row in read_rows(path):
        k = key_of(row)
        if k in result:
            raise ValueError(f"Clave duplicada en auditoría: {k}")
        result[k] = row
    return result


def median_of(rows, field):
    vals = []
    for row in rows:
        value = row.get(field, "")
        if value is None or str(value).strip() == "":
            continue
        n = float(value)
        if math.isfinite(n):
            vals.append(n)
    return statistics.median(vals) if vals else None


def short_float(v, places=6):
    return "" if v is None else f"{v:.{places}f}"


def cluster_profiles(assignments, audit, k, seed, out: Path):
    by_cluster = defaultdict(list)
    by_entity = defaultdict(dict)
    far = []
    for entity, v in assignments.items():
        if entity not in audit:
            raise ValueError(f"Asignación sin datos originales: {entity}")
        row = audit[entity]
        if row.get("eligible") != "1":
            raise ValueError(f"Asignación a perfil no elegible: {entity}")
        c = v["cluster"]
        by_cluster[c].append(row)
        by_entity[entity[1]][entity[0]] = c
        far.append({
            "ano_eje": entity[0], "sec_ejec": entity[1],
            "departamento": row.get("departamento", ""),
            "ejecutora_nombre": row.get("ejecutora_nombre", ""),
            "cluster": c, "distancia_centroide": v["dist"],
        })

    if len(by_cluster) != k:
        raise ValueError(f"Se esperaban {k} clústeres, aparecen {len(by_cluster)}")
    profiles = []
    for c, rows in sorted(by_cluster.items()):
        rec = {"k": k, "seed": seed, "cluster": c, "n": len(rows),
               "proporcion": len(rows) / len(assignments),
               "n_2024": sum(r["ano_eje"] == "2024" for r in rows),
               "n_2025": sum(r["ano_eje"] == "2025" for r in rows),
               "departamentos": len({r["departamento"] for r in rows}),
               }
        for name in RAW_MONEY + FEATURES:
            rec["mediana_" + name] = median_of(rows, name)
        profiles.append(rec)
    write_csv(out / f"k{k}_perfiles_por_cluster.csv", profiles)

    transitions = Counter()
    matched = 0
    for entity, years in by_entity.items():
        if "2024" in years and "2025" in years:
            matched += 1
            transitions[(years["2024"], years["2025"])] += 1
    write_csv(out / f"k{k}_transiciones_2024_2025.csv", [
        {"cluster_2024": c0, "cluster_2025": c1, "n": n}
        for (c0, c1), n in sorted(transitions.items())
    ], ["cluster_2024", "cluster_2025", "n"])
    far.sort(key=lambda r: r["distancia_centroide"], reverse=True)
    write_csv(out / f"k{k}_mayores_distancias.csv", far[:20],
              ["ano_eje", "sec_ejec", "departamento", "ejecutora_nombre", "cluster", "distancia_centroide"])
    return profiles, {
        "entidades_en_ambos_anios": matched,
        "cambiaron_cluster": sum(n for (a, b), n in transitions.items() if a != b),
        "nota": "Una transición no implica mejora, deterioro ni irregularidad."
    }


def write_csv(path, records, fields=None):
    records = list(records)
    if fields is None:
        if not records:
            return
        fields = list(records[0].keys())
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(records)


def do_analysis(assignments_dir: Path, audit_file: Path, out: Path, ks: tuple[int,...], seeds: tuple[int,...]):
    out.mkdir(parents=True, exist_ok=True)
    audit = load_audit(audit_file)
    all_summary = {}
    rows_ari = []
    md = ["# Estabilidad y caracterización de K-Means", "",
          "ARI mide coincidencia de particiones y es invariante al nombre de los clústeres.",
          "Las medianas describen valores originales del MEF; no son los centroides escalados.", ""]
    for k in ks:
        models = {}
        for seed in seeds:
            path = assignments_dir / f"k{k}_seed{seed}" / "assignments.csv"
            if not path.exists():
                raise FileNotFoundError(f"No existe: {path}")
            models[seed] = load_assignments(path)
            if len(models[seed]) != 3783:
                raise ValueError(f"Número inesperado de filas en {path}: {len(models[seed])}; se esperaban 3783")
            if len({v["cluster"] for v in models[seed].values()}) != k:
                raise ValueError(f"K inconsistente en {path}")
        aris = []
        for a, b in combinations(seeds, 2):
            v = adjusted_rand_index(models[a], models[b])
            aris.append(v)
            rows_ari.append({"k": k, "seed_a": a, "seed_b": b, "ari": v})
        ref_seed = seeds[0]
        profiles, transitions = cluster_profiles(models[ref_seed], audit, k, ref_seed, out)
        entry = {
            "n_models": len(seeds), "n_pairs": len(aris), "ari_mean": statistics.mean(aris),
            "ari_median": statistics.median(aris), "ari_min": min(aris), "ari_max": max(aris),
            "reference_seed": ref_seed, "reference_profile_sizes": {str(p["cluster"]): p["n"] for p in profiles},
            "transitions": transitions,
        }
        all_summary[str(k)] = entry
        md += [f"## K={k}", "",
               f"- ARI medio entre {len(aris)} pares: **{entry['ari_mean']:.6f}**",
               f"- ARI mínimo: **{entry['ari_min']:.6f}**",
               f"- ARI máximo: **{entry['ari_max']:.6f}**",
               f"- Ejecución de referencia para perfiles originales: semilla {ref_seed}",
               f"- Ejecutoras presentes en 2024 y 2025: {transitions['entidades_en_ambos_anios']}",
               f"- Cambios de clúster entre años: {transitions['cambiaron_cluster']}", "",
               "| Clúster | n | Mediana tasa ejecución | Mediana concentración Q4 | Mediana devengado (S/) |",
               "|---|---:|---:|---:|---:|"]
        for p in profiles:
            md.append(f"| {p['cluster']} | {p['n']} | {short_float(p['mediana_tasa_ejecucion'],4)} | "
                      f"{short_float(p['mediana_concentracion_q4'],4)} | {short_float(p['mediana_devengado_soles'],2)} |")
        md.append("")
    write_csv(out / "ari_pares.csv", rows_ari, ["k", "seed_a", "seed_b", "ari"])
    with (out / "resumen_estabilidad.json").open("w", encoding="utf-8") as f:
        json.dump(all_summary, f, ensure_ascii=False, indent=2)
    (out / "resumen_estabilidad.md").write_text("\n".join(md), encoding="utf-8")
    return all_summary


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--runs", type=Path, default=Path("data/processed/kmeans_go/estabilidad"))
    p.add_argument("--audit", type=Path, default=Path("data/processed/features_mef/municipality_features_audit.csv"))
    p.add_argument("--out", type=Path, default=Path("data/processed/kmeans_go/analisis_estabilidad"))
    p.add_argument("--ks", nargs="+", type=int, default=[2, 3])
    p.add_argument("--seeds", nargs="+", type=int, default=list(range(1, 11)))
    args = p.parse_args()
    summaries = do_analysis(args.runs, args.audit, args.out, tuple(args.ks), tuple(args.seeds))
    print("Análisis de estabilidad completado:")
    for k, v in summaries.items():
        print(f"K={k}: ARI promedio={v['ari_mean']:.6f}, mínimo={v['ari_min']:.6f}; "
              f"cambios 2024-2025={v['transitions']['cambiaron_cluster']}")
    print(f"Archivos en: {args.out}")


if __name__ == "__main__":
    main()
