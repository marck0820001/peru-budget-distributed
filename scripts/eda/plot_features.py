#!/usr/bin/env python3
"""Gráficos de EDA de características; requiere `pip install matplotlib`."""
from __future__ import annotations

import argparse
import csv
from collections import Counter
from pathlib import Path

from feature_engineering import ROOT


def plot(output_dir: Path) -> list[Path]:
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError as exc:
        raise SystemExit("Instala matplotlib: py -m pip install matplotlib") from exc

    path = output_dir / "municipality_features_audit.csv"
    with path.open("r", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    eligible = [r for r in rows if r["eligible"] == "1"]
    if not eligible:
        raise ValueError("Sin perfiles elegibles para graficar")
    charts = output_dir / "graficos"
    charts.mkdir(parents=True, exist_ok=True)
    produced = []
    
    fig, ax = plt.subplots(figsize=(9, 5))
    for year in ("2024", "2025"):
        vals = [float(r["tasa_ejecucion"]) for r in eligible if r["ano_eje"] == year]
        # Histograma en dominio visible: extremos se reportan, no se descartan del dataset.
        visible = [min(v, 1.2) for v in vals]
        if visible:
            ax.hist(visible, bins=36, alpha=0.50, label=year)
    ax.set(xlabel="Devengado / PIM (valores superiores a 1.2 en último intervalo)",
           ylabel="Perfiles municipal-año", title="Tasa de ejecución por año")
    ax.legend()
    fig.tight_layout()
    path1 = charts / "01_tasa_ejecucion_por_ano.png"
    fig.savefig(path1, dpi=160)
    plt.close(fig)
    produced.append(path1)

    fig, ax = plt.subplots(figsize=(9, 5))
    for year in ("2024", "2025"):
        items = [r for r in eligible if r["ano_eje"] == year]
        ax.scatter([float(r["log1p_pim"]) for r in items],
                   [float(r["concentracion_q4"]) for r in items],
                   s=7, alpha=0.35, label=year)
    ax.set(xlabel="log(1 + PIM en S/)", ylabel="Devengado oct–dic / devengado anual",
           title="Escala presupuestal y concentración del gasto")
    ax.legend()
    fig.tight_layout()
    path2 = charts / "02_presupuesto_vs_concentracion.png"
    fig.savefig(path2, dpi=160)
    plt.close(fig)
    produced.append(path2)

    count = Counter(r["tipo_entidad"] for r in rows)
    fig, ax = plt.subplots(figsize=(9, 5))
    names = list(count)
    bars = ax.bar(names, [count[k] for k in names])
    ax.bar_label(bars)
    ax.set(ylabel="Perfiles ejecutora-año", title="Clasificación inicial de entidades")
    fig.tight_layout()
    path3 = charts / "03_tipos_de_entidad.png"
    fig.savefig(path3, dpi=160)
    plt.close(fig)
    produced.append(path3)
    return produced


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output-dir", type=Path, default=ROOT / "data/processed/features_mef")
    args = p.parse_args()
    for path in plot(args.output_dir):
        print("Gráfico:", path)


if __name__ == "__main__":
    main()
