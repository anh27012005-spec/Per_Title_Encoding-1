from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any


class EncodingModule:
    def __init__(self, ffmpeg: str, logger):
        self.ffmpeg = ffmpeg
        self.logger = logger

    @staticmethod
    def build_candidates(resolutions: list[list[int]], bitrates_kbps: list[int | float]) -> list[dict[str, Any]]:
        candidates = []
        index = 1
        for width, height in resolutions:
            for br in bitrates_kbps:
                candidates.append({
                    "candidate_id": f"C{index:03d}_{width}x{height}_{int(br)}k",
                    "width": int(width),
                    "height": int(height),
                    "resolution": f"{width}x{height}",
                    "target_bitrate_kbps": float(br),
                    "status": "pending",
                    "error": "",
                })
                index += 1
        return candidates

    def encode_one(
        self,
        reference_path: str | Path,
        candidate: dict[str, Any],
        output_dir: str | Path,
        encoding_cfg: dict[str, Any],
    ) -> dict[str, Any]:
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        out = output_dir / f"{candidate['candidate_id']}.mp4"
        width, height = candidate["width"], candidate["height"]
        br = candidate["target_bitrate_kbps"]

        vf = (
            f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1"
        )
        cmd = [
            self.ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
            "-i", str(reference_path),
            "-an",
            "-vf", vf,
            "-c:v", str(encoding_cfg["codec"]),
            "-preset", str(encoding_cfg["preset"]),
            "-pix_fmt", str(encoding_cfg["pixel_format"]),
            "-g", str(int(encoding_cfg["gop"])),
            "-keyint_min", str(int(encoding_cfg["gop"])),
            "-sc_threshold", "0",
            "-b:v", f"{int(br)}k",
        ]
        if encoding_cfg.get("rate_control") == "capped_vbr":
            maxrate = max(1, int(br * float(encoding_cfg.get("maxrate_ratio", 1.2))))
            bufsize = max(1, int(br * float(encoding_cfg.get("bufsize_ratio", 2.0))))
            cmd += ["-maxrate", f"{maxrate}k", "-bufsize", f"{bufsize}k"]
        cmd += [str(x) for x in encoding_cfg.get("extra_args", [])]
        cmd.append(str(out))

        self.logger.info("Encode %s", candidate["candidate_id"])
        p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
        result = dict(candidate)
        result["output_path"] = str(out)
        if p.returncode == 0 and out.exists() and out.stat().st_size > 0:
            result["status"] = "encoded"
        else:
            result["status"] = "encode_error"
            result["error"] = (p.stderr or "FFmpeg encode failed").strip()
        return result
