#!/usr/bin/env python3
"""Genera el informe Word del Entregable 1 (PC3) a partir de las salidas del
pipeline en Go (cmd/etl, cmd/trainer, cmd/benchmark) y de los logs de pruebas.

Requisitos:  py -m pip install python-docx matplotlib numpy

Uso (desde la raíz del repo, después de correr ETL + trainer + benchmark):
    py scripts/report/build_pc3_report.py --etl data/processed/go_etl \
        --bench data/processed/benchmarks --logs data/processed/logs \
        --out docs/reports/1ACC0065_PC3_202610_Informe_UXXXXXXXX.docx

Con --synthetic el informe declara que las cifras del pipeline Go provienen
del dataset sintético (mismo esquema MEF). Sin esa bandera, se asume que se
ejecutó con los CSV oficiales.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch
import numpy as np
from docx import Document
from docx.enum.section import WD_SECTION
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

# ----------------------------------------------------------------------------
# Datos fijos del equipo y del EDA real (auditoría Python de los CSV oficiales)
# ----------------------------------------------------------------------------
TEAM = [
    # (nombre, código, rol principal en PC3, % participación)
    ("David Serrudo", "UXXXXXXXX", "Cargador concurrente con parseo en workers y K-Means MapReduce (silueta, atípicos) en Go; pruebas, benchmarks e informe", "[ ]"),
    ("Marco Fuentes", "UXXXXXXXX", "Auditoría de volumen, EDA, preprocesamiento y feature engineering (Python); auditoría concurrente y K-Means masivo sobre 3.64 M líneas en Go; estructura del repositorio", "[ ]"),
    ("Alexis Davila", "UXXXXXXXX", "[completar]", "[ ]"),
]
REPO = "https://github.com/marck0820001/peru-budget-distributed"
EDA_REAL = {  # docs/datasets/02-eda-estadistico-plan.md (rama feature/eda-preprocessing)
    "gasto_2024_total": 2_789_756, "gasto_2024_local": 1_829_290, "gasto_2024_proy": 293_159,
    "gasto_2025_total": 2_807_176, "gasto_2025_local": 1_813_220, "gasto_2025_proy": 285_797,
    "pi_2024_total": 722_358, "pi_2024_local": 632_761,
    "pi_2025_total": 708_068, "pi_2025_local": 619_257,
    "local_total": 3_642_510, "proy_total": 578_956,
    "exec_2024": 75.82, "exec_2025": 80.64,
}
MASSIVE_DOC = {  # docs/evidence/validacion-kmeans-masivo.md (ejecución real de Marco)
    "rows": 3_642_510, "project_rows": 578_956, "k": 3, "iterations": 8, "inertia": 15719788.266976278,
    "sizes": [1502969, 1037720, 1101821],
    "profile": [  # % del cluster: proyectos, PIM = 0, devengado = 0
        {"proy": 17.23, "pim0": 95.98, "dev0": 0.00}, {"proy": 3.97, "pim0": 48.30, "dev0": 99.33},
        {"proy": 25.30, "pim0": 5.56, "dev0": 97.22}],
    "bench": {1: 4641, 2: 3150, 4: 2633, 8: 1943},          # ms (mediana de 3)
    "audit": {1: [24.948, 24.949, 24.668], 2: [26.019, 26.047, 27.049],  # benchmarks_etl.csv
              4: [26.078, 26.293, 26.491], 8: [26.298, 26.071, 26.723]},
}
FEATURE_LABEL = {
    "tasa_ejecucion": "Tasa de ejecución (devengado / PIM)",
    "modificacion_log_pim_pia": "Modificación presupuestal log(1+PIM) − log(1+PIA)",
    "participacion_devengado_proyectos": "Participación de proyectos en el devengado",
    "concentracion_q4": "Concentración del gasto en oct–dic",
    "cv_devengado_mensual": "Coef. de variación del devengado mensual",
    "log1p_pim": "Escala del presupuesto log(1+PIM)",
}
SHORT = {
    "tasa_ejecucion": "Ejecución", "modificacion_log_pim_pia": "Modificación",
    "participacion_devengado_proyectos": "% proyectos", "concentracion_q4": "Conc. Q4",
    "cv_devengado_mensual": "CV mensual", "log1p_pim": "log PIM",
}
ACCENT = "#B5121B"   # rojo UPC
INK = "#1F2937"
PALETTE = ["#2563EB", "#16A34A", "#F59E0B", "#9333EA", "#0891B2", "#DC2626", "#4B5563", "#DB2777", "#65A30D", "#7C3AED"]


# ----------------------------------------------------------------------------
# Utilidades de lectura
# ----------------------------------------------------------------------------
def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def median(xs):
    xs = sorted(xs); n = len(xs)
    return xs[n // 2] if n % 2 else (xs[n // 2 - 1] + xs[n // 2]) / 2


def load_massive(mdir: Path, audit_csv: Path) -> dict:
    """Lee los reportes del experimento masivo de Marco; si faltan, usa los valores documentados."""
    out = {"source": "documentado", **{k: MASSIVE_DOC[k] for k in ("rows", "project_rows", "k", "iterations", "inertia", "sizes")}}
    out["profile"] = MASSIVE_DOC["profile"]
    out["bench"] = dict(MASSIVE_DOC["bench"]); out["audit"] = {w: list(v) for w, v in MASSIVE_DOC["audit"].items()}
    try:
        files = sorted(mdir.glob("training_k*_w*_seed*.json"))
        if files:
            tr = json.loads(files[0].read_text(encoding="utf-8"))
            out.update(rows=tr["rows"], k=tr["k"], iterations=tr["iterations"], inertia=tr["inertia"], sizes=tr["cluster_sizes"], source="medido")
        pf = list(mdir.glob("profile_k*_seed*.json"))
        if pf:
            pr = json.loads(pf[0].read_text(encoding="utf-8"))
            out["profile"] = [{"proy": c["mean_original_features"][6] * 100, "pim0": c["mean_original_features"][7] * 100,
                               "dev0": c["mean_original_features"][8] * 100} for c in pr["clusters"]]
        bm = mdir / "benchmarks_massive.csv"
        if bm.exists():
            by = {}
            for r in read_csv(bm):
                by.setdefault(int(r["Workers"]), []).append(float(r["DuracionMs"]))
            out["bench"] = {w: median(v) for w, v in by.items()}
    except Exception as exc:  # reportes incompletos: se conserva lo documentado
        print("aviso: reportes masivos incompletos, uso valores documentados:", exc)
    if audit_csv.exists():
        by = {}
        for r in read_csv(audit_csv):
            by.setdefault(int(r["Workers"]), []).append(float(r["Segundos"]))
        out["audit"] = by
    return out


def fig_massive(path: Path, m: dict, speed: list, synthetic: bool = False):
    fig, axes = plt.subplots(1, 2, figsize=(11, 3.9))
    ax = axes[0]
    w = sorted(m["bench"]); sp = [m["bench"][1] / m["bench"][x] for x in w]
    ax.plot(w, sp, "o-", color="#2563EB", lw=2, label="K-Means masivo (3.64 M líneas)")
    ax.plot(w, w, ":", color="#9CA3AF", label="ideal (lineal)")
    for a, b in zip(w, sp):
        ax.text(a, b + 0.12, f"{b:.2f}×", ha="center", fontsize=8)
    ax.set_xticks(w); ax.set_xlabel("workers (goroutines)"); ax.set_ylabel("speedup vs. 1 worker")
    ax.set_title("Entrenamiento K-Means sobre 3 642 510 líneas", fontsize=10); ax.legend(frameon=False, fontsize=8)
    ax.spines[["top", "right"]].set_visible(False)
    ax = axes[1]
    w = sorted(m["audit"]); base = median(m["audit"][1])
    sp = [base / median(m["audit"][x]) for x in w]
    ax.plot(w, sp, "s-", color="#DC2626", lw=2, label="auditoría ETL con lector CSV único")
    etl = [x for x in speed if x["etapa"] == "etl" and x["configuracion"] != "secuencial"]
    if etl:
        ax.plot([int(x["workers"]) for x in etl], [float(x["speedup"]) for x in etl], "o-", color="#16A34A", lw=2,
                label="cargador con parseo en workers" + (" (datos sintéticos)" if synthetic else ""))
    ax.plot(w, w, ":", color="#9CA3AF", label="ideal (lineal)")
    ax.set_xticks(w); ax.set_xlabel("workers (goroutines)"); ax.set_ylabel("speedup vs. 1 worker")
    ax.set_title("ETL: dónde se paraleliza importa", fontsize=10); ax.legend(frameon=False, fontsize=8)
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout(); fig.savefig(path, dpi=200); plt.close(fig)


def fmt_int(v) -> str:
    return f"{int(v):,}".replace(",", " ")


def fmt_pct(v: float, d: int = 2) -> str:
    return f"{v * 100:.{d}f} %"


# ----------------------------------------------------------------------------
# Figuras
# ----------------------------------------------------------------------------
def box(ax, x, y, w, h, text, fc, ec=INK, fs=9, bold=False, lw=1.2):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.02,rounding_size=0.08",
                                fc=fc, ec=ec, lw=lw))
    ax.text(x + w / 2, y + h / 2, text, ha="center", va="center", fontsize=fs,
            color=INK, fontweight="bold" if bold else "normal", wrap=True)


def arrow(ax, x1, y1, x2, y2, text="", color=INK, fs=8, style="-|>"):
    ax.annotate("", xy=(x2, y2), xytext=(x1, y1),
                arrowprops=dict(arrowstyle=style, color=color, lw=1.3))
    if text:
        ax.text((x1 + x2) / 2, (y1 + y2) / 2 + 0.12, text, ha="center", va="bottom", fontsize=fs, color=color)


def fig_architecture(path: Path):
    fig, ax = plt.subplots(figsize=(11, 5.2))
    ax.set_xlim(0, 11); ax.set_ylim(0, 5.4); ax.axis("off")
    ax.add_patch(FancyBboxPatch((0.15, 0.15), 10.7, 5.0, boxstyle="round,pad=0.02,rounding_size=0.15",
                                fc="#F9FAFB", ec="#9CA3AF", lw=1, ls="--"))
    ax.text(5.5, 4.95, "Docker Compose (TB2)", ha="center", fontsize=9, color="#6B7280")
    box(ax, 0.4, 3.4, 1.7, 1.1, "CSV MEF\nGasto Devengado\n2024 · 2025\n(~2.6 GB c/u)", "#FEF3C7")
    box(ax, 2.6, 3.3, 2.5, 1.3, "Parte A\nCargador concurrente\n(goroutines + channels)\ncmd/etl", "#DBEAFE", ec=ACCENT, bold=True, lw=2.2)
    box(ax, 5.6, 3.3, 2.3, 1.3, "Parte B\nK-Means paralelo\n(MapReduce)\ncmd/trainer", "#DCFCE7", ec=ACCENT, bold=True, lw=2.2)
    box(ax, 8.4, 3.4, 2.2, 1.1, "Clúster nodos ML\nGo TCP (PC4)", "#EDE9FE")
    box(ax, 2.6, 0.6, 2.5, 1.2, "Parte D\nSPA React (TB2)\ndashboard e impacto", "#FCE7F3")
    box(ax, 5.6, 0.6, 2.3, 1.2, "Parte C\nAPI coordinador\nREST/WebSocket (PC4)", "#FEF9C3")
    box(ax, 8.4, 0.6, 2.2, 1.2, "MongoDB (persistente)\nRedis (caché)\n(PC4)", "#FEE2E2")
    box(ax, 0.4, 0.75, 1.7, 0.9, "Usuario\n(navegador)", "#F3F4F6")
    arrow(ax, 2.1, 3.95, 2.6, 3.95, "bloques")
    arrow(ax, 5.1, 3.95, 5.6, 3.95, "matriz")
    arrow(ax, 7.9, 3.95, 8.4, 3.95, "TCP")
    arrow(ax, 6.75, 3.3, 6.75, 1.8, "modelo")
    arrow(ax, 7.9, 1.2, 8.4, 1.2, "")
    arrow(ax, 5.6, 1.2, 5.1, 1.2, "JSON/WS")
    arrow(ax, 2.1, 1.2, 2.6, 1.2, "HTTP")
    ax.text(5.5, 2.55, "Borde rojo = alcance implementado en el Entregable 1 (PC3)", ha="center", fontsize=9, color=ACCENT)
    fig.tight_layout(); fig.savefig(path, dpi=200); plt.close(fig)


def fig_pipeline(path: Path, workers: int = 4):
    fig, ax = plt.subplots(figsize=(11, 4.6))
    ax.set_xlim(0, 11); ax.set_ylim(-0.3, 4.8); ax.axis("off")
    box(ax, 0.2, 1.9, 1.4, 1.0, "Archivo CSV\n(disco)", "#FEF3C7")
    box(ax, 2.0, 1.8, 1.7, 1.2, "Split\n1 goroutine\nlee + corta bloques", "#DBEAFE", bold=True)
    ax.text(4.25, 2.95, "chan Chunk\n(cap. 2×N →\nbackpressure)", ha="center", fontsize=8)
    ys = np.linspace(4.0, 1.05, workers)
    for i, y in enumerate(ys):
        box(ax, 5.0, y - 0.32, 2.0, 0.64, f"worker {i + 1}: parse · valida\n· agrega en mapa local", "#E0F2FE", fs=8)
        arrow(ax, 3.7, 2.4, 5.0, y)
        arrow(ax, 7.0, y, 8.2, 2.4)
    box(ax, 8.2, 1.8, 1.4, 1.2, "Reduce\nfan-in\nMerge()", "#DCFCE7", bold=True)
    box(ax, 9.85, 1.9, 1.0, 1.0, "Perfiles\nejecutora-\naño", "#F3F4F6", fs=8)
    arrow(ax, 9.6, 2.4, 9.85, 2.4)
    ax.text(7.6, 4.45, "chan *partial", ha="center", fontsize=8)
    box(ax, 5.0, -0.2, 2.0, 0.42, "DupDetector: 64 shards × sync.Mutex", "#FEE2E2", fs=7.5)
    box(ax, 8.2, 0.1, 2.6, 0.6, "chan Incident → 1 goroutine escritor\n(incidencias_preprocesamiento.csv)", "#FEF9C3", fs=7.5)
    fig.tight_layout(); fig.savefig(path, dpi=200); plt.close(fig)


def fig_mapreduce(path: Path, workers: int = 4):
    fig, ax = plt.subplots(figsize=(11, 4.4))
    ax.set_xlim(0, 11); ax.set_ylim(0, 4.6); ax.axis("off")
    box(ax, 0.2, 1.7, 2.0, 1.3, "Coordinador\ncentroides C(t)\n(snapshot inmutable)", "#DCFCE7", bold=True)
    ys = np.linspace(3.8, 0.6, workers)
    for i, y in enumerate(ys):
        box(ax, 3.6, y - 0.35, 3.0, 0.7, f"MAP · worker {i + 1}: filas [lo{i + 1}, hi{i + 1})\nasigna al centroide más cercano", "#E0F2FE", fs=8)
        arrow(ax, 2.2, 2.35, 3.6, y, "C(t)" if i == 0 else "", fs=8)
        arrow(ax, 6.6, y, 7.9, 2.35, "Partial" if i == 0 else "", fs=8)
    box(ax, 7.9, 1.6, 2.9, 1.5, "REDUCE (barrera)\nΣ sumas / Σ conteos\nen orden de partición\n→ C(t+1), inercia", "#DCFCE7", bold=True)
    ax.annotate("", xy=(1.2, 1.7), xytext=(9.3, 1.6),
                arrowprops=dict(arrowstyle="-|>", color=ACCENT, lw=1.3, connectionstyle="arc3,rad=0.35"))
    ax.text(5.3, 0.02, "siguiente iteración hasta converger (sin cambios de etiqueta o desplazamiento < tol)", ha="center", fontsize=8.5, color=ACCENT)
    fig.tight_layout(); fig.savefig(path, dpi=200); plt.close(fig)


def fig_funnel(path: Path, rep: dict):
    t = rep["totals"]
    labels = ["Filas leídas\n(2 archivos)", "Gobierno local\n(NIVEL = M)", "Aceptadas\n(limpias)", "Perfiles\nejecutora-año", "Elegibles\nK-Means"]
    vals = [t["rows_read"], t["local_rows"], t["local_accepted"], rep["municipality_year_profiles"], rep["eligible_profiles"]]
    fig, ax = plt.subplots(figsize=(10, 3.8))
    bars = ax.barh(range(len(vals))[::-1], vals, color=["#9CA3AF", "#60A5FA", "#2563EB", "#16A34A", "#15803D"])
    ax.set_xscale("log"); ax.set_yticks(range(len(vals))[::-1]); ax.set_yticklabels(labels, fontsize=9)
    for b, v in zip(bars, vals):
        ax.text(v * 1.08, b.get_y() + b.get_height() / 2, fmt_int(v), va="center", fontsize=9)
    ax.set_xlabel("registros (escala log)"); ax.set_xlim(1000, max(vals) * 4)
    ax.spines[["top", "right"]].set_visible(False)
    ax.set_title("De líneas presupuestarias a perfiles municipales", fontsize=11)
    fig.tight_layout(); fig.savefig(path, dpi=200); plt.close(fig)


def fig_monthly(path: Path, rep: dict):
    months = ["Ene", "Feb", "Mar", "Abr", "May", "Jun", "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"]
    fig, ax = plt.subplots(figsize=(10, 3.6))
    for i, (y, vals) in enumerate(sorted(rep.get("monthly_devengado_soles_by_year", {}).items())):
        tot = sum(vals)
        ax.plot(months, [v / tot * 100 for v in vals], marker="o", color=PALETTE[i], label=y, lw=2)
    ax.axvspan(8.5, 11.5, color=ACCENT, alpha=0.07)
    ax.text(10, ax.get_ylim()[1] * 0.92, "último trimestre", ha="center", color=ACCENT, fontsize=8)
    ax.set_ylabel("% del devengado anual"); ax.legend(frameon=False)
    ax.spines[["top", "right"]].set_visible(False); ax.grid(axis="y", alpha=0.3)
    ax.set_title("Distribución mensual del devengado municipal", fontsize=11)
    fig.tight_layout(); fig.savefig(path, dpi=200); plt.close(fig)


def fig_features(path: Path, audit: list[dict], names: list[str]):
    el = [r for r in audit if r["eligible"] == "1"]
    fig, axes = plt.subplots(2, 3, figsize=(11, 5.4))
    for ax, n in zip(axes.flat, names):
        v = np.array([float(r[n]) for r in el if r[n] != ""])
        lo, hi = np.percentile(v, [0.5, 99.5])
        ax.hist(np.clip(v, lo, hi), bins=40, color="#2563EB", alpha=0.85)
        ax.set_title(SHORT.get(n, n), fontsize=10)
        ax.spines[["top", "right"]].set_visible(False); ax.tick_params(labelsize=8)
    fig.suptitle("Indicadores sin escalar de los perfiles elegibles (recorte visual p0.5–p99.5)", fontsize=11)
    fig.tight_layout(); fig.savefig(path, dpi=200); plt.close(fig)


def fig_k(path: Path, rows: list[dict], chosen: int):
    k = [int(r["k"]) for r in rows]
    fig, ax1 = plt.subplots(figsize=(10, 3.8))
    ax1.plot(k, [float(r["inertia"]) for r in rows], "o-", color="#2563EB", lw=2, label="Inercia (codo)")
    ax1.set_xlabel("K"); ax1.set_ylabel("Inercia", color="#2563EB")
    ax2 = ax1.twinx()
    ax2.plot(k, [float(r["silhouette"]) for r in rows], "s-", color="#16A34A", lw=2, label="Silueta")
    ax2.plot(k, [float(r["davies_bouldin"]) for r in rows], "^--", color="#F59E0B", lw=1.5, label="Davies-Bouldin")
    ax2.set_ylabel("Silueta / Davies-Bouldin")
    ax1.axvline(chosen, color=ACCENT, ls=":", lw=1.5)
    ax1.text(chosen + 0.1, ax1.get_ylim()[1] * 0.95, f"K = {chosen}", color=ACCENT, fontsize=9, va="top")
    h1, l1 = ax1.get_legend_handles_labels(); h2, l2 = ax2.get_legend_handles_labels()
    ax1.legend(h1 + h2, l1 + l2, frameon=False, loc="upper center", ncol=3, fontsize=9)
    ax1.set_title("Selección de K", fontsize=11)
    fig.tight_layout(); fig.savefig(path, dpi=200); plt.close(fig)


def fig_clusters(path: Path, X: np.ndarray, labels: np.ndarray, anom: np.ndarray, names_by_c: dict):
    Xc = X - X.mean(axis=0)
    _, s, vt = np.linalg.svd(Xc, full_matrices=False)
    P = Xc @ vt[:2].T
    var = (s ** 2) / (s ** 2).sum()
    fig, ax = plt.subplots(figsize=(10, 5.2))
    for c in sorted(set(labels)):
        m = (labels == c) & ~anom
        ax.scatter(P[m, 0], P[m, 1], s=7, alpha=0.55, color=PALETTE[c % len(PALETTE)], label=f"C{c}: {names_by_c[c]}")
    ax.scatter(P[anom, 0], P[anom, 1], s=26, facecolors="none", edgecolors="black", lw=0.9, label="atípico")
    ax.set_xlabel(f"Componente principal 1 ({var[0] * 100:.0f} % var.)")
    ax.set_ylabel(f"Componente principal 2 ({var[1] * 100:.0f} % var.)")
    ax.legend(frameon=False, fontsize=8, markerscale=2, loc="best")
    ax.spines[["top", "right"]].set_visible(False)
    ax.set_title("Perfiles municipales proyectados en 2D (PCA) y coloreados por cluster", fontsize=11)
    fig.tight_layout(); fig.savefig(path, dpi=200); plt.close(fig)


def fig_heatmap(path: Path, model: dict, names: list[str], names_by_c: dict):
    C = np.array(model["centroids_scaled"])
    fig, ax = plt.subplots(figsize=(10, 0.7 * len(C) + 1.6))
    lim = max(1.0, np.abs(C).max())
    im = ax.imshow(C, cmap="RdBu_r", vmin=-lim, vmax=lim, aspect="auto")
    ax.set_xticks(range(len(names))); ax.set_xticklabels([SHORT.get(n, n) for n in names], fontsize=9)
    ax.set_yticks(range(len(C))); ax.set_yticklabels([f"C{c} · {names_by_c[c]}" for c in range(len(C))], fontsize=9)
    for i in range(C.shape[0]):
        for j in range(C.shape[1]):
            ax.text(j, i, f"{C[i, j]:+.2f}", ha="center", va="center", fontsize=8,
                    color="white" if abs(C[i, j]) > lim * 0.6 else INK)
    fig.colorbar(im, ax=ax, fraction=0.025, label="centroide escalado (unidades IQR)")
    ax.set_title("Perfil de cada cluster (0 = mediana nacional)", fontsize=11)
    fig.tight_layout(); fig.savefig(path, dpi=200); plt.close(fig)


def fig_speedup(path: Path, rows: list[dict]):
    fig, axes = plt.subplots(1, 2, figsize=(11, 3.9))
    for ax, stage, title in ((axes[0], "etl", "ETL concurrente (5.6 M filas)"), (axes[1], "kmeans", "K-Means paralelo")):
        r = [x for x in rows if x["etapa"] == stage and x["configuracion"] != "secuencial"]
        if not r:
            continue
        w = [int(x["workers"]) for x in r]
        sp = [float(x["speedup"]) for x in r]
        ax.plot(w, sp, "o-", color="#2563EB", lw=2, label="speedup medido")
        ax.plot(w, w, ":", color="#9CA3AF", label="ideal (lineal)")
        cpu = int(r[0]["num_cpu"])
        ax.axvline(cpu, color=ACCENT, ls="--", lw=1)
        ax.text(cpu, max(w) * 0.92, f" núcleos = {cpu}", color=ACCENT, fontsize=8)
        for a, b in zip(w, sp):
            ax.text(a, b + 0.12, f"{b:.2f}×", ha="center", fontsize=8)
        ax.set_xticks(w); ax.set_xlabel("workers (goroutines)"); ax.set_ylabel("speedup vs. secuencial")
        n = r[0]["n"]
        ax.set_title(title if stage == "etl" else f"{title} (N = {fmt_int(n)})", fontsize=10)
        ax.legend(frameon=False, fontsize=8); ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout(); fig.savefig(path, dpi=200); plt.close(fig)


def fig_convergence(path: Path, model: dict):
    h = model["history"]
    fig, ax = plt.subplots(figsize=(10, 3.2))
    ax.plot([x["iter"] for x in h], [x["inertia"] for x in h], "o-", color="#16A34A", lw=2, label="inercia")
    ax2 = ax.twinx()
    ax2.bar([x["iter"] for x in h], [x["changed"] for x in h], color="#93C5FD", alpha=0.6, label="perfiles que cambian de cluster")
    ax.set_zorder(ax2.get_zorder() + 1); ax.patch.set_visible(False)
    ax.set_xlabel("iteración"); ax.set_ylabel("inercia"); ax2.set_ylabel("cambios de etiqueta")
    h1, l1 = ax.get_legend_handles_labels(); h2, l2 = ax2.get_legend_handles_labels()
    ax.legend(h1 + h2, l1 + l2, frameon=False, fontsize=8, loc="upper right")
    ax.set_title("Convergencia del K-Means paralelo", fontsize=11)
    fig.tight_layout(); fig.savefig(path, dpi=200); plt.close(fig)


def terminal_image(path: Path, text: str, title: str, max_lines: int = 34):
    lines = text.expandtabs(8).rstrip().splitlines()
    if len(lines) > max_lines:
        lines = lines[: max_lines - 1] + ["…"]
    lines = [ln if len(ln) <= 132 else ln[:129] + "…" for ln in lines]
    h = 0.6 + 0.205 * len(lines)
    fig = plt.figure(figsize=(11, h))
    fig.patch.set_facecolor("#0F172A")
    fig.text(0.012, 1 - 0.28 / h, "● ● ●  " + title, color="#94A3B8", fontsize=8.5, family="monospace", va="top", parse_math=False)
    for i, ln in enumerate(lines):
        color = "#E2E8F0"
        if ln.startswith("ok") or "PASS" in ln or "true" in ln:
            color = "#86EFAC"
        if ln.startswith("$"):
            color = "#FDE68A"
        if "FAIL" in ln:
            color = "#FCA5A5"
        fig.text(0.012, 1 - (0.55 + 0.205 * i) / h, ln, color=color, fontsize=7.6, family="monospace", va="top", parse_math=False)
    fig.savefig(path, dpi=200, facecolor=fig.get_facecolor()); plt.close(fig)


# ----------------------------------------------------------------------------
# Construcción del documento
# ----------------------------------------------------------------------------
class Report:
    def __init__(self):
        self.doc = Document()
        self.fig_n = 0
        self.tab_n = 0
        sec = self.doc.sections[0]
        sec.page_height, sec.page_width = Cm(29.7), Cm(21.0)
        sec.left_margin = sec.right_margin = Cm(2.5)
        sec.top_margin = sec.bottom_margin = Cm(2.3)
        st = self.doc.styles["Normal"]
        st.font.name = "Calibri"; st.font.size = Pt(11)
        st.element.rPr.rFonts.set(qn("w:eastAsia"), "Calibri")
        st.paragraph_format.space_after = Pt(6)
        st.paragraph_format.line_spacing = 1.15
        for lvl, size, color in ((1, 15, "B5121B"), (2, 12.5, "1F2937"), (3, 11.5, "374151")):
            h = self.doc.styles[f"Heading {lvl}"]
            h.font.name = "Calibri"; h.font.size = Pt(size); h.font.bold = True
            h.font.color.rgb = RGBColor.from_string(color)
            h.element.rPr.rFonts.set(qn("w:eastAsia"), "Calibri")
            h.paragraph_format.space_before = Pt(14 if lvl == 1 else 10)
            h.paragraph_format.space_after = Pt(6)
            h.paragraph_format.keep_with_next = True

    def p(self, text: str = "", bold_prefix: str | None = None, italic=False, size=None, align=None, after=None):
        para = self.doc.add_paragraph()
        if bold_prefix:
            r = para.add_run(bold_prefix); r.bold = True
            if size: r.font.size = Pt(size)
        self._rich(para, text, italic=italic, size=size)
        if align == "center":
            para.alignment = WD_ALIGN_PARAGRAPH.CENTER
        elif align == "justify" or align is None:
            para.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
        if after is not None:
            para.paragraph_format.space_after = Pt(after)
        return para

    def _rich(self, para, text, italic=False, size=None):
        # **negrita** y `código`
        parts = []
        buf, mode, i = "", None, 0
        while i < len(text):
            if text.startswith("**", i):
                parts.append((buf, mode)); buf = ""
                mode = None if mode == "b" else "b"; i += 2; continue
            if text[i] == "`":
                parts.append((buf, mode)); buf = ""
                mode = None if mode == "c" else "c"; i += 1; continue
            buf += text[i]; i += 1
        parts.append((buf, mode))
        for t, m in parts:
            if not t:
                continue
            r = para.add_run(t)
            r.italic = italic
            if size: r.font.size = Pt(size)
            if m == "b": r.bold = True
            if m == "c":
                r.font.name = "Consolas"; r.font.size = Pt(9.5)
                r.font.color.rgb = RGBColor(0x9D, 0x17, 0x4D)

    def bullets(self, items: list[str], style="List Bullet"):
        for it in items:
            para = self.doc.add_paragraph(style=style)
            para.paragraph_format.space_after = Pt(3)
            self._rich(para, it)

    def h(self, text: str, lvl: int = 1):
        return self.doc.add_heading(text, level=lvl)

    def figure(self, path: Path, caption: str, width_cm: float = 16.0):
        self.fig_n += 1
        para = self.doc.add_paragraph(); para.alignment = WD_ALIGN_PARAGRAPH.CENTER
        para.paragraph_format.keep_with_next = True
        para.add_run().add_picture(str(path), width=Cm(width_cm))
        cap = self.doc.add_paragraph(); cap.alignment = WD_ALIGN_PARAGRAPH.CENTER
        r = cap.add_run(f"Figura {self.fig_n}. "); r.bold = True; r.font.size = Pt(9)
        r2 = cap.add_run(caption); r2.italic = True; r2.font.size = Pt(9)

    def table(self, header: list[str], rows: list[list], caption: str, widths: list[float] | None = None,
              font=9, align_right: set[int] | None = None):
        self.tab_n += 1
        cap = self.doc.add_paragraph(); cap.paragraph_format.keep_with_next = True
        r = cap.add_run(f"Tabla {self.tab_n}. "); r.bold = True; r.font.size = Pt(9)
        r2 = cap.add_run(caption); r2.italic = True; r2.font.size = Pt(9)
        t = self.doc.add_table(rows=1, cols=len(header))
        t.style = "Table Grid"; t.alignment = WD_TABLE_ALIGNMENT.CENTER
        align_right = align_right or set()
        for i, hd in enumerate(header):
            c = t.rows[0].cells[i]
            c.text = ""
            run = c.paragraphs[0].add_run(str(hd)); run.bold = True; run.font.size = Pt(font)
            run.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
            shade(c, "B5121B")
        for ri, row in enumerate(rows):
            cells = t.add_row().cells
            for i, v in enumerate(row):
                cells[i].text = ""
                para = cells[i].paragraphs[0]
                self._rich(para, str(v), size=font)
                for run in para.runs:
                    run.font.size = Pt(font) if run.font.name != "Consolas" else Pt(font - 0.5)
                if i in align_right:
                    para.alignment = WD_ALIGN_PARAGRAPH.RIGHT
                if ri % 2 == 1:
                    shade(cells[i], "F9FAFB")
        set_widths(t, widths or [16.0 / len(header)] * len(header))
        self.doc.add_paragraph().paragraph_format.space_after = Pt(2)
        return t

    def code(self, text: str, size=8.5):
        t = self.doc.add_table(rows=1, cols=1); t.style = "Table Grid"
        set_widths(t, [16.0])
        c = t.rows[0].cells[0]; shade(c, "F3F4F6")
        c.text = ""
        para = c.paragraphs[0]
        for i, ln in enumerate(text.strip("\n").splitlines()):
            r = para.add_run(ln)
            r.font.name = "Consolas"; r.font.size = Pt(size)
            r._element.rPr.rFonts.set(qn("w:eastAsia"), "Consolas")
            if i < len(text.strip("\n").splitlines()) - 1:
                r.add_break()
        para.paragraph_format.space_after = Pt(0)
        self.doc.add_paragraph().paragraph_format.space_after = Pt(2)

    def note(self, text: str, color="FEF3C7"):
        t = self.doc.add_table(rows=1, cols=1); t.style = "Table Grid"
        set_widths(t, [16.0])
        c = t.rows[0].cells[0]; shade(c, color); c.text = ""
        self._rich(c.paragraphs[0], text, size=10)
        self.doc.add_paragraph().paragraph_format.space_after = Pt(2)

    def page_break(self):
        self.doc.add_paragraph().add_run().add_break(WD_BREAK.PAGE)


def set_widths(t, widths):
    """Fija anchos en la grilla y en cada celda (Word y LibreOffice los respetan)."""
    t.autofit = False  # python-docx escribe <w:tblLayout w:type="fixed"/> en la posición correcta
    for i, w in enumerate(widths):
        t.columns[i].width = Cm(w)
    for row in t.rows:
        for i, w in enumerate(widths):
            row.cells[i].width = Cm(w)


def shade(cell, hex_color: str):
    tcPr = cell._element.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear"); shd.set(qn("w:color"), "auto"); shd.set(qn("w:fill"), hex_color)
    tcPr.append(shd)


def add_page_number_footer(doc):
    for sec in doc.sections:
        para = sec.footer.paragraphs[0]
        para.alignment = WD_ALIGN_PARAGRAPH.CENTER
        r = para.add_run("CC65 · Entregable 1 (PC3) · pág. ")
        r.font.size = Pt(8); r.font.color.rgb = RGBColor(0x6B, 0x72, 0x80)
        run = para.add_run()
        for tag, txt in (("begin", None), (None, "PAGE"), ("end", None)):
            if tag:
                el = OxmlElement("w:fldChar"); el.set(qn("w:fldCharType"), tag)
            else:
                el = OxmlElement("w:instrText"); el.set(qn("xml:space"), "preserve"); el.text = txt
            run._r.append(el)
        run.font.size = Pt(8)


# ----------------------------------------------------------------------------
# Nombres automáticos de clusters según su centroide
# ----------------------------------------------------------------------------
def cluster_names(model: dict, names: list[str]) -> dict[int, str]:
    """Nombra cada cluster con reglas por prioridad sobre su centroide escalado
    (unidades de IQR respecto de la mediana nacional)."""
    out, used = {}, set()
    for c, cent in enumerate(model["centroids_scaled"]):
        z = {n: cent[j] for j, n in enumerate(names)}
        g = lambda n: z.get(n, 0.0)
        if g("tasa_ejecucion") <= -0.75:
            label = "Rezago de ejecución"
        elif g("concentracion_q4") >= 0.75 or g("cv_devengado_mensual") >= 0.75:
            label = "Gasto concentrado al cierre"
        elif g("participacion_devengado_proyectos") >= 0.75:
            label = "Intensivo en inversión" + (" y alta modificación" if g("modificacion_log_pim_pia") >= 0.75 else "")
        elif g("log1p_pim") >= 0.75:
            label = "Gran presupuesto"
        elif g("modificacion_log_pim_pia") >= 0.75:
            label = "Alta modificación presupuestal"
        elif g("tasa_ejecucion") >= 0.3:
            label = "Ejecución sostenida"
        else:
            label = "Perfil intermedio"
        if label in used:
            label += f" ({c})"
        used.add(label)
        out[c] = label
    return out


# ----------------------------------------------------------------------------
def build(args):
    etl, bench, logs, figs = Path(args.etl), Path(args.bench), Path(args.logs), Path(args.figs)
    figs.mkdir(parents=True, exist_ok=True)
    rep = json.loads((etl / "reporte_etl.json").read_text(encoding="utf-8"))
    model = json.loads((etl / "kmeans" / "modelo.json").read_text(encoding="utf-8"))
    ksel = read_csv(etl / "kmeans" / "k_selection.csv") if (etl / "kmeans" / "k_selection.csv").exists() else []
    clusters = read_csv(etl / "kmeans" / "clusters.csv")
    anomalies = read_csv(etl / "kmeans" / "anomalias.csv")
    audit = read_csv(etl / "municipality_features_audit.csv")
    transformer = json.loads((etl / "feature_transformer.json").read_text(encoding="utf-8"))
    speed = read_csv(bench / "speedup.csv") if (bench / "speedup.csv").exists() else []
    massive = load_massive(Path(args.massive), Path(args.audit_bench))
    names = model["features"]
    cnames = cluster_names(model, names)
    X = np.array([[float(v) for v in r.values()] for r in read_csv(etl / "kmeans_matrix.csv")])
    labels = np.array([int(r["cluster"]) for r in clusters])
    anom = np.array([r["atipico"] == "1" for r in clusters])
    t = rep["totals"]
    synthetic = args.synthetic
    src_label = "dataset sintético con el esquema oficial del MEF" if synthetic else "CSV oficiales del MEF"

    # Figuras
    fig_architecture(figs / "f_arquitectura.png")
    fig_pipeline(figs / "f_pipeline.png")
    fig_mapreduce(figs / "f_mapreduce.png")
    fig_funnel(figs / "f_embudo.png", rep)
    fig_monthly(figs / "f_mensual.png", rep)
    fig_features(figs / "f_features.png", audit, names)
    if ksel:
        fig_k(figs / "f_k.png", ksel, model["k"])
    fig_clusters(figs / "f_clusters.png", X, labels, anom, cnames)
    fig_heatmap(figs / "f_heatmap.png", model, names, cnames)
    fig_convergence(figs / "f_convergencia.png", model)
    if speed:
        fig_speedup(figs / "f_speedup.png", speed)
    fig_massive(figs / "f_massive.png", massive, speed, args.synthetic)
    term = {}
    for name, title in (("go_test.txt", "go test -race -v ./..."), ("etl.txt", "go run ./cmd/etlgo --data-dir data/raw"),
                        ("trainer.txt", "go run ./cmd/mrtrainer --in data/processed/go_etl"),
                        ("bench.txt", "go test -bench . -benchmem ./internal/..."), ("git.txt", "git log --oneline --graph --all")):
        if (logs / name).exists():
            terminal_image(figs / f"t_{name[:-4]}.png", (logs / name).read_text(encoding="utf-8", errors="replace"), title)
            term[name] = figs / f"t_{name[:-4]}.png"

    R = Report()
    d = R.doc

    # a) Carátula ---------------------------------------------------------------
    for _ in range(2):
        d.add_paragraph()
    R.p("UNIVERSIDAD PERUANA DE CIENCIAS APLICADAS", bold_prefix=None, size=16, align="center").runs[0].bold = True
    R.p("Facultad de Ingeniería · Carrera de Ciencias de la Computación", size=11, align="center")
    d.add_paragraph()
    R.p("CC65 — Programación Concurrente y Distribuida", size=14, align="center").runs[0].bold = True
    R.p("Trabajo Final · Entregable 1 (PC3)", size=12, align="center")
    d.add_paragraph()
    tp = R.p("PeruBudget Distributed: clustering paralelo de la ejecución presupuestal municipal para detectar desviaciones atípicas en la inversión pública", size=17, align="center")
    for r in tp.runs:
        r.bold = True; r.font.color.rgb = RGBColor(0xB5, 0x12, 0x1B)
    R.p("Caso 6 — Análisis masivo de la ejecución del presupuesto público (MEF, Consulta Amigable de Gasto)", size=10.5, align="center", italic=True)
    d.add_paragraph()
    R.p("Sección: [completar]      Profesor: [completar]", size=11, align="center")
    d.add_paragraph()
    R.p("Integrantes", size=11.5, align="center").runs[0].bold = True
    tt = d.add_table(rows=1, cols=2); tt.style = "Table Grid"; tt.alignment = WD_TABLE_ALIGNMENT.CENTER
    for i, hd in enumerate(("Apellidos y nombres", "Código")):
        c = tt.rows[0].cells[i]; c.text = ""; rr = c.paragraphs[0].add_run(hd); rr.bold = True
        rr.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF); shade(c, "B5121B")
    for n, code, _, _ in TEAM:
        cells = tt.add_row().cells; cells[0].text = n; cells[1].text = code
    set_widths(tt, [8.0, 4.0])
    for _ in range(3):
        d.add_paragraph()
    R.p("Santiago de Surco, 7 de noviembre de 2026", size=11, align="center")
    R.page_break()

    # b) Resumen ------------------------------------------------------------------
    R.h("Resumen")
    clus_txt = "; ".join(f"«{cnames[c]}» ({model['clusters'][c]['size']} perfiles)" for c in range(model["k"]))
    sp_etl = [x for x in speed if x["etapa"] == "etl" and x["configuracion"] != "secuencial"]
    best = max(sp_etl, key=lambda x: float(x["speedup"])) if sp_etl else None
    R.p(
        "Las municipalidades del Perú son el nivel de gobierno con menor ejecución de su presupuesto de inversión: "
        "en 2024 ejecutaron el 68 % frente al 96 % del Gobierno Nacional (Gestión, 2025). Este trabajo construye un "
        "sistema en Go que procesa los datos abiertos de Gasto Devengado del MEF (2024 y 2025) para agrupar a las "
        "municipalidades según su patrón de ejecución y señalar aquellas con un comportamiento atípico que merece revisión. "
        f"El EDA sobre los CSV oficiales identificó **{fmt_int(EDA_REAL['local_total'])} líneas presupuestarias de gobiernos locales** "
        f"(de 5.6 millones de filas), con una ejecución agregada de {EDA_REAL['exec_2024']} % en 2024 y {EDA_REAL['exec_2025']} % en 2025. "
        "En este entregable se implementan la Parte A (cargador concurrente con pipeline, worker pool y fan-in) y la Parte B en su "
        "versión paralela (K-Means MapReduce con goroutines y channels), junto con la limpieza auditable de los datos. "
        f"Sobre el {src_label} ({fmt_int(t['rows_read'])} filas), el ETL produjo {fmt_int(rep['municipality_year_profiles'])} perfiles "
        f"ejecutora-año, de los cuales {fmt_int(rep['eligible_profiles'])} son elegibles para el modelo"
        + (f"; con {best['workers']} workers alcanzó un speedup de {float(best['speedup']):.2f}× frente al secuencial con resultados idénticos" if best else "")
        + f". K-Means seleccionó K = {model['k']} (silueta {model['silhouette']:.3f}): {clus_txt}; "
        f"{model['anomalies']} perfiles ({model['anomalies'] / len(clusters) * 100:.1f} %) quedaron marcados como atípicos. "
        "El diseño del coordinador ya separa el cálculo por particiones, lo que permite distribuirlo por TCP en el Entregable 2."
    )
    R.p("**Palabras clave:** programación concurrente, Go, goroutines, K-Means paralelo, MapReduce, presupuesto público, datos abiertos.")
    if synthetic:
        R.note("**Nota sobre las cifras.** Las cifras del EDA (sección 4.2.1) y del experimento masivo de 3 642 510 líneas (sección 4.5.6) provienen de "
               "ejecuciones sobre los CSV oficiales del MEF. Las cifras del pipeline municipal en Go (ETL, clusters, atípicos y tiempos de las secciones 4.2.3 y 4.5.3–4.5.5) se obtuvieron con un dataset sintético que reproduce "
               "el esquema, el volumen (~2.8 M filas y ~2.6 GB por año) y los problemas de calidad de los archivos oficiales, porque estos "
               "no estaban disponibles en el entorno de ejecución. Se regeneran con `scripts/report/build_pc3_report.py` tras ejecutar el "
               "pipeline sobre los CSV oficiales (anexo B).")
    R.page_break()

    # c) Índice -------------------------------------------------------------------
    R.h("Índice")
    toc = [
        "Resumen", "1. Descripción del problema y motivación", "   1.1 Contexto", "   1.2 Pregunta de impacto social",
        "   1.3 Dataset", "2. Objetivos", "3. Arquitectura de la solución", "4. Desarrollo",
        "   4.1 Presentación del caso", "   4.2 Limpieza y análisis de datos", "   4.3 Diseño del modelo ML distribuido",
        "   4.4 Paralelización del cálculo en Go", "   4.5 Evidencias de implementación y pruebas",
        "   4.6 GitHub (Git Flow) y tablero Kanban", "   4.7 Reporte de participación", "5. Conclusiones",
        "6. Recomendaciones", "7. Bibliografía", "8. Anexos",
    ]
    for line in toc:
        para = d.add_paragraph(line.strip()); para.paragraph_format.space_after = Pt(2)
        if line.startswith("   "):
            para.paragraph_format.left_indent = Cm(0.8)
        else:
            para.runs[0].bold = True
    R.page_break()

    # d) Problema y motivación ---------------------------------------------------
    R.h("1. Descripción del problema y motivación")
    R.h("1.1 Contexto", 2)
    R.p("El presupuesto público peruano se aprueba como Presupuesto Institucional de Apertura (PIA), se modifica durante el año "
        "hasta el Presupuesto Institucional Modificado (PIM) y se ejecuta cuando el gasto se devenga, es decir, cuando se reconoce "
        "la obligación de pago por un bien, servicio u obra recibido. La brecha entre lo que una municipalidad tiene asignado (PIM) "
        "y lo que efectivamente devenga se traduce en obras que no llegan a tiempo a la población.")
    R.p("En 2024 la inversión pública alcanzó S/ 57 742 millones y el país ejecutó el 83 % de su presupuesto de inversión; sin embargo, "
        "los gobiernos locales solo ejecutaron el 68 %, frente al 88 % de los gobiernos regionales y el 96 % del Gobierno Nacional "
        "(Gestión, 2025; Caretas, 2025). Además, el gasto municipal tiende a concentrarse en los últimos meses del año, un patrón que el "
        "EDA del equipo confirmó en los datos oficiales y que suele asociarse a una planificación débil y a mayores riesgos en la calidad de las obras.")
    R.p("Con cerca de 1 900 municipalidades y millones de líneas presupuestarias por año, es inviable revisar caso por caso. Hace falta "
        "un sistema que procese los datos completos con rapidez y agrupe a las municipalidades por patrones de comportamiento, para que la "
        "atención (asistencia técnica, control concurrente, vigilancia ciudadana) se dirija a donde más se necesita.")
    R.h("1.2 Pregunta de impacto social", 2)
    R.note("**¿Qué municipalidades presentan un patrón de ejecución presupuestal atípico (baja ejecución, gasto concentrado a fin de año o "
           "modificaciones extremas de su presupuesto) que justifique priorizar asistencia técnica y seguimiento ciudadano, para que las "
           "obras públicas lleguen a tiempo a su población?**", color="FDE2E4")
    R.p("Beneficiarios directos: la población de los distritos cuyas obras se retrasan, los equipos de asistencia técnica del MEF y de los "
        "gobiernos regionales, la Contraloría (priorización de control) y periodistas y organizaciones de vigilancia ciudadana. "
        "El sistema no acusa irregularidades: produce **alertas para revisión** basadas en datos públicos y verificables.")
    R.h("1.3 Dataset", 2)
    R.table(["Fuente", "Descripción", "Uso en el proyecto"], [
        ["Gasto Devengado 2024 y 2025 (MEF, Datos Abiertos)", "Línea presupuestaria por ejecutora, clasificador y fuente: PIA, PIM, certificado, comprometido, devengado mensual (12 meses) y anual, girado. 73 columnas.", "Fuente principal del clustering municipal (> 1 M registros)."],
        ["Seguimiento de Proyectos de Inversión 2024 y 2025 (MEF)", "Costo actual, ejecución acumulada y anual de proyectos. Contiene snapshots con ANO_EJE históricos.", "Complementaria; no se fusiona hasta validar claves y significado temporal (riesgo de duplicar)."],
    ], "Conjuntos de datos utilizados.", widths=[4.2, 7.0, 4.8])

    # e) Objetivos ---------------------------------------------------------------
    R.h("2. Objetivos")
    R.p("**Objetivo general.** Construir en Go una solución concurrente y distribuida que procese los datos masivos de ejecución presupuestal "
        "del MEF y agrupe a las municipalidades con K-Means paralelo, identificando perfiles con desviación atípica en la ejecución de obras públicas.")
    R.p("**Objetivos específicos del Entregable 1 (PC3):**")
    R.bullets([
        "Analizar y limpiar los datasets del MEF con reglas auditables (céntimos exactos, conciliación mensual, registro de incidencias).",
        "Implementar un cargador concurrente que procese más de 1 millón de registros con goroutines y channels, con un resultado idéntico al secuencial.",
        "Diseñar el modelo K-Means distribuido (MapReduce) y definir los indicadores municipales y su escalamiento.",
        "Implementar el entrenamiento paralelo de K-Means sin condiciones de carrera y medir su speedup.",
        "Evidenciar la implementación con pruebas unitarias, el detector de carreras de Go, benchmarks, Git Flow y el tablero Kanban.",
    ])

    # f) Arquitectura ------------------------------------------------------------
    R.h("3. Arquitectura de la solución")
    R.p("La solución sigue la arquitectura de referencia del curso: cuatro partes encadenadas que se despliegan en contenedores. "
        "En este entregable se implementan las Partes A y B (versión concurrente); el clúster por TCP, la API, las bases de datos y la SPA "
        "corresponden a los Entregables 2 y 3.")
    R.figure(figs / "f_arquitectura.png", "Arquitectura de la solución y alcance del Entregable 1.")
    R.table(["Componente", "Tecnología", "Responsabilidad", "Entregable"], [
        ["Parte A: cargador concurrente", "Go (`cmd/etlgo`, `internal/ingestion`)", "Leer 2 CSV de ~2.6 GB, limpiar, agregar y construir la matriz", "PC3 ✔"],
        ["Parte B: entrenamiento", "Go (`cmd/mrtrainer`, `internal/ml/kmeansmr`, `internal/ml/massive`)", "K-Means paralelo, selección de K, atípicos", "PC3 ✔ (concurrente) · PC4 (TCP)"],
        ["Clúster de nodos ML", "Go + TCP", "Ejecutar la fase map en nodos remotos", "PC4"],
        ["Parte C: API coordinadora", "Go net/http + WebSocket, JWT", "Coordinar el clúster, exponer predicciones (< 100 ms)", "PC4"],
        ["Bases de datos", "MongoDB + Redis", "Persistir resultados y métricas; caché", "PC4"],
        ["Parte D: visualización", "React (SPA)", "Dashboard, resultados, panel admin", "TB2"],
    ], "Componentes y alcance por entregable.", widths=[3.6, 4.0, 5.6, 2.8])

    # g) Desarrollo --------------------------------------------------------------
    R.h("4. Desarrollo")
    R.h("4.1 Presentación del caso", 2)
    R.p("Se trabaja el **Caso 6 — Análisis masivo de la ejecución del presupuesto público**, con el algoritmo recomendado **K-Means paralelo**. "
        "La unidad de análisis es el **perfil ejecutora-año**: una municipalidad en un ejercicio fiscal, resumida en indicadores que "
        "describen cuánto ejecuta, cuándo lo hace, cuánto modifica su presupuesto y qué tan orientada está a proyectos de inversión. "
        "Los millones de líneas son el volumen que procesa el ETL concurrente; el modelo trabaja sobre miles de perfiles interpretables.")

    R.h("4.2 Limpieza y análisis de datos", 2)
    R.h("4.2.1 Auditoría y EDA de los CSV oficiales (Python, auxiliar)", 3)
    R.p("El equipo auditó en streaming los cuatro CSV oficiales (rama `feature/eda-preprocessing`, scripts `audit_volume.py`, "
        "`exploratory_analysis.py`). Los resultados verificados son:")
    e = EDA_REAL
    R.table(["Fuente", "Filas totales", "Gobierno local", "Local + PROYECTO"], [
        ["Gasto Devengado 2024", fmt_int(e["gasto_2024_total"]), fmt_int(e["gasto_2024_local"]), fmt_int(e["gasto_2024_proy"])],
        ["Gasto Devengado 2025", fmt_int(e["gasto_2025_total"]), fmt_int(e["gasto_2025_local"]), fmt_int(e["gasto_2025_proy"])],
        ["Seguimiento PI 2024", fmt_int(e["pi_2024_total"]), fmt_int(e["pi_2024_local"]), "no determinado"],
        ["Seguimiento PI 2025", fmt_int(e["pi_2025_total"]), fmt_int(e["pi_2025_local"]), "no determinado"],
        ["**Total Gasto (local)**", "**" + fmt_int(e["gasto_2024_total"] + e["gasto_2025_total"]) + "**", "**" + fmt_int(e["local_total"]) + "**", "**" + fmt_int(e["proy_total"]) + "**"],
    ], "Volumen real de los datasets del MEF (auditoría del equipo).", widths=[5, 3.6, 3.6, 3.8], align_right={1, 2, 3})
    R.bullets([
        f"El volumen local (**{fmt_int(e['local_total'])}** filas) supera el umbral de 2 M del caso y el requisito general de 1 M.",
        "Cobertura de los 24 departamentos y la Provincia Constitucional del Callao.",
        f"Ejecución agregada municipal (devengado / PIM): **{e['exec_2024']} % en 2024** y **{e['exec_2025']} % en 2025**.",
        "El devengado se concentra en los últimos meses del año (pico en diciembre).",
        "Abundantes líneas con montos en cero y algunos negativos (reversiones contables), que se conservan porque son válidos.",
        "Seguimiento PI 2025 contiene `ANO_EJE` históricos: no se suma ni concatena con PI 2024 sin validar claves (riesgo de duplicar).",
    ])
    R.h("4.2.2 Reglas de limpieza auditables", 3)
    R.p("Las reglas se definieron en Python (`preprocess_data.py`, `feature_engineering.py`) y se **reimplementaron idénticas en Go** "
        "(`internal/preprocessing`, `internal/features`), de modo que ambos pipelines producen archivos con las mismas columnas y se pueden contrastar.")
    R.table(["#", "Regla", "Tratamiento", "Justificación"], [
        ["1", "Nivel de gobierno", "Se retiene `NIVEL_GOBIERNO = M`; R y N se cuentan y descartan", "El caso analiza municipalidades"],
        ["2", "Montos", "Conversión exacta a céntimos enteros (int64); coma decimal o > 2 decimales ⇒ rechazo", "No redondear en silencio; sumas exactas e independientes del orden"],
        ["3", "Conciliación", "Σ 12 meses = devengado anual; si no, la línea va a incidencias", "Detectar filas corruptas o cortes parciales"],
        ["4", "Año y clave", "`ANO_EJE` debe coincidir con el archivo y `SEC_EJEC` no vacío", "Evitar mezclar ejercicios"],
        ["5", "Estructura", "Número de columnas distinto al encabezado ⇒ malformada", "Filas truncadas o unidas"],
        ["6", "Ceros y negativos", "Se conservan y se cuentan", "Son válidos (líneas sin uso, reversiones)"],
        ["7", "Duplicados exactos", "Huella FNV-64 de los 73 campos; se reportan (opción `--drop-duplicates`)", "Una clave repetida no implica duplicado; solo copias idénticas"],
        ["8", "Elegibilidad del perfil", "Solo `MUNICIPALIDAD…`, PIM y devengado > 0, PIA ≥ 0, sin filas excluidas ni metadatos inconsistentes", "Indicadores bien definidos; mancomunidades fuera del modelo"],
        ["9", "Escalamiento", "Winsorización p01–p99 y escalado robusto (mediana/IQR); parámetros guardados en JSON", "Robusto a extremos sin eliminar perfiles"],
    ], "Reglas de limpieza y preprocesamiento.", widths=[0.7, 3.0, 6.3, 6.0], font=8.5)
    R.h("4.2.3 Resultados de la limpieza en Go", 3)
    if synthetic:
        R.p(f"Resultados del ETL concurrente sobre el {src_label}, que incluye problemas de calidad inyectados a propósito "
            "(filas truncadas, montos con coma decimal, montos vacíos, meses que no concilian, años equivocados y duplicados exactos) para verificar cada regla:")
    else:
        R.p("Resultados del ETL concurrente sobre los CSV oficiales:")
    rows = []
    for f in rep["files"]:
        s = f["stats"]
        rows.append([f["file"], fmt_int(s["rows_read"]), fmt_int(s["non_local_rows"]), fmt_int(s["local_rows"]), fmt_int(s["local_accepted"]),
                     fmt_int(s["local_rejected"]), fmt_int(s["malformed_rows"]), fmt_int(s["exact_duplicates_accepted"])])
    rows.append(["**Total**", fmt_int(t["rows_read"]), fmt_int(t["non_local_rows"]), fmt_int(t["local_rows"]), fmt_int(t["local_accepted"]),
                 fmt_int(t["local_rejected"]), fmt_int(t["malformed_rows"]), fmt_int(t["exact_duplicates_accepted"])])
    R.table(["Archivo", "Leídas", "No locales", "Locales", "Aceptadas", "Rechazadas", "Malformadas", "Duplicados"], rows,
            "Conteos del ETL concurrente por archivo.", widths=[3.8, 1.8, 1.7, 1.8, 1.8, 1.7, 1.7, 1.7], font=8, align_right={1, 2, 3, 4, 5, 6, 7})
    me = t.get("money_errors") or {}
    detail = [["Montos inválidos (total de filas)", fmt_int(t["local_rows_invalid_monetary"])],
              ["Meses que no concilian con el anual", fmt_int(t["local_monthly_mismatches"])],
              ["Líneas aceptadas con todos los montos en cero", fmt_int(t["local_rows_all_zero"])],
              ["Líneas aceptadas con algún monto negativo", fmt_int(t["local_rows_with_negative_amounts"])],
              ["Líneas de proyecto (TIPO_ACT_PROY = PROYECTO)", fmt_int(t["local_project_rows"])]]
    for k, v in sorted(me.items(), key=lambda kv: -kv[1])[:4]:
        detail.append([f"Error de monto `{k}`", fmt_int(v)])
    R.table(["Indicador de calidad", "Filas"], detail, "Detalle de incidencias y características de las líneas municipales.", widths=[11, 4], align_right={1})
    integ = rep["integrity"]
    R.table(["Conciliación", "Resultado"], [
        ["Σ agregados por ejecutora = Σ líneas aceptadas (PIA, PIM, devengado, al céntimo)", "✔ " + str(integ["totals_equal_aggregates"])],
        ["Líneas en agregados = líneas aceptadas", "✔ " + str(integ["rows_equal_aggregates"])],
        ["Leídas = no locales + aceptadas + rechazadas + malformadas (+ duplicados excluidos)", "✔ " + str(integ["row_balance"])],
    ], "Controles de integridad del ETL (el programa termina con error si alguno falla).", widths=[12, 3])
    R.figure(figs / "f_embudo.png", "Embudo de datos: de líneas presupuestarias a perfiles elegibles para K-Means.")
    R.figure(figs / "f_mensual.png", "Distribución mensual del devengado municipal calculada por el ETL en Go.")
    reasons = rep.get("excluded_by_reason", {})
    R.p(f"De {fmt_int(rep['municipality_year_profiles'])} perfiles ejecutora-año, **{fmt_int(rep['eligible_profiles'])}** son elegibles. "
        "Motivos de exclusión (un perfil puede tener varios): " + "; ".join(f"`{k}` = {v}" for k, v in sorted(reasons.items(), key=lambda kv: -kv[1])) + ".")

    R.h("4.3 Diseño del modelo ML distribuido", 2)
    R.h("4.3.1 Indicadores (features) del perfil municipal", 3)
    feat_rows = []
    for n in names:
        p = transformer["parameters"][n]
        feat_rows.append([FEATURE_LABEL.get(n, n), f"`{n}`", f"{p['p01']:.3f} – {p['p99']:.3f}", f"{p['center_median']:.3f}", f"{p['scale']:.3f} ({p['scale_method']})"])
    R.table(["Indicador", "Columna", "Winsor p01–p99", "Mediana", "Escala"], feat_rows,
            "Indicadores del perfil ejecutora-año y parámetros de escalamiento ajustados.", widths=[5.2, 4.4, 2.6, 1.6, 2.2], font=8)
    R.p("Los indicadores capturan las dimensiones que distinguen una buena de una mala gestión del gasto: **cuánto** se ejecuta "
        "(tasa de ejecución), **cuándo** (concentración en el último trimestre y variabilidad mensual), **cuánto cambia** el presupuesto "
        "(modificación PIA→PIM, en logaritmos para admitir PIA = 0) y **en qué** se gasta (participación de proyectos), además de la escala. "
        "La winsorización limita la influencia de extremos sin eliminarlos y el escalado robusto evita que una variable domine las distancias.")
    R.figure(figs / "f_features.png", "Distribución de los indicadores (sin escalar) de los perfiles elegibles.")
    R.h("4.3.2 Algoritmo: K-Means paralelo con esquema MapReduce", 3)
    R.p("K-Means minimiza la inercia (suma de distancias cuadradas de cada punto a su centroide) alternando dos pasos: asignar cada punto "
        "al centroide más cercano y recalcular cada centroide como la media de sus puntos (MacQueen, 1967). Ambos pasos se descomponen "
        "en sumas parciales independientes por partición de datos, lo que lo hace naturalmente paralelizable (Zhao et al., 2009):")
    R.bullets([
        "**Inicialización:** k-means++ con semilla fija (Arthur y Vassilvitskii, 2007); secuencial y paralelo parten de los mismos centroides.",
        "**Map (cada worker):** recibe una copia inmutable de los centroides, asigna cada punto de su partición y acumula, por cluster, la suma de vectores, el conteo y la inercia. Devuelve un mensaje `Partial`.",
        "**Reduce (coordinador):** espera a todos los workers (barrera), suma los parciales en orden de partición y recalcula los centroides.",
        "**Convergencia:** se detiene cuando ningún punto cambia de cluster o el desplazamiento máximo de los centroides es menor que la tolerancia.",
        "**Clusters vacíos:** se reubican en el punto más lejano reportado por los workers (determinista).",
    ])
    R.figure(figs / "f_mapreduce.png", "Una iteración del K-Means paralelo (MapReduce) implementado en Go.")
    R.code("""// internal/ml/kmeansmr/parallel.go — bucle del coordinador (goroutines hoy, nodos TCP en PC4)
for it := 1; it <= o.MaxIter; it++ {
    snapshot := copiar(cents)                  // copia inmutable de solo lectura
    for s, w := range workers {                // fan-out
        replies[s] = w.Step(snapshot)
    }
    for s := range workers {                   // fan-in + barrera
        parts[s] = <-replies[s]
    }
    nc, _, _, changed, shift := reduce(X, parts, cents) // orden de partición
    if changed == 0 || shift < o.Tol { break }
}""")
    R.h("4.3.3 Selección de K y detección de atípicos", 3)
    R.p("K se evalúa entre 2 y 10 con la curva del codo (inercia), el coeficiente de **silueta** (Rousseeuw, 1987), calculado en paralelo, "
        "y el índice de Davies-Bouldin (1979). Se elige el K de silueta máxima. Un perfil es **atípico** si su distancia al centroide supera "
        "Q3 + 1.5·IQR de las distancias de su propio cluster (regla de Tukey) o si pertenece a un micro-cluster de menos de 4 perfiles.")
    R.h("4.3.4 Distribución prevista (Entregable 2)", 3)
    R.p("El coordinador (`Coordinate`) trabaja contra la interfaz `ShardWorker`. En PC3 cada `ShardWorker` es un goroutine local; en PC4 será "
        "un nodo del clúster que recibe su partición una sola vez y, en cada iteración, recibe los centroides y responde el `Partial` "
        "serializado en JSON por TCP. Solo viajan k×d sumas por nodo, no los datos, por lo que el tráfico por iteración es mínimo.")

    R.h("4.4 Paralelización del cálculo en Go", 2)
    R.h("4.4.1 Parte A: pipeline concurrente del cargador", 3)
    R.figure(figs / "f_pipeline.png", "Pipeline concurrente del cargador: productor, worker pool, reduce y escritor de incidencias.")
    R.table(["Técnica / patrón", "Dónde", "Por qué"], [
        ["Pipeline productor-consumidor", "`Split` → canal `chunks` → workers", "La lectura del disco (secuencial) se solapa con el parseo (CPU-bound)."],
        ["Backpressure (canal con capacidad acotada)", "`make(chan Chunk, 2*workers)`", "Memoria acotada aunque el archivo pese 2.6 GB."],
        ["Worker pool", "N goroutines (`--workers`)", "Parseo CSV y conversión exacta de 15 montos por fila en paralelo."],
        ["Map-reduce con agregación local", "mapa por worker + `Merge`", "Sin candados en el bucle caliente; el resultado es idéntico al secuencial (sumas enteras)."],
        ["Fan-in con `sync.WaitGroup`", "canal `partials` se cierra al terminar todos", "Fusión segura sin esperas activas."],
        ["Lock striping (`sync.Mutex` × 64)", "`DupDetector.InsertBatch`", "El único estado compartido; un candado por partición y por bloque."],
        ["Serialización por canal", "canal `incCh` → 1 escritor", "El archivo de incidencias nunca se escribe en paralelo."],
        ["Registros completos por bloque", "`readRecord` cuenta comillas", "Ningún registro con salto de línea entrecomillado se parte entre workers."],
    ], "Técnicas y patrones de concurrencia del cargador.", widths=[4.4, 4.6, 7.0], font=8.5)
    R.code("""// internal/ingestion/loader.go — worker del pool (fase map, estado local)
for c := range chunks {
    r := csv.NewReader(bytes.NewReader(c.Data))
    for {
        rec, err := r.Read(); if err == io.EOF { break }
        h.handle(p, rec, row, &keep, dups != nil)   // valida; guarda aceptadas
    }
    isDup := dups.InsertBatch(fingerprints(keep))   // único sync.Mutex (por shard)
    for i := range keep {
        if !(isDup[i] && cfg.DropDuplicates) { h.accept(p, &keep[i]) }
    }
}
partials <- p                                   // fan-in hacia el reduce""")
    R.h("4.4.2 Parte B: K-Means paralelo", 3)
    R.table(["Técnica / patrón", "Implementación", "Garantía"], [
        ["Paralelismo de datos (sharding)", "`Partition(n, p)`: rangos contiguos de filas", "Carga balanceada (diferencia máxima de 1 fila)."],
        ["Goroutines de larga vida", "`newLocalWorker`: un goroutine por partición durante todo el entrenamiento", "Sin costo de crear goroutines por iteración."],
        ["Broadcast inmutable", "copia `snapshot` de centroides por iteración", "Lecturas concurrentes sin carreras."],
        ["Escritura en regiones disjuntas", "cada worker escribe `labels[lo:hi]`", "Sin candados; verificado con `-race`."],
        ["Barrera por canales", "el coordinador recibe los P `Partial`", "La actualización de centroides ve todos los parciales."],
        ["Reducción determinista", "suma en orden de partición", "Mismas etiquetas que la versión secuencial."],
        ["Silueta paralela", "un acumulador por goroutine", "O(n²) dividido entre workers sin candados."],
    ], "Técnicas de paralelización del K-Means.", widths=[4.2, 6.2, 5.6], font=8.5)
    R.p("**Ausencia de condiciones de carrera.** Ningún dato mutable se comparte sin sincronización: los agregados son locales a cada worker, "
        "los centroides se difunden como copias, las etiquetas se escriben en rangos disjuntos y la comunicación ocurre por canales. "
        "El único estado compartido (detector de duplicados) está protegido por `sync.Mutex`. Toda la suite se ejecuta con `go test -race`.")

    R.h("4.5 Evidencias de implementación y pruebas", 2)
    R.h("4.5.1 Estructura del código", 3)
    R.code("""cmd/etlgo          Parte A: carga concurrente, limpieza, agregación y matriz de features
cmd/mrtrainer      Parte B: selección de K, K-Means MapReduce, silueta y atípicos
cmd/etl            auditoría concurrente de conteos y montos (Marco)
cmd/trainer        K-Means municipal sobre la matriz de Python y benchmark 1/2/4/8 workers (Marco)
cmd/massivekmeans  K-Means sobre 3.64 M líneas presupuestarias (archivo binario, ReadAt) (Marco)
cmd/massiveprofile caracterización y validación de los clusters masivos (Marco)
cmd/benchmark      speedup del ETL y de K-Means con 1/2/4/8 workers
cmd/gendata        generador de CSV sintéticos con el esquema del MEF (pruebas)
internal/ingestion       audit.go (Marco) · chunker.go · loader.go · sequential.go · dedup.go
internal/preprocessing   money.go (céntimos exactos) · rules.go (validación por fila)
internal/features        features.go (elegibilidad, indicadores, winsor, robust scaling) · io.go
internal/ml/kmeans       K-Means por rangos con canales y silueta muestral (Marco)
internal/ml/kmeansmr     kmeans.go · parallel.go (MapReduce, ShardWorker) · metrics.go (silueta, DB, atípicos)
internal/ml/massive      build.go · features.go · train.go · profile.go (experimento masivo, Marco)
deployments/docker       Dockerfile.etl (etl, mrtrainer, benchmark) · Dockerfile.trainer (Marco)""")
    R.h("4.5.2 Pruebas unitarias y detector de carreras", 3)
    R.table(["Prueba", "Verifica"], [
        ["`TestParseCents`, `TestFormatSoles`", "Conversión exacta: decimales, coma ambigua, vacíos, notación científica, negativos."],
        ["`TestValidate`, `TestNewIndexMissing`", "Cada regla de limpieza: nivel, año, conciliación mensual, montos, filas malformadas, encabezado."],
        ["`TestConcurrentEqualsSequential`", "Con 1, 2, 4 y 8 workers y bloques de 1, 7 y 500 registros, totales y agregados idénticos al secuencial."],
        ["`TestRowBalance`", "Balance de filas y suma de agregados = suma de líneas, con exclusión de duplicados."],
        ["`TestSplitKeepsQuotedNewlines`", "Un campo con salto de línea entrecomillado no se parte entre bloques."],
        ["`TestDupDetectorConcurrent`", "8 goroutines insertan huellas a la vez: conteo exacto de duplicados y sin carreras."],
        ["`TestIndicators`, `TestFitTransform`, `TestEntityType`, `TestPercentile`", "Indicadores (PIA = 0 válido), winsor y escalado (mediana → 0), tipificación por nombre sin tildes."],
        ["`TestAuditFile`, `TestCents`, `TestSequentialAndParallelSame` (Marco)", "Auditoría concurrente de conteos y montos; K-Means por rangos igual al secuencial; encabezado y claves de la matriz."],
        ["`TestBuildAndValidateMetadata`, `TestSequentialParallelAgreement`, `TestCheckBinaryLength`, `TestProfileAllMatchesTraining` (Marco)", "Archivo binario de líneas con metadatos válidos; entrenamiento masivo idéntico con 1, 2, 4 y 8 workers; todas las filas asignadas una sola vez; rechazo de reportes y binarios corruptos."],
        ["`TestParallelEqualsSequential`", "K-Means paralelo con 1, 2, 3, 4 y 8 workers: mismas etiquetas e inercia que el secuencial."],
        ["`TestRecoversBlobs`, `TestDetectAnomalies`, `TestEmptyClusterReseed`, `TestPartition`", "Recupera clusters conocidos (silueta > 0.7), detecta el punto extremo, reubica clusters vacíos, particiona sin rangos vacíos."],
    ], "Pruebas automatizadas (`go test -race ./...`).", widths=[6.0, 10.0], font=8.5)
    if "go_test.txt" in term:
        R.figure(term["go_test.txt"], "Ejecución de la suite de pruebas con el detector de carreras de Go.")
    R.h("4.5.3 Ejecución del ETL y del entrenamiento", 3)
    if "etl.txt" in term:
        R.figure(term["etl.txt"], f"Ejecución del ETL concurrente sobre el {src_label}.")
    if ksel:
        R.figure(figs / "f_k.png", "Curva del codo, silueta y Davies-Bouldin para K = 2…10.")
        R.table(["K", "Inercia", "Silueta", "Davies-Bouldin", "Iteraciones"],
                [[r["k"], f"{float(r['inertia']):.1f}", f"{float(r['silhouette']):.4f}", f"{float(r['davies_bouldin']):.3f}", r["iterations"]] for r in ksel],
                "Métricas de selección de K (K-Means paralelo).", widths=[1.5, 3.5, 3.5, 4.0, 3.5], align_right={1, 2, 3, 4}, font=8.5)
    if "trainer.txt" in term:
        R.figure(term["trainer.txt"], "Ejecución del entrenamiento: selección de K, comparación secuencial vs. paralelo y atípicos.")
    R.figure(figs / "f_convergencia.png", "Convergencia del modelo final: inercia y perfiles que cambian de cluster por iteración.")
    R.h("4.5.4 Resultados del clustering", 3)
    crow = []
    for c in model["clusters"]:
        mr = c["median_raw"]
        crow.append([f"C{c['cluster']}", cnames[c["cluster"]], fmt_int(c["size"]), f"{c['share'] * 100:.1f} %",
                     f"{mr.get('tasa_ejecucion', float('nan')) * 100:.1f} %", f"{mr.get('concentracion_q4', float('nan')) * 100:.1f} %",
                     f"{mr.get('participacion_devengado_proyectos', float('nan')) * 100:.1f} %", f"{mr.get('modificacion_log_pim_pia', float('nan')):.2f}",
                     str(c["anomalies"])])
    R.table(["Cluster", "Perfil", "Perfiles", "%", "Ejecución (mediana)", "Conc. Q4", "% proyectos", "Modif. log", "Atípicos"], crow,
            f"Perfiles de cluster con medianas de los indicadores sin escalar (K = {model['k']}, silueta = {model['silhouette']:.3f}).",
            widths=[1.3, 3.8, 1.5, 1.2, 1.9, 1.6, 1.7, 1.5, 1.5], font=8,
            align_right={2, 3, 4, 5, 6, 7, 8})
    R.figure(figs / "f_heatmap.png", "Centroides escalados: cada fila es un cluster; rojo = por encima de la mediana nacional.")
    R.figure(figs / "f_clusters.png", "Proyección PCA de los perfiles por cluster; los círculos negros son perfiles atípicos.")
    top = anomalies[:10]
    R.table(["Año", "Ejecutora", "Departamento", "Cluster", "Score", "Motivo"],
            [[a["ano_eje"], a["ejecutora_nombre"][:46], a["departamento"][:18], a["cluster"], (f"{float(a['score']):.2f}" if a["score"] else "∞"), a["motivo"]] for a in top],
            "Diez perfiles con mayor desviación (score = distancia / umbral del cluster)." + (" Nombres sintéticos." if synthetic else ""),
            widths=[1.2, 6.4, 3.0, 1.4, 1.4, 2.6], font=8)
    R.p("**Lectura para el impacto social.** Cada cluster es un patrón de gestión distinto que pide una respuesta distinta: el rezago de "
        "ejecución sugiere asistencia técnica en formulación y contratación; el gasto concentrado al cierre sugiere apoyo en planificación y "
        "control concurrente de fin de año; el perfil intensivo en inversión con alta modificación pide seguimiento de la cartera de obras. "
        "Los atípicos son los casos a revisar primero dentro de cada grupo.")
    R.h("4.5.5 Rendimiento: secuencial vs. concurrente", 3)
    if speed:
        srows = [[x["etapa"].upper(), x["configuracion"], x["workers"] if x["workers"] != "0" else "—", fmt_int(x["n"]),
                  f"{float(x['segundos_mediana']):.3f}", f"{float(x['speedup']):.2f}×", (f"{float(x['eficiencia']) * 100:.0f} %" if x["eficiencia"] else "—")] for x in speed]
        R.table(["Etapa", "Configuración", "Workers", "Registros / puntos", "Tiempo (s, mediana de 3)", "Speedup", "Eficiencia"], srows,
                f"Tiempos medidos con `cmd/benchmark` en una máquina de {speed[0]['num_cpu']} núcleos lógicos.",
                widths=[1.6, 2.6, 1.6, 2.8, 3.0, 2.0, 2.4], font=8.5, align_right={2, 3, 4, 5, 6})
        R.figure(figs / "f_speedup.png", "Speedup del ETL y del K-Means paralelo frente a la versión secuencial.")
        cpu = int(speed[0]["num_cpu"])
        R.p(f"El speedup crece hasta igualar el número de núcleos físicos disponibles ({cpu}) y se estabiliza después: con más goroutines que "
            "núcleos no hay más paralelismo real, solo intercalado. En el ETL, la parte secuencial (lectura del disco por un único productor y "
            "fusión final) acota el speedup según la ley de Amdahl. Ambos resultados (concurrente y secuencial) son idénticos byte a byte. "
            "La matriz municipal tiene pocos miles de perfiles y se entrena en milisegundos; por eso la escalabilidad de K-Means se midió con "
            "N puntos remuestreados de la misma matriz, el volumen que se distribuirá en el clúster del Entregable 2.")
    if "bench.txt" in term:
        R.figure(term["bench.txt"], "Benchmarks de Go (`testing.B`) del cargador y del K-Means.")

    R.h("4.5.6 Experimento masivo sobre 3 642 510 líneas presupuestarias", 3)
    mm = massive
    origin = "medidos en esta ejecución" if mm["source"] == "medido" else "documentados por el equipo en `docs/evidence/validacion-kmeans-masivo.md` (ejecución sobre los CSV oficiales)"
    R.p("El modelo municipal entrena sobre miles de perfiles; **el volumen masivo** del caso se aborda además con un segundo experimento, "
        "independiente, a nivel de línea presupuestaria. Marco implementó en `internal/ml/massive` un pipeline que convierte las líneas municipales "
        "en un archivo binario de 9 características (3 642 510 × 9 × 8 bytes), inicializa k-means++ sobre una muestra uniforme de 10 000 líneas y "
        "ejecuta iteraciones de Lloyd **exactas sobre todas las líneas**: cada worker lee su rango con `ReadAt`, acumula sumas locales y las envía "
        "por un canal; el coordinador reduce en orden fijo. Los resultados siguientes son " + origin + ".")
    R.table(["Cluster", "Líneas", "% del total", "% proyectos", "% PIM = 0", "% devengado = 0"],
            [[f"C{i}", fmt_int(n), f"{n / mm['rows'] * 100:.2f} %", f"{mm['profile'][i]['proy']:.2f} %", f"{mm['profile'][i]['pim0']:.2f} %", f"{mm['profile'][i]['dev0']:.2f} %"]
             for i, n in enumerate(mm["sizes"])],
            f"K = {mm['k']}, {fmt_int(mm['rows'])} líneas, {mm['iterations']} iteraciones, inercia = {mm['inertia']:.1f}.",
            widths=[1.8, 3.0, 2.4, 2.8, 2.8, 3.2], font=8.5, align_right={1, 2, 3, 4, 5})
    bt = mm["bench"]; w1 = bt[1]
    R.table(["Workers", "Entrenamiento (ms, mediana de 3)", "Speedup", "Eficiencia"],
            [[str(w), f"{bt[w]:,.0f}".replace(",", " "), f"{w1 / bt[w]:.2f}×", f"{w1 / bt[w] / w * 100:.1f} %"] for w in sorted(bt)],
            "Escalabilidad del K-Means masivo (K, semilla y datos idénticos; el resultado es el mismo con cualquier número de workers).",
            widths=[2.4, 6.0, 3.0, 3.0], font=8.5, align_right={0, 1, 2, 3})
    R.p("Dos lecturas honestas de estos resultados. Primero, **la segmentación separa tipos de línea contable** (líneas con PIM cero, líneas sin devengado, "
        "líneas ejecutadas), no municipalidades: sirve como prueba de escalabilidad y exploración, no como detector de irregularidades; por eso la "
        "pregunta de impacto social se responde con el modelo municipal. Segundo, el speedup (≈ 2.4× con 8 workers, eficiencia ≈ 30 %) queda lejos del lineal porque "
        "cada iteración debe releer 262 MB y mover datos es más lento que calcular distancias: el entrenamiento está limitado por memoria y disco, no por CPU.")
    au = mm["audit"]; ab = median(au[1])
    R.table(["Workers", "Auditoría ETL con lector CSV único (s, mediana de 3)", "Speedup"],
            [[str(w), f"{median(au[w]):.2f}", f"{ab / median(au[w]):.2f}×"] for w in sorted(au)],
            "Auditoría concurrente de los 2 CSV (5.6 M filas): agregar workers no reduce el tiempo.",
            widths=[2.4, 9.0, 3.0], font=8.5, align_right={0, 1, 2})
    R.p("**Hallazgo.** En la auditoría, un único goroutine lee y parsea todo el CSV (`encoding/csv` es secuencial) y solo reparte a los workers la conversión de tres montos; "
        "como el parseo domina el costo, más workers no ayudan (el tiempo sube ligeramente por el costo del canal). Esta observación motivó el diseño del cargador de "
        "`cmd/etlgo`: un productor ligero parte el archivo en bloques de registros completos y **cada worker parsea y valida su bloque**, de modo que la parte "
        "paralelizable pasa de ser casi nula a ser la mayoría del trabajo.")
    R.figure(figs / "f_massive.png", "Izquierda: escalabilidad del K-Means masivo. Derecha: parsear dentro de los workers acelera; el lector único no." + (" La curva verde se midió con datos sintéticos en 2 núcleos." if synthetic else ""))
    R.h("4.6 GitHub (Git Flow) y tablero Kanban", 2)
    R.p(f"Repositorio público: {REPO}. Se sigue Git Flow: `main` (versiones entregadas) ← `develop` (integración) ← ramas `feature/*`, "
        "integradas mediante Pull Request con revisión de un compañero.")
    R.table(["Rama", "Contenido", "Estado"], [
        ["`main`", "Versión entregada de cada PC", "Se actualiza al cierre del entregable"],
        ["`develop`", "Integración; estructura inicial del proyecto", "Activa"],
        ["`feature/eda-preprocessing`", "Auditoría, EDA, preprocesamiento, feature engineering y pruebas (Python)", "PR → develop"],
        ["`feature/parallel-kmeans`", "Auditoría Go, K-Means por rangos, experimento masivo de 3.64 M líneas, perfilado y validación (Marco)", "PR → develop"],
        ["`feature/go-concurrent-etl-kmeans`", "ETL concurrente con parseo en workers, limpieza, features, K-Means MapReduce, silueta y atípicos, Docker (David)", "PR → develop"],
    ], "Ramas del repositorio.", widths=[5.0, 7.5, 3.5], font=8.5)
    if "git.txt" in term:
        R.figure(term["git.txt"], "Historial de commits (Git Flow).")
    R.table(["Columna", "Tarjetas"], [
        ["Done", "Caso y pregunta de impacto · Auditoría de volumen · EDA · Reglas de preprocesamiento · Feature engineering · Auditoría concurrente Go · K-Means por rangos · K-Means masivo 3.64 M · Cargador con parseo en workers · Limpieza y features Go · K-Means MapReduce · Atípicos · Pruebas y benchmarks"],
        ["Review", "Informe PC3 y reporte de participación"],
        ["To do", "Ejecutar el pipeline Go con los CSV oficiales y actualizar cifras"],
        ["Backlog (PC4 / TB2)", "Nodos ML por TCP · API REST/WebSocket + Swagger · MongoDB + Redis · SPA React · Docker Compose"],
    ], "Estado del tablero Kanban al cierre del Entregable 1 (detalle en docs/reports/kanban-pc3.md).", widths=[3.2, 12.8], font=8.5)
    R.p("[Insertar captura del tablero Kanban de GitHub Projects]", italic=True, align="center")

    R.h("4.7 Reporte de participación", 2)
    R.table(["Integrante", "Código", "Actividades en el Entregable 1", "Participación"],
            [[n, c, r, pct] for n, c, r, pct in TEAM], "Reporte de participación.", widths=[3.6, 2.4, 8.0, 2.0], font=9)

    # Conclusiones ---------------------------------------------------------------
    R.h("5. Conclusiones")
    R.bullets([
        f"Los datos del MEF cumplen holgadamente el requisito de volumen: {fmt_int(EDA_REAL['local_total'])} líneas presupuestarias municipales en 2024–2025, que el cargador procesa de forma concurrente.",
        "Las reglas de limpieza son auditables y exactas: los montos se manejan en céntimos enteros, cada fila descartada queda registrada con su motivo y los agregados cuadran al céntimo con las líneas aceptadas.",
        "El diseño map-reduce con estado local por worker elimina la contención: el ETL concurrente produce exactamente el mismo resultado que el secuencial" + (f" y es {float(best['speedup']):.2f}× más rápido con {best['workers']} workers en {best['num_cpu']} núcleos." if best else "."),
        f"K-Means paralelo converge a la misma solución que el secuencial. Con K = {model['k']} (silueta {model['silhouette']:.3f}) separa patrones de gestión interpretables y marca {model['anomalies']} perfiles atípicos para revisión prioritaria.",
        f"El experimento masivo entrena K-Means sobre las {fmt_int(massive['rows'])} líneas con resultado idéntico para 1, 2, 4 y 8 workers y un speedup de {massive['bench'][1] / massive['bench'][max(massive['bench'])]:.2f}× con {max(massive['bench'])} workers: la carga es de ancho de banda y no de cómputo.",
        "Paralelizar solo la conversión de montos no acelera la auditoría de los CSV (24.9 s con 1 worker, 26.3 s con 8): el parseo debe estar dentro de los workers, como en el cargador por bloques.",
        "El coordinador ya está desacoplado de los workers mediante la interfaz `ShardWorker` y el mensaje `Partial`, lo que deja lista la distribución por TCP del Entregable 2.",
    ])
    R.h("6. Recomendaciones")
    R.bullets([
        "Unificar `internal/ml/kmeans` (Marco) y `internal/ml/kmeansmr` (David) en un solo paquete antes del Entregable 2, conservando la interfaz `ShardWorker` para la distribución por TCP.",
        "Para el entrenamiento masivo, cargar el binario en memoria compartida (o mapearlo) en lugar de releerlo con `ReadAt` en cada iteración, y reportar silueta sobre una muestra.",
        "Ejecutar el pipeline Go sobre los CSV oficiales en una máquina de 8 o más núcleos y contrastar `municipality_year_features.csv` contra la salida de `preprocess_data.py` (deben coincidir).",
        "Validar con un padrón oficial la tipificación de ejecutoras por nombre (municipalidad, mancomunidad, otras) antes de presentar resultados definitivos.",
        "Comparar 2024 y 2025 al mismo mes de corte si 2025 resulta un snapshot parcial.",
        "Integrar Seguimiento PI solo después de validar claves y el significado de `ANO_EJE`; agregarlo como indicador de avance de la cartera de proyectos.",
        "Hacer un análisis de sensibilidad de K y del conjunto de indicadores, y presentar los atípicos siempre como alertas, nunca como evidencia de irregularidad.",
        "En el Entregable 2, implementar `ShardWorker` remoto por TCP con tolerancia a fallos (reintento y reasignación de particiones) y medir la latencia por iteración.",
    ])

    # Bibliografía ---------------------------------------------------------------
    R.h("7. Bibliografía")
    refs = [
        "Arthur, D., y Vassilvitskii, S. (2007). k-means++: The advantages of careful seeding. En *Proceedings of the Eighteenth Annual ACM-SIAM Symposium on Discrete Algorithms* (pp. 1027–1035). SIAM.",
        "Caretas. (2 de enero de 2025). Inversión pública cierra el 2024 al alcanzar una ejecución de S/ 57 742 millones. https://caretas.pe/economia/inversion-publica-cierra-el-2024-al-alcanzar-una-ejecucion-de-s-57-742-millones",
        "Davies, D. L., y Bouldin, D. W. (1979). A cluster separation measure. *IEEE Transactions on Pattern Analysis and Machine Intelligence, PAMI-1*(2), 224–227. https://doi.org/10.1109/TPAMI.1979.4766909",
        "Dean, J., y Ghemawat, S. (2008). MapReduce: Simplified data processing on large clusters. *Communications of the ACM, 51*(1), 107–113. https://doi.org/10.1145/1327452.1327492",
        "Donovan, A. A. A., y Kernighan, B. W. (2015). *The Go programming language*. Addison-Wesley.",
        "Gestión. (2 de enero de 2025). Inversión pública cerró el 2024 creciendo 16 %: ¿cuánto presupuesto se ejecutó? https://gestion.pe/economia/inversion-publica-cerro-el-2024-creciendo-16-cuanto-presupuesto-se-ejecuto-noticia/",
        "MacQueen, J. (1967). Some methods for classification and analysis of multivariate observations. En *Proceedings of the Fifth Berkeley Symposium on Mathematical Statistics and Probability* (Vol. 1, pp. 281–297). University of California Press.",
        "Ministerio de Economía y Finanzas. (2025). *Presupuesto y ejecución de gasto — Gasto devengado* [Conjunto de datos]. Plataforma Nacional de Datos Abiertos. https://www.datosabiertos.gob.pe",
        "Ministerio de Economía y Finanzas. (2025). *Seguimiento de la ejecución de proyectos de inversión* [Conjunto de datos]. Plataforma Nacional de Datos Abiertos. https://www.datosabiertos.gob.pe",
        "Rousseeuw, P. J. (1987). Silhouettes: A graphical aid to the interpretation and validation of cluster analysis. *Journal of Computational and Applied Mathematics, 20*, 53–65. https://doi.org/10.1016/0377-0427(87)90125-7",
        "The Go Authors. (2024). *Data race detector*. https://go.dev/doc/articles/race_detector",
        "Tukey, J. W. (1977). *Exploratory data analysis*. Addison-Wesley.",
        "Zhao, W., Ma, H., y He, Q. (2009). Parallel k-means clustering based on MapReduce. En *Cloud Computing. CloudCom 2009* (LNCS 5931, pp. 674–679). Springer. https://doi.org/10.1007/978-3-642-10665-1_71",
    ]
    for ref in refs:
        para = d.add_paragraph()
        para.paragraph_format.left_indent = Cm(1.0); para.paragraph_format.first_line_indent = Cm(-1.0)
        para.paragraph_format.space_after = Pt(4)
        chunks = ref.split("*")
        for i, ch in enumerate(chunks):
            r = para.add_run(ch); r.font.size = Pt(10); r.italic = (i % 2 == 1)

    # Anexos ---------------------------------------------------------------------
    R.h("8. Anexos")
    R.h("Anexo A. Enlaces", 2)
    R.table(["Recurso", "Enlace"], [
        ["Repositorio GitHub", REPO],
        ["Rama del Entregable 1 (Go)", REPO + "/tree/feature/go-concurrent-etl-kmeans"],
        ["Rama de EDA y preprocesamiento (Python)", REPO + "/tree/feature/eda-preprocessing"],
        ["Tablero Kanban", "[completar enlace de GitHub Projects]"],
        ["Video", "[completar si corresponde]"],
    ], "Enlaces del proyecto.", widths=[5.0, 11.0], font=9)
    R.h("Anexo B. Reproducción de resultados", 2)
    R.code("""# 1) Colocar los CSV del MEF en data/raw/ (no se suben a Git)
#    2024-Gasto-Devengado.csv   2025-Gasto-Devengado-Mensual.csv
go test -race ./...                                              # pruebas
go run ./cmd/etlgo --data-dir data/raw --workers 8               # Parte A
go run ./cmd/mrtrainer --in data/processed/go_etl --workers 8 # Parte B
go run ./cmd/massivekmeans -mode all -k 3 -workers 4             # 3.64 M líneas
# o todo junto:  powershell -File scripts/run_pc3_all.ps1
go run ./cmd/benchmark --data-dir data/raw --workers 1,2,4,8
# 2) Regenerar este informe con las cifras reales
py -m pip install python-docx matplotlib numpy
py scripts/report/build_pc3_report.py   # lee data/processed/go_etl, benchmarks y logs""")
    R.h("Anexo C. Archivos de salida", 2)
    R.table(["Archivo", "Contenido"], [
        ["`reporte_etl.json`, `resumen_etl.md`", "Conteos, tiempos, filas/s y conciliaciones"],
        ["`incidencias_preprocesamiento.csv`", "Filas rechazadas o malformadas con su motivo y número de fila"],
        ["`municipality_year_features.csv`", "Perfil por ejecutora-año (mismas columnas que el preprocesamiento en Python)"],
        ["`municipality_features_audit.csv`", "Todos los perfiles con elegibilidad, motivos e indicadores sin escalar"],
        ["`kmeans_matrix.csv`, `kmeans_keys.csv`, `feature_transformer.json`", "Matriz escalada, claves y parámetros de la transformación"],
        ["`kmeans/k_selection.csv`, `modelo.json`, `clusters.csv`, `anomalias.csv`", "Selección de K, modelo, asignaciones y atípicos"],
    ], "Archivos generados por el pipeline (carpeta data/processed/go_etl).", widths=[7.0, 9.0], font=8.5)

    add_page_number_footer(d)
    zoom = d.settings.element.find(qn("w:zoom"))
    if zoom is not None and zoom.get(qn("w:percent")) is None:
        zoom.set(qn("w:percent"), "100")
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    d.save(out)
    print(f"Informe: {out}  ({R.fig_n} figuras, {R.tab_n} tablas)")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--etl", default="data/processed/go_etl")
    ap.add_argument("--bench", default="data/processed/benchmarks")
    ap.add_argument("--logs", default="data/processed/logs")
    ap.add_argument("--massive", default="data/processed/massive_mef", help="reportes del K-Means masivo (opcional)")
    ap.add_argument("--audit-bench", default="benchmarks_etl.csv", help="CSV Workers,Repeticion,Segundos de la auditoría ETL")
    ap.add_argument("--figs", default="data/processed/report_figs")
    ap.add_argument("--out", default="docs/reports/1ACC0065_PC3_202610_Informe_UXXXXXXXX.docx")
    ap.add_argument("--synthetic", action="store_true", help="declarar que el pipeline Go se ejecutó con datos sintéticos")
    build(ap.parse_args())


if __name__ == "__main__":
    main()
