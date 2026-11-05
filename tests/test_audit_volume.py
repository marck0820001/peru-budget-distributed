import csv
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts' / 'eda'))
from audit_volume import audit_file, locate_files, summarize, classify_local, classify_project_text


class VolumeAuditTests(unittest.TestCase):
    def test_classification_conservative(self):
        self.assertTrue(classify_local('M'))
        self.assertTrue(classify_local('Gobiernos Locales'))
        self.assertFalse(classify_local('3'))
        self.assertTrue(classify_project_text('PROYECTO'))
        self.assertFalse(classify_project_text('2'))

    def test_streaming_counts(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / '2024-Gasto-Devengado.csv'
            with path.open('w', newline='', encoding='utf-8') as f:
                w = csv.writer(f, delimiter=';')
                w.writerow(['ANO_EJE', 'NIVEL_GOBIERNO', 'SEC_EJEC', 'TIPO_ACT_PROY', 'DEPARTAMENTO_EJECUTORA_NOMBRE'])
                w.writerow(['2024', 'M', '100', 'PROYECTO', 'LIMA'])
                w.writerow(['2024', 'M', '101', 'ACTIVIDAD', 'CUSCO'])
                w.writerow(['2024', 'N', '102', 'PROYECTO', 'LIMA'])
                w.writerow(['2024', 'M', '103', '2', 'PIURA'])
            report = audit_file('2024_gasto', path, mode='full', progress=0)
            self.assertEqual(report['filas_validas'], 4)
            self.assertEqual(report['gobiernos_locales'], 3)
            self.assertEqual(report['proyectos_etiquetados'], 2)
            self.assertEqual(report['locales_y_proyectos_etiquetados'], 1)
            self.assertEqual(report['entidades_locales_unicas'], 3)
            found, _ = locate_files(Path(temp))
            self.assertEqual(found[0][0], '2024_gasto')

    def test_quick_is_not_full(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / '2025-Gasto-Devengado-Mensual.csv'
            path.write_text('ANO_EJE;NIVEL_GOBIERNO\n2025;M\n2025;M\n2025;N\n', encoding='utf-8')
            report = audit_file('2025_gasto', path, mode='quick', max_rows=2, progress=0)
            self.assertEqual(report['filas_leidas'], 2)
            self.assertFalse(report['conteo_completo'])
            text, decision = summarize([report], mode='quick')
            self.assertIsNone(decision['supera_2m_locales_preliminar'])
            self.assertIn('Pendiente', text)


if __name__ == '__main__':
    unittest.main()
