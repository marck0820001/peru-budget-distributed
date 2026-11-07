import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "benchmarks"))
from summarize_massive import summarize


class TestSummarize(unittest.TestCase):
    def test_speedup(self):
        rows = []
        for w, times in [(1, [100, 102, 101]), (2, [60, 62, 61])]:
            for i, duration in enumerate(times):
                rows.append({"K": "3", "Workers": str(w), "DuracionMs": str(duration),
                             "Inercia": "200.25", "Iteraciones": "10", "Convergio": "True", "Filas": "10000"})
        results = summarize(rows)
        self.assertEqual(results[0]["mediana_ms"], 101)
        self.assertAlmostEqual(results[1]["speedup"], 101 / 61, places=4)
        self.assertTrue(results[1]["convergieron_todas"])

    def test_requires_baseline(self):
        with self.assertRaises(ValueError):
            summarize([{"K": "2", "Workers": "4", "DuracionMs": "20", "Inercia": "1", "Iteraciones": "1", "Convergio": "True", "Filas": "123"}])


if __name__ == "__main__":
    unittest.main()
