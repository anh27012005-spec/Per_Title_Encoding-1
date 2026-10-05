from __future__ import annotations

import csv
import json
import math
import subprocess
from pathlib import Path
from typing import Any

import cv2
import numpy as np


class VideoProcessingError(RuntimeError):
    pass


class VideoProcessor:
    def __init__(self, ffmpeg: str, ffprobe: str, logger):
        self.ffmpeg = ffmpeg
        self.ffprobe = ffprobe
        self.logger = logger

    def probe(self, video_path: str | Path) -> dict[str, Any]:
        cmd = [
            self.ffprobe,
            "-v", "error",
            "-show_streams",
            "-show_format",
            "-of", "json",
            str(video_path),
        ]
        p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
        if p.returncode != 0:
            raise VideoProcessingError(f"FFprobe lỗi: {p.stderr.strip()}")
        data = json.loads(p.stdout)
        video_streams = [s for s in data.get("streams", []) if s.get("codec_type") == "video"]
        if not video_streams:
            raise VideoProcessingError("Video không có luồng hình.")
        stream = video_streams[0]
        duration = stream.get("duration") or data.get("format", {}).get("duration")
        try:
            duration_f = float(duration)
        except (TypeError, ValueError):
            duration_f = 0.0
        if duration_f <= 0:
            raise VideoProcessingError("Không đọc được thời lượng video.")
        return {
            "width": int(stream.get("width", 0)),
            "height": int(stream.get("height", 0)),
            "duration_sec": duration_f,
            "codec_name": stream.get("codec_name"),
            "avg_frame_rate": stream.get("avg_frame_rate"),
            "pix_fmt": stream.get("pix_fmt"),
            "raw": data,
        }

    def create_reference(
        self,
        input_video: str | Path,
        out_path: str | Path,
        duration_sec: float,
        fps: float,
        resolution: list[int],
        codec: str = "ffv1",
    ) -> dict[str, Any]:
        meta = self.probe(input_video)
        if meta["duration_sec"] + 1e-6 < duration_sec:
            raise VideoProcessingError(
                f"Video nguồn chỉ dài {meta['duration_sec']:.3f}s, ngắn hơn thời lượng yêu cầu {duration_sec}s."
            )

        w, h = resolution
        vf = (
            f"scale={w}:{h}:force_original_aspect_ratio=decrease,"
            f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,"
            f"fps={fps},setsar=1"
        )
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        cmd = [
            self.ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
            "-i", str(input_video),
            "-t", str(duration_sec),
            "-an",
            "-vf", vf,
            "-c:v", codec,
            "-pix_fmt", "yuv420p",
            str(out_path),
        ]
        self.logger.info("Tạo video tham chiếu: %s", out_path)
        p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
        if p.returncode != 0:
            raise VideoProcessingError(f"Không tạo được video tham chiếu: {p.stderr.strip()}")
        result = self.probe(out_path)
        result["path"] = str(out_path)
        result["source_metadata"] = meta
        return result

    def compute_si_ti(self, reference_path: str | Path, csv_path: str | Path) -> dict[str, Any]:
        cap = cv2.VideoCapture(str(reference_path))
        if not cap.isOpened():
            raise VideoProcessingError(f"OpenCV không mở được reference: {reference_path}")

        fps = cap.get(cv2.CAP_PROP_FPS)
        if not fps or not math.isfinite(fps):
            fps = 0.0

        rows: list[dict[str, Any]] = []
        prev_gray = None
        frame_idx = 0
        sis: list[float] = []
        tis: list[float] = []

        while True:
            ok, frame = cap.read()
            if not ok:
                break
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY).astype(np.float32)
            gx = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
            gy = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
            sobel_mag = np.sqrt(gx * gx + gy * gy)
            si = float(np.std(sobel_mag, ddof=1)) if sobel_mag.size > 1 else 0.0
            sis.append(si)

            ti = None
            if prev_gray is not None:
                diff = gray - prev_gray
                ti = float(np.std(diff, ddof=1)) if diff.size > 1 else 0.0
                tis.append(ti)

            rows.append({
                "frame": frame_idx,
                "time_sec": (frame_idx / fps) if fps > 0 else None,
                "si": si,
                "ti": ti,
            })
            prev_gray = gray
            frame_idx += 1

        cap.release()
        if not rows:
            raise VideoProcessingError("Không đọc được khung hình từ video tham chiếu.")

        csv_path = Path(csv_path)
        csv_path.parent.mkdir(parents=True, exist_ok=True)
        with csv_path.open("w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=["frame", "time_sec", "si", "ti"])
            writer.writeheader()
            writer.writerows(rows)

        return {
            "frames": len(rows),
            "si_mean": float(np.mean(sis)) if sis else None,
            "si_max": float(np.max(sis)) if sis else None,
            "ti_mean": float(np.mean(tis)) if tis else None,
            "ti_max": float(np.max(tis)) if tis else None,
            "series_csv": str(csv_path),
        }
