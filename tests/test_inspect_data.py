import csv
import importlib.util
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts' / 'eda' / 'inspect_data.py'
spec = importlib.util.spec_from_file_location('inspect_data', SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class InspectTest(unittest.TestCase):
    def test_delimiter_quoted_comma(self):
        self.assertEqual(module.delimiter_from_text('CODIGO;NOMBRE;MONTO_PIM\n1;"Municipalidad, Lima";30\n'), ';')

    def test_number_formats(self):
        self.assertEqual(module.parse_number('1.234,56'), 1234.56)
        self.assertEqual(module.parse_number('1,234.56'), 1234.56)
        self.assertEqual(module.parse_number('-10,25'), -10.25)

    def test_quick_and_full(self):
        with tempfile.TemporaryDirectory() as temp:
            p = Path(temp) / '2024-Gasto-Devengado.csv'
            with p.open('w', encoding='utf-8-sig', newline='') as f:
                writer = csv.writer(f, delimiter=';')
                writer.writerow(['NIVEL_GOBIERNO', 'EJECUTORA_NOMBRE', 'MONTO_PIM'])
                writer.writerows([['M', 'MUNICIPALIDAD X', '100.50'], ['M', 'MUNICIPALIDAD Y', '-20'], ['R', 'REGIONAL', '']])
            quick = module.inspect_file('2024_gasto', p, 'quick', 2, 2, 0)
            full = module.inspect_file('2024_gasto', p, 'full', 2, 2, 0)
            self.assertEqual(quick['filas_analizadas'], 2)
            self.assertEqual(full['filas_analizadas'], 3)
            self.assertEqual(full['filas_validas'], 3)
            self.assertEqual(full['perfiles_columnas'][2]['numericos_negativos'], 1)
            self.assertEqual(full['perfiles_columnas'][2]['vacios'], 1)


if __name__ == '__main__':
    unittest.main()
