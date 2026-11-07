import importlib.util
import json
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts' / 'validation' / 'validate_massive_pc3.py'
spec = importlib.util.spec_from_file_location('validate_massive_pc3', SCRIPT)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

class ValidateMassiveTest(unittest.TestCase):
    def test_relative_closeness(self):
        self.assertTrue(mod.rel_close(10, 10 + 1e-10))
        self.assertFalse(mod.rel_close(10, 12))

    def test_markdown(self):
        d = {'rows': 3642510, 'project_rows': 578956, 'k':3, 'dimensions':9,
             'iterations':8, 'cluster_sizes':[1502969,1037720,1101821],
             'training_inertia_4workers':15719788.26, 'recomputed_inertia':15719788.26,
             'relative_inertia_discrepancy':0.0, 'max_centroid_diff_across_workers':0.0,
             'clusters':[{'cluster':0, 'rows':1502969,'share_pct':41.26,'project_pct':17.23,'pim_zero_pct':95.98,'dev_zero_pct':0.004}],
             'benchmarks':[{'workers':1,'median_ms':4641,'speedup':1,'efficiency':1}],
             'limitations':['La unidad es una línea.']}
        txt = mod.markdown(d)
        self.assertIn('3,642,510', txt)
        self.assertIn('17.23%', txt)
        self.assertIn('La unidad es una línea.', txt)

if __name__ == '__main__': unittest.main()
