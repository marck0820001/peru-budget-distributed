"""Pruebas del EDA: archivos pequeños sintéticos, sin datos originales MEF."""
from __future__ import annotations
import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "eda"))
from exploratory_analysis import analyze, parse_money, safe_ratio


class TestEDAMef(unittest.TestCase):
    def make_data(self, folder: Path):
        gasto_fields = ["ANO_EJE", "NIVEL_GOBIERNO", "SEC_EJEC", "EJECUTORA_NOMBRE",
                        "DEPARTAMENTO_EJECUTORA_NOMBRE", "TIPO_ACT_PROY", "PRODUCTO_PROYECTO",
                        "MONTO_PIA", "MONTO_PIM", "MONTO_DEVENGADO_ANUAL"]
        from exploratory_analysis import MONTHS
        gasto_fields += [f"MONTO_DEVENGADO_{month}" for month in MONTHS]
        gasto_rows = [
            ["2024", "M", "101", "Municipalidad A", "LIMA", "PROYECTO", "P111", "50", "100", "40"],
            ["2024", "M", "101", "Municipalidad A", "LIMA", "ACTIVIDAD", "A11", "20", "30", "15"],
            ["2024", "R", "222", "Regional", "LIMA", "PROYECTO", "P222", "10", "30", "5"],
        ]
        for y in (2024, 2025):
            rows = [[str(y)] + r[1:] for r in gasto_rows]
            for r in rows:
                dev = float(r[9])
                r.extend([str(dev)] + ["0"]*11)
            with (folder/f"{y}-Gasto-Devengado-Mensual.csv").open("w", newline="", encoding="utf-8") as stream:
                wr = csv.writer(stream)
                wr.writerow(gasto_fields)
                wr.writerows(rows)
        pi_fields = ["ANO_EJE", "NIVEL_GOBIERNO", "SEC_EJEC", "EJECUTORA_NOMBRE",
                     "DEPARTAMENTO_EJECUTORA_NOMBRE", "TIPO_ACT_PROY",
                     "TIPO_ACT_PROY_NOMBRE", "PRODUCTO_PROYECTO", "MONTO_PIA", "MONTO_PIM"]
        for y in (2024, 2025):
            with (folder/f"{y}-Seguimiento-PI.csv").open("w", newline="", encoding="utf-8") as stream:
                wr = csv.writer(stream)
                wr.writerow(pi_fields)
                wr.writerow(["2020", "M", "101", "Municipalidad A", "LIMA", "2", "PROYECTO", "P111", "50", "100"])
                wr.writerow([str(y), "M", "101", "Municipalidad A", "LIMA", "2", "PROYECTO", "P777", "25", "40"])

    def test_numeric(self):
        self.assertEqual(parse_money("1,200.50"), 1200.50)
        self.assertEqual(parse_money("1.200,50"), 1200.50)
        self.assertIsNone(parse_money(""))
        self.assertIsNone(safe_ratio(1, 0))

    def test_full_run(self):
        with tempfile.TemporaryDirectory() as d:
            base = Path(d)
            raw, out = base/"raw", base/"processed"
            raw.mkdir()
            self.make_data(raw)
            result = analyze(raw, out, "full", 10, 50, 0)
            self.assertEqual(result["indicadores"]["filas_locales_gasto"], 4)
            self.assertEqual(result["indicadores"]["filas_proyectos_municipales_gasto"], 2)
            self.assertEqual(result["indicadores"]["entidades_anio_unicas_gasto"], 2)
            self.assertEqual(result["indicadores"]["claves_PI_en_ambas_publicaciones"], 1)
            report = json.loads((out/"reporte_eda.json").read_text(encoding="utf-8"))
            pi_2025 = next(x for x in report["archivos"] if x["dataset"] == "2025_pi")
            self.assertEqual(pi_2025["anio_eje_distinto_nombre_archivo"], 1)
            self.assertEqual(pi_2025["tipo_proyecto_descripcion"][0]["codigo"], "2")
            with (out/"municipalidades_indicadores_exploratorios.csv").open(encoding="utf-8-sig") as f:
                rows = list(csv.DictReader(f))
            self.assertEqual(len(rows), 2)
            self.assertAlmostEqual(float(rows[0]["tasa_ejecucion_sobre_pim"]), 55/130, places=6)
            self.assertTrue((base/"eda_estadistico_mef_full.zip").exists())

    def test_quick_warning(self):
        with tempfile.TemporaryDirectory() as d:
            raw = Path(d)/"raw"
            raw.mkdir()
            self.make_data(raw)
            result = analyze(raw, Path(d)/"out", "quick", 1, 10, 0)
            self.assertEqual(result["indicadores"]["filas_locales_gasto"], 2)
            self.assertTrue(all(not r["conteo_completo"] for r in result["archivos"]))


if __name__ == "__main__":
    unittest.main()
