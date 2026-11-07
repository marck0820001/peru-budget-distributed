#!/usr/bin/env python3
"""Genera gráficos para el informe desde los CSV resumen del EDA.

Opcional: pip install matplotlib
Uso: py scripts/eda/plot_eda.py
No lee los CSV originales del MEF.
"""
from __future__ import annotations
import argparse
import csv
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def read_csv(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def draw_charts(input_dir: Path, output_dir: Path) -> list[Path]:
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError as exc:
        raise RuntimeError("Falta matplotlib. Instalar con: py -m pip install matplotlib") from exc
    output_dir.mkdir(parents=True, exist_ok=True)
    created = []
    yearly_monthly = defaultdict(dict)
    for row in read_csv(input_dir / "evolucion_mensual_local.csv"):
        year = row["ano_eje"]
        month = int(row["numero_mes"])
        yearly_monthly[year][month] = float(row["suma"])
    if yearly_monthly:
        fig, ax = plt.subplots(figsize=(10, 4.5))
        for year, monthly in sorted(yearly_monthly.items()):
            ax.plot(sorted(monthly), [monthly[m]/1e9 for m in sorted(monthly)], marker="o", label=year)
        ax.set(xlabel="Mes del año", ylabel="Devengado (miles de millones S/)",
               title="Devengado mensual de gobiernos locales — registros observados")
        ax.set_xticks(range(1, 13))
        ax.legend(title="ANO_EJE")
        ax.grid(alpha=.2)
        fig.tight_layout()
        path = output_dir / "01_devengado_mensual.png"
        fig.savefig(path, dpi=170)
        plt.close(fig)
        created.append(path)
    rows = read_csv(input_dir / "municipalidades_indicadores_exploratorios.csv")
    ratios = defaultdict(list)
    for row in rows:
        try:
            if row.get("tasa_ejecucion_sobre_pim"):
                v = float(row["tasa_ejecucion_sobre_pim"])
                if 0 <= v <= 2:  # zona mostrada, no exclusión de entrenamiento
                    ratios[row["ano_eje"]].append(v)
        except ValueError:
            continue
    if ratios:
        fig, ax = plt.subplots(figsize=(9, 4.5))
        for year, values in sorted(ratios.items()):
            ax.hist(values, bins=30, alpha=.55, label=year)
        ax.set(xlabel="Devengado / PIM", ylabel="Municipalidades-año",
               title="Distribución de tasa de ejecución (visualización 0 a 2)")
        ax.legend(title="ANO_EJE")
        fig.tight_layout()
        path = output_dir / "02_tasa_ejecucion.png"
        fig.savefig(path, dpi=170)
        plt.close(fig)
        created.append(path)
    cover = read_csv(input_dir / "cobertura_local_departamento.csv")
    dept_counts = defaultdict(int)
    for r in cover:
        if r["dataset"].endswith("gasto"):
            dept_counts[r["departamento"]] += int(r["filas"])
    if dept_counts:
        top = sorted(dept_counts.items(), key=lambda x: x[1], reverse=True)[:15]
        fig, ax = plt.subplots(figsize=(10, 6))
        ax.barh([name for name, _ in reversed(top)], [count/1000 for _, count in reversed(top)])
        ax.set(xlabel="Miles de registros de gobierno local", title="Departamentos — top 15 por registros de gasto")
        fig.tight_layout()
        path = output_dir / "03_cobertura_departamentos.png"
        fig.savefig(path, dpi=170)
        plt.close(fig)
        created.append(path)
    return created


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, default=ROOT/"data/processed/eda_estadistico")
    parser.add_argument("--output-dir", type=Path, default=ROOT/"data/processed/eda_estadistico/graficos")
    args = parser.parse_args()
    for path in draw_charts(args.input_dir, args.output_dir):
        print(f"Gráfico: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
