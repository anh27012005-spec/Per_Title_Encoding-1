from __future__ import annotations

import itertools
import math
from typing import Any


class LadderSelectionModule:
    @staticmethod
    def _is_valid_sequence(seq: tuple[dict[str, Any], ...], min_ratio: float, min_gain: float) -> bool:
        if not seq:
            return False
        for a, b in zip(seq, seq[1:]):
            ra, rb = float(a["actual_bitrate_kbps"]), float(b["actual_bitrate_kbps"])
            qa, qb = float(a["vmaf"]), float(b["vmaf"])
            if rb <= ra or qb <= qa:
                return False
            if rb / ra < min_ratio:
                return False
            if qb - qa < min_gain:
                return False
        return True

    def select(
        self,
        pareto: list[dict[str, Any]],
        hull: list[dict[str, Any]],
        target_rungs: int,
        min_bitrate_ratio: float,
        min_vmaf_gain: float,
    ) -> tuple[list[dict[str, Any]], str]:
        if not pareto:
            return [], "Không có điểm Pareto hợp lệ từ dữ liệu đo."

        pool = sorted(pareto, key=lambda c: (float(c["actual_bitrate_kbps"]), float(c["vmaf"])))
        hull_ids = {c["candidate_id"] for c in hull}
        max_k = min(int(target_rungs), len(pool))

        best = None
        best_score = None
        for k in range(max_k, 0, -1):
            for combo in itertools.combinations(pool, k):
                if not self._is_valid_sequence(combo, min_bitrate_ratio, min_vmaf_gain):
                    continue
                hull_count = sum(1 for c in combo if c["candidate_id"] in hull_ids)
                if k >= 2:
                    coverage = math.log2(float(combo[-1]["actual_bitrate_kbps"]) / float(combo[0]["actual_bitrate_kbps"]))
                    vmaf_span = float(combo[-1]["vmaf"]) - float(combo[0]["vmaf"])
                else:
                    coverage = 0.0
                    vmaf_span = 0.0
                # First maximize number of selected rungs; then prefer hull points and wide bitrate coverage.
                score = (k, hull_count, coverage, vmaf_span)
                if best_score is None or score > best_score:
                    best_score = score
                    best = combo
            if best is not None:
                break

        if best is None:
            return [], "Không có tổ hợp nào thỏa ngưỡng bitrate/VMAF đã cấu hình."

        ladder = [dict(c) for c in best]
        for i, c in enumerate(ladder, start=1):
            c["rung"] = i
            c["on_upper_hull"] = c["candidate_id"] in hull_ids

        if len(ladder) < target_rungs:
            reason = (
                f"Yêu cầu {target_rungs} mức nhưng chỉ chọn được {len(ladder)} mức thực đo "
                f"thỏa min_bitrate_ratio={min_bitrate_ratio} và min_vmaf_gain={min_vmaf_gain}."
            )
        else:
            reason = "Đủ số mức yêu cầu; ưu tiên điểm hull và độ phủ bitrate rộng."
        return ladder, reason
