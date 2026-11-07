#!/usr/bin/env python3
"""Valida evidencia del experimento masivo K-Means PC3 (sin dependencias externas).

Se ejecuta DESPUÉS de `massivekmeans` y `massiveprofile`.
NO prueba una silueta ni constituye validación administrativa de la información MEF.
"""
import argparse
import csv
import json
import math
import statistics
from pathlib import Path

FEATURES = (
    'signed_log_pia', 'signed_log_pim', 'signed_log_devengado',
    'tasa_ejecucion_acotada', 'participacion_q4_acotada',
    'meses_activos_fraccion', 'es_proyecto', 'pim_cero', 'devengado_cero'
)
WORKERS = (1, 2, 4, 8)


def check(condition, message):
    if not condition:
        raise ValueError(message)


def read_json(path):
    with path.open('r', encoding='utf-8-sig') as handle:
        return json.load(handle)


def rel_close(left, right, relative=1e-9, absolute=1e-6):
    return math.isclose(left, right, rel_tol=relative, abs_tol=absolute)


def validate(directory, require_benchmarks=True):
    directory = Path(directory)
    meta = read_json(directory / 'budget_lines_metadata.json')
    check(meta.get('dimensions') == len(FEATURES), 'dimensiones != 9')
    check(tuple(meta.get('features', [])) == FEATURES, 'orden de características incorrecto')
    rows = meta['rows']
    check(isinstance(rows, int) and rows > 1_000_000, 'no es el experimento masivo')
    sources = meta.get('sources')
    check(isinstance(sources, list) and len(sources) == 2, 'se esperan dos fuentes (2024 y 2025)')
    check(sum(s['municipal_rows'] for s in sources) == rows, 'filas fuente y total no concilian')
    all_rows = sum(s['all_rows'] for s in sources)
    project_rows = sum(s['project_rows'] for s in sources)
    # Aquí se validan los totales esperados para ESTE experimento concreto.
    check(rows == 3642510 and all_rows == 5596932 and project_rows == 578956,
          'conteos diferentes a la base validada de 2024-2025')

    reports = {}
    for workers in WORKERS:
        p = directory / f'training_k3_w{workers}_seed42.json'
        t = read_json(p)
        check(t.get('rows') == rows, f'filas inconsistentes w{workers}')
        check(t.get('k') == 3 and t.get('workers') == workers and t.get('seed') == 42,
              f'parámetros incompatibles w{workers}')
        check(tuple(t.get('features', [])) == FEATURES, f'features incompatibles w{workers}')
        check(t.get('converged') is True and t.get('iterations', 0) > 0,
              f'no convergió w{workers}')
        sizes = t.get('cluster_sizes', [])
        check(len(sizes) == 3 and sum(sizes) == rows, f'tamaños incompatibles w{workers}')
        check(len(t.get('centroids_scaled', [])) == 3 and all(len(c) == 9 for c in t['centroids_scaled']),
              f'centroides incorrectos w{workers}')
        check(math.isfinite(t.get('inertia', float('nan'))), f'inercia inválida w{workers}')
        reports[workers] = t
    base = reports[1]
    max_centroid_diff = 0.0
    max_rel_inertia_diff = 0.0
    for workers, t in reports.items():
        check(t['cluster_sizes'] == base['cluster_sizes'], f'asignaciones por tamaño diferentes w{workers}')
        check(t['iterations'] == base['iterations'], f'iteraciones diferentes w{workers}')
        change = abs(t['inertia'] - base['inertia']) / max(1., abs(base['inertia']))
        max_rel_inertia_diff = max(max_rel_inertia_diff, change)
        check(change < 1e-9, f'inercia no equivalente w{workers}')
        for c0, c1 in zip(base['centroids_scaled'], t['centroids_scaled']):
            max_centroid_diff = max(max_centroid_diff, *(abs(x-y) for x,y in zip(c0,c1)))
    check(max_centroid_diff < 1e-7, 'centroides divergentes entre workers')

    profile = read_json(directory / 'profile_k3_seed42.json')
    check(profile.get('rows') == rows and profile.get('k') == 3 and profile.get('seed') == 42,
          'reporte de perfilado incompatible')
    check(tuple(profile.get('features', [])) == FEATURES, 'perfilado: características incompatibles')
    clusters = profile.get('clusters', [])
    check(len(clusters) == 3, 'perfilado no contiene 3 clusters')
    check(sum(c['rows'] for c in clusters) == rows, 'suma de filas del perfilado incorrecta')
    check(rel_close(sum(c['inertia'] for c in clusters), profile['inertia'], relative=1e-12),
          'inercia del perfil no concilia con suma de sus clusters')
    check(rel_close(profile['inertia'], reports[4]['inertia'], relative=1e-9),
          'inercia del perfil no concilia con el entrenamiento w4')
    check(profile['max_centroid_delta'] <= 1e-4, 'diferencia excesiva entre centroides y medias')
    for index, c in enumerate(clusters):
        check(c['cluster'] == index and c['rows'] == base['cluster_sizes'][index],
              f'perfil: tamaño del cluster {index} incorrecto')
        check(rel_close(c['share_pct'], 100*c['rows']/rows),
              f'perfil: proporción del cluster {index} incorrecta')
        means = c['mean_original_features']
        check(len(means) == 9 and all(math.isfinite(v) for v in means),
              f'perfil: media inválida cluster {index}')
        for j in (6,7,8):
            check(-1e-12 <= means[j] <= 1 + 1e-12,
                  f'perfil: proporción de indicador binario fuera de 0-1 clúster {index}')

    benchmark_rows = []
    if require_benchmarks:
        raw_path = directory / 'benchmarks_massive.csv'
        summary_path = directory / 'benchmarks_resumen.csv'
        with raw_path.open('r', encoding='utf-8-sig', newline='') as fh:
            raw = list(csv.DictReader(fh))
        with summary_path.open('r', encoding='utf-8-sig', newline='') as fh:
            summary = list(csv.DictReader(fh))
        check(len(raw) == 12 and len(summary) == 4, 'cantidad inesperada de benchmarks')
        times = {w: [] for w in WORKERS}
        for r in raw:
            w = int(r['Workers'])
            check(w in times and int(r['Filas']) == rows and int(r['K']) == 3,
                  'benchmark sin correspondencia con datos')
            check(r['Convergio'].lower() == 'true' and int(r['Iteraciones']) == base['iterations'],
                  'benchmark no convergido o iteraciones diferentes')
            times[w].append(float(r['DuracionMs']))
            check(rel_close(float(r['Inercia']), reports[w]['inertia'], relative=1e-9),
                  f'benchmark inercia diferente w{w}')
        check(all(len(vals) == 3 for vals in times.values()), 'faltan repeticiones de benchmarks')
        medians = {w: statistics.median(vals) for w, vals in times.items()}
        for r in summary:
            w = int(r['workers'])
            check(w in times and int(r['repeticiones']) == 3, 'resumen: workers/repeticiones inválidos')
            check(rel_close(float(r['mediana_ms']), medians[w]),
                  f'mediana inconsistente w{w}')
            check(abs(float(r['speedup']) - medians[1]/medians[w]) < 0.0002,
                  f'speedup inconsistente w{w}')
            check(abs(float(r['eficiencia']) - medians[1]/medians[w]/w) < 0.0002,
                  f'eficiencia inconsistente w{w}')
            benchmark_rows.append({
                'workers': w, 'median_ms': medians[w],
                'speedup': medians[1]/medians[w], 'efficiency': medians[1]/medians[w]/w,
            })
        benchmark_rows.sort(key=lambda a:a['workers'])

    result = {
        'status': 'PASS',
        'scope': 'PC3 - K-Means sobre líneas presupuestarias; no perfiles municipales',
        'rows': rows, 'original_total_rows': all_rows, 'project_rows': project_rows,
        'k': 3, 'seed': 42, 'dimensions': len(FEATURES),
        'iterations': base['iterations'], 'cluster_sizes': base['cluster_sizes'],
        'training_inertia_4workers': reports[4]['inertia'],
        'recomputed_inertia': profile['inertia'],
        'absolute_inertia_discrepancy': abs(reports[4]['inertia'] - profile['inertia']),
        'relative_inertia_discrepancy': abs(reports[4]['inertia'] - profile['inertia']) / reports[4]['inertia'],
        'max_centroid_diff_across_workers': max_centroid_diff,
        'max_relative_inertia_diff_across_workers': max_rel_inertia_diff,
        'max_profile_delta_z': profile['max_centroid_delta'],
        'clusters': [
            {'cluster': c['cluster'], 'rows':c['rows'], 'share_pct':c['share_pct'],
             'project_pct':c['mean_original_features'][6]*100,
             'pim_zero_pct':c['mean_original_features'][7]*100,
             'dev_zero_pct':c['mean_original_features'][8]*100}
            for c in clusters
        ],
        'benchmarks': benchmark_rows,
        'limitations': [
            'Las unidades de observación son líneas presupuestarias, no municipalidades.',
            'Las tasas de ejecución y Q4 promediadas por línea NO representan razones agregadas.',
            'PIM=0 fija a cero la variable tasa_ejecucion_acotada; no equivale a ejecución real de 0%.',
            'Los importes signed_log_* NO están expresados directamente en soles.',
            'No se estimó Silhouette Score para el experimento masivo.',
            'Las validaciones usan reportes y metadatos: no recalculan los 3.64M registros sin el binario.'
        ]
    }
    return result


def markdown(result):
    s = [
        '# PC3 — Evidencia automatizada del entrenamiento K-Means masivo', '',
        '**Estado: PASS** — Validación de reportes (no sustituto de los tests Go).', '',
        f"- Filas municipales: **{result['rows']:,}**; líneas de proyectos: **{result['project_rows']:,}**.",
        f"- K={result['k']}; características={result['dimensions']}; iteraciones={result['iterations']}.",
        f"- Tamaños: **{result['cluster_sizes']}**.",
        f"- Inercia: entrenamiento={result['training_inertia_4workers']:.9f}; recalculada={result['recomputed_inertia']:.9f}.",
        f"- Diferencia relativa de inercia: **{result['relative_inertia_discrepancy']:.3e}**.",
        f"- Máxima diferencia de centroides entre workers: **{result['max_centroid_diff_across_workers']:.3e}**.", '',
        '## Perfilado de clústeres (proporciones de líneas, no municipalidades)', '',
        '| Clúster | Líneas | % del total | % proyectos | % PIM=0 | % Devengado=0 |',
        '|---:|---:|---:|---:|---:|---:|'
    ]
    for c in result['clusters']:
        s.append(f"| {c['cluster']} | {c['rows']:,} | {c['share_pct']:.2f}% | {c['project_pct']:.2f}% | {c['pim_zero_pct']:.2f}% | {c['dev_zero_pct']:.2f}% |")
    if result['benchmarks']:
        s.extend(['', '## Benchmarks de entrenamiento', '',
                  '| Workers | Mediana | Speedup | Eficiencia |', '|---:|---:|---:|---:|'])
        for b in result['benchmarks']:
            s.append(f"| {b['workers']} | {b['median_ms']:.0f} ms | {b['speedup']:.3f}× | {b['efficiency']*100:.1f}% |")
    s.extend(['', '## Limitaciones', ''])
    s.extend(f'- {item}' for item in result['limitations'])
    return '\n'.join(s) + '\n'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dir', default='data/processed/massive_mef', type=Path,
                        help='Carpeta con metadatos, profile, entrenamiento y benchmarks')
    parser.add_argument('--output', type=Path,
                        help='Carpeta de salida para validacion_final.json/.md; por defecto usa --dir')
    parser.add_argument('--skip-benchmarks', action='store_true')
    args = parser.parse_args()
    try:
        result = validate(args.dir, require_benchmarks=not args.skip_benchmarks)
    except (ValueError, FileNotFoundError, KeyError, json.JSONDecodeError, csv.Error) as exc:
        parser.exit(1, f'VALIDACIÓN FALLIDA: {exc}\n')
    destination = args.output or args.dir
    destination.mkdir(parents=True, exist_ok=True)
    (destination/'validacion_final.json').write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    (destination/'validacion_final.md').write_text(markdown(result), encoding='utf-8')
    print(f"PASS: {result['rows']:,} líneas; clústeres={result['cluster_sizes']}; inercia relativa={result['relative_inertia_discrepancy']:.2e}")
    print(f"Evidencias: {destination/'validacion_final.json'} y {destination/'validacion_final.md'}")


if __name__ == '__main__':
    main()
