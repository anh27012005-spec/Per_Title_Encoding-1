from __future__ import annotations

import math
from typing import Any


class AnalysisModule:
    REQUIRED = ("actual_bitrate_kbps", "vmaf", "duration_sec", "output_path")

    @classmethod
    def valid_candidates(cls, candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
        valid = []
        for c in candidates:
            if c.get("status") != "success":
                continue
            if not all(k in c for k in cls.REQUIRED):
                continue
            try:
                r = float(c["actual_bitrate_kbps"])
                q = float(c["vmaf"])
                d = float(c["duration_sec"])
            except (TypeError, ValueError):
                continue
            if r <= 0 or d <= 0 or not math.isfinite(r) or not math.isfinite(q):
                continue
            valid.append(dict(c))
        return valid

    @staticmethod
    def pareto_front(valid: list[dict[str, Any]]) -> list[dict[str, Any]]:
        pareto = []
        for i, a in enumerate(valid):
            ra, qa = float(a["actual_bitrate_kbps"]), float(a["vmaf"])
            dominated = False
            for j, b in enumerate(valid):
                if i == j:
                    continue
                rb, qb = float(b["actual_bitrate_kbps"]), float(b["vmaf"])
                if rb <= ra and qb >= qa and (rb < ra or qb > qa):
                    dominated = True
                    break
            if not dominated:
                pareto.append(dict(a))

        # Deterministic handling for equal coordinates: keep lexicographically smallest candidate_id.
        dedup: dict[tuple[float, float], dict[str, Any]] = {}
        for c in pareto:
            key = (round(float(c["actual_bitrate_kbps"]), 9), round(float(c["vmaf"]), 9))
            if key not in dedup or str(c["candidate_id"]) < str(dedup[key]["candidate_id"]):
                dedup[key] = c
        return sorted(dedup.values(), key=lambda c: (float(c["actual_bitrate_kbps"]), float(c["vmaf"])))

    @staticmethod
    def upper_hull(pareto: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if len(pareto) <= 2:
            return [dict(c) for c in pareto]

        points = []
        for c in pareto:
            x = math.log2(float(c["actual_bitrate_kbps"]))
            y = float(c["vmaf"])
            points.append((x, y, c))
        points.sort(key=lambda t: (t[0], t[1], str(t[2]["candidate_id"])))

        hull: list[tuple[float, float, dict[str, Any]]] = []

        def cross(a, b, c):
            return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])

        # Upper concave envelope: slopes should not increase as bitrate grows.
        # Collinear middle points are removed; endpoints remain real measured candidates.
        eps = 1e-12
        for p in points:
            while len(hull) >= 2 and cross(hull[-2], hull[-1], p) >= -eps:
                hull.pop()
            hull.append(p)
        return [dict(t[2]) for t in hull]

    def analyze(self, candidates: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
        valid = self.valid_candidates(candidates)
        pareto = self.pareto_front(valid)
        hull = self.upper_hull(pareto)
        hull_ids = {c["candidate_id"] for c in hull}
        for c in pareto:
            c["on_upper_hull"] = c["candidate_id"] in hull_ids
        return {"valid": valid, "pareto": pareto, "hull": hull}
