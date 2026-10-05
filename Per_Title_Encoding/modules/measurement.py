from __future__ import annotations

import json
import math
import subprocess
from pathlib import Path
from typing import Any


class MeasurementModule:
    def __init__(self, ffmpeg: str, ffprobe: str, logger):
        self.ffmpeg = ffmpeg
        self.ffprobe = ffprobe
        self.logger = logger

    def _probe_video(self, path: str | Path) -> dict[str, Any]:
        cmd = [
            self.ffprobe, "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream=bit_rate,duration,width,height:format=duration,size,bit_rate",
            "-of", "json",
            str(path),
        ]
        p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
        if p.returncode != 0:
            raise RuntimeError(p.stderr.strip() or "ffprobe failed")
        return json.loads(p.stdout)

    @staticmethod
    def _to_float(value) -> float | None:
        try:
            v = float(value)
            return v if math.isfinite(v) else None
        except (TypeError, ValueError):
            return None

    def actual_bitrate(self, path: str | Path) -> tuple[float, float, float, str]:
        data = self._probe_video(path)
        streams = data.get("streams") or []
        stream = streams[0] if streams else {}
        fmt = data.get("format") or {}

        duration = self._to_float(stream.get("duration")) or self._to_float(fmt.get("duration"))
        if not duration or duration <= 0:
            raise RuntimeError("Không đo được duration hợp lệ.")

        stream_br = self._to_float(stream.get("bit_rate"))
        if stream_br and stream_br > 0:
            actual_kbps = stream_br / 1000.0
            method = "ffprobe_stream_bit_rate"
        else:
            size_bytes = self._to_float(fmt.get("size"))
            if not size_bytes or size_bytes <= 0:
                size_bytes = float(Path(path).stat().st_size)
            actual_kbps = size_bytes * 8.0 / duration / 1000.0
            method = "size_duration_estimate"

        size_bytes = self._to_float(fmt.get("size")) or float(Path(path).stat().st_size)
        size_mb = size_bytes / (1024.0 * 1024.0)
        return actual_kbps, size_mb, duration, method

    def measure_vmaf(
        self,
        candidate_path: str | Path,
        reference_path: str | Path,
        reference_resolution: list[int],
        json_path: str | Path,
        vmaf_model: str = "",
        threads: int = 0,
    ) -> float:
        width, height = reference_resolution
        json_path = Path(json_path)
        json_path.parent.mkdir(parents=True, exist_ok=True)
        safe_json = str(json_path).replace("\\", "/").replace(":", "\\:")

        dist_chain = (
            f"[0:v]scale={width}:{height}:force_original_aspect_ratio=decrease,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1,setpts=PTS-STARTPTS[dist]"
        )
        ref_chain = f"[1:v]scale={width}:{height},setsar=1,setpts=PTS-STARTPTS[ref]"
        opts = [f"log_fmt=json", f"log_path={safe_json}"]
        if threads and int(threads) > 0:
            opts.append(f"n_threads={int(threads)}")
        if vmaf_model:
            escaped_model = str(vmaf_model).replace("\\", "/").replace(":", "\\:")
            opts.append(f"model=path='{escaped_model}'")
        lavfi = f"{dist_chain};{ref_chain};[dist][ref]libvmaf=" + ":".join(opts)

        cmd = [
            self.ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
            "-i", str(candidate_path),
            "-i", str(reference_path),
            "-lavfi", lavfi,
            "-f", "null", "-",
        ]
        p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
        if p.returncode != 0:
            raise RuntimeError(p.stderr.strip() or "libvmaf failed")
        if not json_path.exists():
            raise RuntimeError("libvmaf không tạo file JSON kết quả.")

        with json_path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        pooled = data.get("pooled_metrics", {}).get("vmaf", {})
        value = pooled.get("mean")
        if value is None:
            frames = data.get("frames", [])
            vals = []
            for fr in frames:
                metrics = fr.get("metrics", {})
                if "vmaf" in metrics:
                    vals.append(float(metrics["vmaf"]))
            if vals:
                value = sum(vals) / len(vals)
        if value is None or not math.isfinite(float(value)):
            raise RuntimeError("Không đọc được VMAF trung bình hữu hạn.")
        return float(value)

    def measure_one(
        self,
        candidate: dict[str, Any],
        reference_path: str | Path,
        reference_resolution: list[int],
        metrics_dir: str | Path,
        measurement_cfg: dict[str, Any],
    ) -> dict[str, Any]:
        result = dict(candidate)
        if result.get("status") != "encoded":
            return result
        try:
            actual_kbps, size_mb, duration, method = self.actual_bitrate(result["output_path"])
            vmaf_json = Path(metrics_dir) / f"{result['candidate_id']}_vmaf.json"
            self.logger.info("Đo VMAF %s", result["candidate_id"])
            vmaf = self.measure_vmaf(
                result["output_path"],
                reference_path,
                reference_resolution,
                vmaf_json,
                measurement_cfg.get("vmaf_model", ""),
                int(measurement_cfg.get("threads", 0) or 0),
            )
            result.update({
                "actual_bitrate_kbps": actual_kbps,
                "size_mb": size_mb,
                "duration_sec": duration,
                "bitrate_method": method,
                "vmaf": vmaf,
                "vmaf_json": str(vmaf_json),
                "status": "success",
                "error": "",
            })
        except Exception as exc:
            result["status"] = "measurement_error"
            result["error"] = str(exc)
        return result
