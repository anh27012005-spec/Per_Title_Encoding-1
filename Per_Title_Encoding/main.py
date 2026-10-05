from __future__ import annotations

import argparse
import json
import logging
import shutil
import sys
from datetime import datetime
from pathlib import Path

from modules.analyzer import AnalysisModule
from modules.config_manager import ConfigError, ConfigurationManager
from modules.encoder import EncodingModule
from modules.ladder_selector import LadderSelectionModule
from modules.measurement import MeasurementModule
from modules.video_processor import VideoProcessingError, VideoProcessor
from modules.visualizer import OutputModule


def build_logger(log_file: Path) -> logging.Logger:
    logger = logging.getLogger("per_title_encoding")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()

    fmt = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    logger.addHandler(sh)

    fh = logging.FileHandler(log_file, encoding="utf-8")
    fh.setFormatter(fmt)
    logger.addHandler(fh)
    return logger


def make_run_dir(output_root: str | Path, input_video: str | Path) -> Path:
    stem = Path(input_video).stem
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = Path(output_root) / f"{stem}_{stamp}"
    for name in ["encoded", "metrics", "analysis", "ladder", "figures", "reference"]:
        (run_dir / name).mkdir(parents=True, exist_ok=True)
    return run_dir


def main() -> int:
    parser = argparse.ArgumentParser(description="Per-Title Encoding demo pipeline")
    parser.add_argument("--config", default="config.yaml", help="Đường dẫn config.yaml")
    args = parser.parse_args()

    try:
        manager = ConfigurationManager(args.config)
        cfg, tools = manager.load_and_validate()
    except ConfigError as exc:
        print(f"[CONFIG ERROR] {exc}")
        return 2

    run_dir = make_run_dir(cfg["output_root"], cfg["input_video"])
    logger = build_logger(run_dir / "run.log")
    logger.info("Bắt đầu pipeline Per-Title Encoding")
    logger.info("Run directory: %s", run_dir)

    shutil.copy2(manager.config_path, run_dir / "config_used.yaml")

    experiment = {
        "started_at": datetime.now().isoformat(timespec="seconds"),
        "input_video": cfg["input_video"],
        "config_path": str(manager.config_path),
        "ffmpeg_version": tools.ffmpeg_version,
        "ffprobe_version": tools.ffprobe_version,
        "libvmaf_available": tools.libvmaf_available,
        "status": "running",
    }

    output = OutputModule(run_dir)
    try:
        # 1) Video Processor: metadata -> normalized reference -> SI/TI
        processor = VideoProcessor(tools.ffmpeg, tools.ffprobe, logger)
        reference_ext = ".mkv" if str(cfg.get("reference_codec", "ffv1")).lower() == "ffv1" else ".mp4"
        reference_path = run_dir / "reference" / f"reference{reference_ext}"
        ref_meta = processor.create_reference(
            cfg["input_video"],
            reference_path,
            float(cfg["duration_sec"]),
            float(cfg["fps"]),
            list(cfg["reference_resolution"]),
            str(cfg.get("reference_codec", "ffv1")),
        )
        si_ti = processor.compute_si_ti(reference_path, run_dir / "metrics" / "si_ti.csv")
        output.plot_si_ti(si_ti["series_csv"])
        logger.info(
            "SI/TI: SI_mean=%.3f, SI_max=%.3f, TI_mean=%s, TI_max=%s",
            si_ti["si_mean"],
            si_ti["si_max"],
            f"{si_ti['ti_mean']:.3f}" if si_ti["ti_mean"] is not None else "N/A",
            f"{si_ti['ti_max']:.3f}" if si_ti["ti_max"] is not None else "N/A",
        )

        # 2) Encoding Module: Cartesian product resolution x bitrate
        encoder = EncodingModule(tools.ffmpeg, logger)
        candidates = encoder.build_candidates(cfg["resolutions"], cfg["bitrates_kbps"])
        logger.info("Tạo %d candidate.", len(candidates))

        encoded = []
        for c in candidates:
            encoded.append(
                encoder.encode_one(reference_path, c, run_dir / "encoded", cfg["encoding"])
            )

        # 3) Measurement Module: actual bitrate, size, duration, VMAF
        measurement = MeasurementModule(tools.ffmpeg, tools.ffprobe, logger)
        measured = []
        for c in encoded:
            measured.append(
                measurement.measure_one(
                    c,
                    reference_path,
                    list(cfg["reference_resolution"]),
                    run_dir / "metrics",
                    cfg["measurement"],
                )
            )

        # 4) Analysis Module: valid -> Pareto -> upper convex hull on log2 bitrate
        analyzer = AnalysisModule()
        analysis = analyzer.analyze(measured)
        logger.info(
            "Phân tích: valid=%d, pareto=%d, hull=%d",
            len(analysis["valid"]),
            len(analysis["pareto"]),
            len(analysis["hull"]),
        )

        # 5) Ladder Selection Module
        selector = LadderSelectionModule()
        sel = cfg["selection"]
        ladder, reason = selector.select(
            analysis["pareto"],
            analysis["hull"],
            int(sel["target_rungs"]),
            float(sel["min_bitrate_ratio"]),
            float(sel["min_vmaf_gain"]),
        )
        logger.info("Ladder chọn được %d mức. %s", len(ladder), reason)

        # 6) Output Module
        output.save_analysis(
            measured,
            analysis["valid"],
            analysis["pareto"],
            analysis["hull"],
            ladder,
            reason,
        )

        experiment.update({
            "finished_at": datetime.now().isoformat(timespec="seconds"),
            "status": "success",
            "reference": ref_meta,
            "si_ti_summary": si_ti,
            "candidate_count": len(measured),
            "valid_count": len(analysis["valid"]),
            "pareto_count": len(analysis["pareto"]),
            "hull_count": len(analysis["hull"]),
            "selected_rungs": len(ladder),
            "selection_reason": reason,
        })
        output.write_json(run_dir / "experiment.json", experiment)

        print("\n=== HOÀN TẤT ===")
        print(f"Kết quả: {run_dir}")
        print(f"Ladder: {run_dir / 'ladder' / 'ladder.csv'}")
        print(f"Đồ thị: {run_dir / 'figures' / 'rate_quality.png'}")
        return 0

    except (VideoProcessingError, Exception) as exc:
        logger.exception("Pipeline thất bại: %s", exc)
        experiment.update({
            "finished_at": datetime.now().isoformat(timespec="seconds"),
            "status": "failed",
            "error": str(exc),
        })
        try:
            output.write_json(run_dir / "experiment.json", experiment)
        except Exception:
            pass
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
