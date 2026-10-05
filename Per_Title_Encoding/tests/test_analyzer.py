import unittest

from modules.analyzer import AnalysisModule
from modules.ladder_selector import LadderSelectionModule


class AnalyzerAcceptanceTests(unittest.TestCase):
    def test_ac04_dominated_point_removed(self):
        # AC04 from BA document: A=(800,78), B=(1000,76) => B is dominated.
        rows = [
            {
                "candidate_id": "A",
                "actual_bitrate_kbps": 800.0,
                "vmaf": 78.0,
                "duration_sec": 20.0,
                "output_path": "a.mp4",
                "status": "success",
            },
            {
                "candidate_id": "B",
                "actual_bitrate_kbps": 1000.0,
                "vmaf": 76.0,
                "duration_sec": 20.0,
                "output_path": "b.mp4",
                "status": "success",
            },
        ]
        result = AnalysisModule().analyze(rows)
        self.assertEqual([x["candidate_id"] for x in result["pareto"]], ["A"])

    def test_ladder_never_invents_points(self):
        pareto = [
            {"candidate_id": "A", "actual_bitrate_kbps": 400.0, "vmaf": 70.0},
            {"candidate_id": "B", "actual_bitrate_kbps": 800.0, "vmaf": 78.0},
            {"candidate_id": "C", "actual_bitrate_kbps": 1500.0, "vmaf": 86.0},
        ]
        ladder, _ = LadderSelectionModule().select(
            pareto, pareto, target_rungs=4, min_bitrate_ratio=1.35, min_vmaf_gain=3.0
        )
        self.assertLessEqual(len(ladder), 3)
        self.assertTrue(all(x["candidate_id"] in {"A", "B", "C"} for x in ladder))


if __name__ == "__main__":
    unittest.main()
