"""Pruebas del pipeline de Gasto Devengado usando CSV sinteticos pequenos."""
import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts" / "eda"
sys.path.insert(0, str(SCRIPT_DIR))
from preprocess_data import MONEY_COLS, MONTH_COLS, process, parse_cents
from validate_data import validate


class PreprocessMEFTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.raw = self.root / "data" / "raw"
        self.out = self.root / "data" / "processed" / "preprocessing_mef"
        self.raw.mkdir(parents=True)
        self.fields = ["ANO_EJE", "NIVEL_GOBIERNO", "SEC_EJEC", "EJECUTORA_NOMBRE",
                       "DEPARTAMENTO_EJECUTORA_NOMBRE", "TIPO_ACT_PROY",
                       "PRODUCTO_PROYECTO", "PRODUCTO_PROYECTO_NOMBRE", *MONEY_COLS]

    def record(self, year, entity="300001", gov="M", atype="PROYECTO", code="12345",
               pia="100.00", pim="150.00", dev="10.00", jan="8.00", dec="2.00"):
        d = {c: "0.00" for c in self.fields}
        d.update({"ANO_EJE": str(year), "NIVEL_GOBIERNO": gov, "SEC_EJEC": entity,
                  "EJECUTORA_NOMBRE": "MUNICIPALIDAD PROVINCIAL DEMO",
                  "DEPARTAMENTO_EJECUTORA_NOMBRE": "LIMA",
                  "TIPO_ACT_PROY": atype, "PRODUCTO_PROYECTO": code,
                  "PRODUCTO_PROYECTO_NOMBRE": "INVERSION DEMO",
                  "MONTO_PIA": pia, "MONTO_PIM": pim, "MONTO_DEVENGADO_ANUAL": dev,
                  "MONTO_DEVENGADO_ENERO": jan, "MONTO_DEVENGADO_DICIEMBRE": dec})
        return d

    def write(self, year, rows):
        name = (f"{year}-Gasto-Devengado.csv" if year == 2024
                else f"{year}-Gasto-Devengado-Mensual.csv")
        with (self.raw / name).open("w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=self.fields)
            w.writeheader()
            w.writerows(rows)

    def make_data(self):
        self.write(2024, [
            self.record(2024, gov="R"),
            self.record(2024, atype="PROYECTO", code="A"),
            self.record(2024, atype="ACTIVIDAD", code="0", pia="0", pim="50", dev="30", jan="30", dec="0"),
            self.record(2024, atype="PROYECTO", code="A", pia="10", pim="20", dev="3", jan="-2", dec="5"),
            self.record(2024, atype="PROYECTO", code="", pia="0", pim="10", dev="2", jan="2", dec="0"),
            self.record(2024, atype="PROYECTO", code="X", pia="0", pim="bad", dev="2", jan="2", dec="0"),
            self.record(2024, atype="ACTIVIDAD", code="Z", pia="0", pim="10", dev="2", jan="1", dec="0"),
        ])
        self.write(2025, [self.record(2025, entity="300002", pia="200", pim="250", dev="50", jan="40", dec="10")])

    def test_money_parser_no_silent_round(self):
        self.assertEqual(parse_cents("-239394.21"), (-23939421, None))
        self.assertEqual(parse_cents("1.230"), (123, None))
        self.assertEqual(parse_cents("1.239")[1], "mas_de_dos_decimales")
        self.assertEqual(parse_cents(""), (None, "vacio"))
        self.assertEqual(parse_cents("1,239")[1], "formato_ambiguo")

    def test_preprocessing_and_validation(self):
        self.make_data()
        result = process(self.raw, self.out, mode="full", write_lines=True, progress=0)
        t = result["totals"]
        self.assertEqual(t["source_rows_read"], 8)
        self.assertEqual(t["local_rows"], 7)
        self.assertEqual(t["local_accepted"], 5)
        self.assertEqual(t["local_rejected"], 2)
        self.assertEqual(t["municipality_year_profiles"], 2)
        self.assertEqual(t["project_executor_year_profiles"], 2)
        self.assertEqual(t["local_project_rows"], 4)
        self.assertEqual(t["sum_local_pia_soles"], "310.00")
        self.assertEqual(t["sum_local_pim_soles"], "480.00")
        self.assertTrue(all(result["integrity"].values()))
        checked = validate(self.out, require_full=True, check_lines=True)
        self.assertEqual(checked["status"], "PASS")
        self.assertEqual(checked["counts"]["candidate_municipality_profiles"], 1)

    def test_smoke_is_explicitly_partial(self):
        self.make_data()
        r = process(self.raw, self.out, mode="smoke", smoke_local=1, progress=0)
        self.assertTrue(r["not_full_dataset"])
        v = validate(self.out, require_full=True)
        self.assertEqual(v["status"], "FAIL")


if __name__ == "__main__":
    unittest.main()
