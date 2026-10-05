from __future__ import annotations

import csv
import json
import math
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt


class OutputModule:
    def __init__(self, run_dir: str | Path):
        self.run_dir = Path(run_dir)
        self.analysis_dir = self.run_dir / "analysis"
        self.ladder_dir = self.run_dir / "ladder"
        self.figures_dir = self.run_dir / "figures"
        for d in [self.analysis_dir, self.ladder_dir, self.figures_dir]:
            d.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _serializable(obj):
        if isinstance(obj, Path):
            return str(obj)
        raise TypeError(f"Not JSON serializable: {type(obj)}")

    def write_csv(self, path: str | Path, rows: list[dict[str, Any]]) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        if not rows:
            path.write_text("", encoding="utf-8")
            return
        fields = []
        for row in rows:
            for key in row.keys():
                if key not in fields:
                    fields.append(key)
        with path.open("w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
            writer.writeheader()
            for row in rows:
                writer.writerow(row)

    def write_json(self, path: str | Path, data: Any) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2, default=self._serializable)

    def save_analysis(self, candidates, valid, pareto, hull, ladder, selection_reason):
        self.write_csv(self.run_dir / "candidates.csv", candidates)
        self.write_csv(self.analysis_dir / "valid_candidates.csv", valid)
        self.write_csv(self.analysis_dir / "pareto.csv", pareto)
        self.write_csv(self.analysis_dir / "convex_hull.csv", hull)
        self.write_csv(self.ladder_dir / "ladder.csv", ladder)
        self.write_json(
            self.ladder_dir / "ladder.json",
            {
                "selected_rungs": len(ladder),
                "reason": selection_reason,
                "ladder": ladder,
            },
        )
        self.plot_rate_quality(valid, pareto, hull, ladder)

    def plot_rate_quality(self, valid, pareto, hull, ladder):
        fig = plt.figure(figsize=(9, 6))
        ax = fig.add_subplot(111)

        if valid:
            xs = [float(c["actual_bitrate_kbps"]) for c in valid]
            ys = [float(c["vmaf"]) for c in valid]
            ax.scatter(xs, ys, label="Valid candidates", marker="o")

        if pareto:
            p = sorted(pareto, key=lambda c: float(c["actual_bitrate_kbps"]))
            ax.plot(
                [float(c["actual_bitrate_kbps"]) for c in p],
                [float(c["vmaf"]) for c in p],
                marker="x",
                linestyle="--",
                label="Pareto",
            )

        if hull:
            h = sorted(hull, key=lambda c: float(c["actual_bitrate_kbps"]))
            ax.plot(
                [float(c["actual_bitrate_kbps"]) for c in h],
                [float(c["vmaf"]) for c in h],
                marker="s",
                linewidth=2,
                label="Upper hull",
            )

        if ladder:
            l = sorted(ladder, key=lambda c: float(c["actual_bitrate_kbps"]))
            ax.scatter(
                [float(c["actual_bitrate_kbps"]) for c in l],
                [float(c["vmaf"]) for c in l],
                marker="*",
                s=120,
                label="Selected ladder",
            )

        ax.set_xscale("log", base=2)
        ax.set_xlabel("Actual video bitrate (kbps, log2 scale)")
        ax.set_ylabel("VMAF")
        ax.set_title("Rate–Quality curve / Pareto / Upper Convex Hull")
        ax.grid(True, which="both", alpha=0.25)
        ax.legend()
        fig.tight_layout()
        fig.savefig(self.figures_dir / "rate_quality.png", dpi=160)
        plt.close(fig)

    def plot_si_ti(self, si_ti_csv: str | Path):
        path = Path(si_ti_csv)
        if not path.exists() or path.stat().st_size == 0:
            return
        times, sis, tis = [], [], []
        with path.open("r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                t = row.get("time_sec")
                si = row.get("si")
                ti = row.get("ti")
                try:
                    times.append(float(t) if t not in (None, "", "None") else math.nan)
                    sis.append(float(si) if si not in (None, "", "None") else math.nan)
                    tis.append(float(ti) if ti not in (None, "", "None") else math.nan)
                except ValueError:
                    continue

        fig = plt.figure(figsize=(9, 5))
        ax = fig.add_subplot(111)
        ax.plot(times, sis, label="SI")
        ax.plot(times, tis, label="TI")
        ax.set_xlabel("Time (s)")
        ax.set_ylabel("SI / TI")
        ax.set_title("Spatial Information / Temporal Information")
        ax.grid(True, alpha=0.25)
        ax.legend()
        fig.tight_layout()
        fig.savefig(self.figures_dir / "si_ti.png", dpi=160)
        plt.close(fig)
