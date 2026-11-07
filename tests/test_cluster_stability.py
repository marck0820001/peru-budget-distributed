import importlib.util
import pathlib
import unittest

S = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "analysis" / "analyze_cluster_stability.py"
spec = importlib.util.spec_from_file_location("analysis", S)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def part(labels):
    return {(str(i), str(i)): {"cluster": int(label)} for i, label in enumerate(labels)}


class TestARI(unittest.TestCase):
    def test_identity(self):
        self.assertAlmostEqual(m.adjusted_rand_index(part([0, 0, 1, 1]), part([0, 0, 1, 1])), 1)

    def test_label_permutation(self):
        self.assertAlmostEqual(m.adjusted_rand_index(part([0, 0, 1, 1]), part([1, 1, 0, 0])), 1)

    def test_nonidentical(self):
        self.assertLess(m.adjusted_rand_index(part([0, 0, 1, 1]), part([0, 1, 0, 1])), 1)

    def test_different_keys(self):
        with self.assertRaises(ValueError):
            m.adjusted_rand_index(part([0, 1]), part([0, 1, 0]))


if __name__ == "__main__":
    unittest.main()
