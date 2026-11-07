"""Pruebas de ingeniería de características con perfiles sintéticos.

Ejecutar: py -m unittest discover -s tests -p "test_feature_engineering.py" -v
"""
from __future__ import annotations

import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "eda"))
from feature_engineering import (
    INPUT_COLUMNS, entity_type, percentile, run, calculate_features
)
from validate_features import validate


class FeatureEngineeringTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.csv_file = self.root / "municipality_year_features.csv"
        self.parent_report = self.root / "reporte_preprocesamiento.json"
        self.out = self.root / "features_mef"
        self.rows = []
        for i in range(20):
            year = 2024 if i < 10 else 2025
            # PIA cero en perfil válido, no debe ser excluido del clustering.
            pia = 0 if i == 2 else 500000 + i*100000
            pim = 800000 + i*130000
            dev = 0 if i == 4 else (380000 + i*140000)
            name = ("MANCOMUNIDAD MUNICIPAL DEL EJEMPLO" if i == 1
                    else f"MUNICIPALIDAD DISTRITAL DE DISTRITO {i}")
            self.rows.append({
                "ano_eje": str(year), "sec_ejec": str(300000 + i),
                "departamento": "LIMA" if i < 12 else "CUSCO",
                "ejecutora_nombre": name,
                "n_lineas": str(100+i), "n_lineas_proyecto": str(i),
                "pia_soles": f"{pia:.2f}", "pim_soles": f"{pim:.2f}",
                "devengado_soles": f"{dev:.2f}",
                "pim_proyectos_soles": f"{100000+i*10000:.2f}",
                "devengado_proyectos_soles": f"{dev*(0.1+i/70):.2f}",
                "tasa_ejecucion": "", "modificacion_sobre_pia": "",
                "participacion_devengado_proyectos": "",
                "concentracion_q4": "" if i == 4 else str(0.20+i*.025),
                "cv_devengado_mensual": "" if i == 4 else str(0.50+i*.06),
                "log1p_pim": "",
                "n_ajustes_mensuales_negativos": "0", "n_montos_negativos": "0",
                "n_lineas_excluidas": "0", "n_codigos_proyecto_faltantes": "1" if i == 3 else "0",
                "apto_candidato": "0" if i in (1,2,4) else "1",
                "advertencias": "pia_no_positivo" if i == 2 else "",
            })
        with self.csv_file.open("w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(INPUT_COLUMNS) + [
                "tasa_ejecucion", "modificacion_sobre_pia",
                "participacion_devengado_proyectos", "log1p_pim",
                "n_ajustes_mensuales_negativos", "n_montos_negativos", "apto_candidato"
            ])
            writer.writeheader()
            writer.writerows(self.rows)
        self.parent_report.write_text(json.dumps({
            "mode": "full", "integrity": {"row_balance": True, "totals_equal_aggregates": True},
            "totals": {"municipality_year_profiles": len(self.rows),
                       "local_accepted": sum(int(r["n_lineas"]) for r in self.rows)}
        }), encoding="utf-8")

    def test_type_classification(self):
        self.assertEqual(entity_type("MANCOMUNIDAD MUNICIPAL Qhapaq"), "mancomunidad")
        self.assertEqual(entity_type("MUNICIPALIDAD DISTRITAL DE Puno"), "municipalidad")
        self.assertEqual(entity_type("OTRA UNIDAD"), "otra_ejecutora_local")

    def test_percentile(self):
        self.assertAlmostEqual(percentile([0,10,20,30,40], .25), 10)
        self.assertAlmostEqual(percentile([0,10,20,30,40], .99), 39.6)

    def test_pia_zero_not_excluded(self):
        r = self.rows[2]
        f = calculate_features(r)
        self.assertGreater(f["modificacion_log_pim_pia"], 0)
        self.assertGreater(f["tasa_ejecucion"], 0)

    def test_run_and_validate(self):
        result = run(self.csv_file, self.parent_report, self.out)
        self.assertEqual(result["input_profiles"], 20)
        self.assertEqual(result["eligible_profiles"], 18)
        with (self.out / "kmeans_keys.csv").open(encoding="utf-8", newline="") as f:
            keys = list(csv.DictReader(f))
        self.assertTrue(any(r["sec_ejec"] == str(300002) for r in keys))
        self.assertFalse(any(r["sec_ejec"] == str(300001) for r in keys))
        self.assertFalse(any(r["sec_ejec"] == str(300004) for r in keys))
        check = validate(self.out, self.csv_file, self.parent_report)
        self.assertEqual(check["status"], "PASS", check["errors"])
        self.assertEqual(check["perfiles_modelo"], 18)

    def test_matrix_tamper_detected(self):
        run(self.csv_file, self.parent_report, self.out)
        p = self.out / "kmeans_matrix.csv"
        original = p.read_text(encoding="utf-8")
        lines = original.splitlines()
        fields = lines[1].split(",")
        fields[0] = "100000"
        lines[1] = ",".join(fields)
        p.write_text("\n".join(lines) + "\n", encoding="utf-8")
        result = validate(self.out, self.csv_file, self.parent_report)
        self.assertEqual(result["status"], "FAIL")
        self.assertTrue(any("numéricos" in e for e in result["errors"]))

    def test_changed_source_detected(self):
        run(self.csv_file, self.parent_report, self.out)
        with self.csv_file.open("a", encoding="utf-8") as f:
            f.write("\n")
        result = validate(self.out, self.csv_file, self.parent_report)
        self.assertEqual(result["status"], "FAIL")
        self.assertTrue(any("cambió" in e for e in result["errors"]))


if __name__ == "__main__":
    unittest.main()
