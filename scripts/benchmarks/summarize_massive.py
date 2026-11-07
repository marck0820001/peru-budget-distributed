"""Resumen reproducible de benchmarks K-Means masivo: sin pandas.

Uso: py scripts/benchmarks/summarize_massive.py
"""
from __future__ import annotations

import argparse
import csv
import statistics
from collections import defaultdict
from pathlib import Path


def summarize(rows: list[dict]) -> list[dict]:
    if not rows:
        raise ValueError("Sin filas de benchmark")
    groups: dict[tuple[int, int], list[dict]] = defaultdict(list)
    for row in rows:
        k, w = int(row["K"]), int(row["Workers"])
        if not k > 1 or not w > 0:
            raise ValueError("K o workers inválidos")
        if str(row["Convergio"]).lower() not in {"true", "false"}:
            raise ValueError("Convergio debe ser true o false")
        groups[(k, w)].append(row)

    output = []
    for k in sorted({k for k, _ in groups}):
        if (k, 1) not in groups:
            raise ValueError(f"Falta referencia secuencial de K={k}")
        all_rows = [r for (group_k, _), g in groups.items() if group_k == k for r in g]
        if len({int(r["Filas"]) for r in all_rows}) != 1:
            raise ValueError(f"Cantidad de filas diferente en K={k}")
        ref = statistics.median(float(r["DuracionMs"]) for r in groups[(k, 1)])
        if ref <= 0:
            raise ValueError("Tiempo de referencia no positivo")
        for _, w in sorted(key for key in groups if key[0] == k):
            g = groups[(k, w)]
            med = statistics.median(float(r["DuracionMs"]) for r in g)
            inertia = [float(r["Inercia"]) for r in g]
            speedup = ref / med if med > 0 else 0
            output.append({
                "k": k,
                "workers": w,
                "repeticiones": len(g),
                "mediana_ms": round(med, 3),
                "speedup": round(speedup, 4),
                "eficiencia": round(speedup / w, 4),
                "inercia_min": min(inertia),
                "inercia_max": max(inertia),
                "iteraciones": ",".join(map(str, sorted({int(r["Iteraciones"]) for r in g}))),
                "convergieron_todas": all(str(r["Convergio"]).lower() == "true" for r in g),
            })
    return output


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--input", default="data/processed/massive_mef/benchmarks_massive.csv")
    p.add_argument("--out", default="data/processed/massive_mef")
    args = p.parse_args()
    with open(args.input, encoding="utf-8-sig", newline="") as f:
        rows = summarize(list(csv.DictReader(f)))
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    dest = out / "benchmarks_resumen.csv"
    with dest.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    lines = ["# Benchmarks K-Means masivo", "", "| K | Workers | Mediana (ms) | Speedup | Eficiencia |", "|---:|---:|---:|---:|---:|"]
    for r in rows:
        lines.append(f"| {r['k']} | {r['workers']} | {r['mediana_ms']:.3f} | {r['speedup']:.3f}x | {r['eficiencia'] * 100:.1f}% |")
    lines += ["", "Tiempos medidos sobre el mismo binario; no comparar contra el ETL del CSV.",
              "Una ejecución no convergida o inercia divergente requiere inspección antes de interpretar speedup."]
    (out / "benchmarks_resumen.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("Resumen generado:", dest)


if __name__ == "__main__":
    main()
