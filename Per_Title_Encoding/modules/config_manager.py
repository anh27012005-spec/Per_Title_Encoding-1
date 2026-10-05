from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


class ConfigError(RuntimeError):
    pass


@dataclass
class ToolInfo:
    ffmpeg: str
    ffprobe: str
    ffmpeg_version: str
    ffprobe_version: str
    libvmaf_available: bool


class ConfigurationManager:
    def __init__(self, config_path: str | Path):
        self.config_path = Path(config_path).resolve()
        self.project_root = self.config_path.parent
        self.config: dict[str, Any] = {}
        self.tools: ToolInfo | None = None

    @staticmethod
    def _run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )

    def load_and_validate(self) -> tuple[dict[str, Any], ToolInfo]:
        if not self.config_path.exists():
            raise ConfigError(f"Không tìm thấy config: {self.config_path}")

        with self.config_path.open("r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
        if not isinstance(cfg, dict):
            raise ConfigError("config.yaml phải là một mapping YAML.")

        required = [
            "input_video",
            "output_root",
            "duration_sec",
            "fps",
            "reference_resolution",
            "resolutions",
            "bitrates_kbps",
            "encoding",
            "measurement",
            "selection",
        ]
        missing = [k for k in required if k not in cfg]
        if missing:
            raise ConfigError(f"Thiếu trường cấu hình: {', '.join(missing)}")

        input_video = Path(cfg["input_video"])
        if not input_video.is_absolute():
            input_video = (self.project_root / input_video).resolve()
        output_root = Path(cfg["output_root"])
        if not output_root.is_absolute():
            output_root = (self.project_root / output_root).resolve()
        cfg["input_video"] = str(input_video)
        cfg["output_root"] = str(output_root)

        if not input_video.exists() or not input_video.is_file():
            raise ConfigError(f"Không tìm thấy video đầu vào: {input_video}")

        self._positive(cfg["duration_sec"], "duration_sec")
        self._positive(cfg["fps"], "fps")
        self._validate_resolution(cfg["reference_resolution"], "reference_resolution")

        if not isinstance(cfg["resolutions"], list) or not cfg["resolutions"]:
            raise ConfigError("resolutions phải là danh sách không rỗng.")
        seen_res = set()
        for i, res in enumerate(cfg["resolutions"]):
            self._validate_resolution(res, f"resolutions[{i}]")
            key = tuple(res)
            if key in seen_res:
                raise ConfigError(f"Độ phân giải bị trùng: {res}")
            seen_res.add(key)

        if not isinstance(cfg["bitrates_kbps"], list) or not cfg["bitrates_kbps"]:
            raise ConfigError("bitrates_kbps phải là danh sách không rỗng.")
        seen_br = set()
        for br in cfg["bitrates_kbps"]:
            self._positive(br, "bitrate")
            if br in seen_br:
                raise ConfigError(f"Bitrate bị trùng: {br}")
            seen_br.add(br)

        enc = cfg["encoding"]
        if not isinstance(enc, dict):
            raise ConfigError("encoding phải là mapping.")
        for key in ["codec", "preset", "pixel_format", "gop", "rate_control"]:
            if key not in enc:
                raise ConfigError(f"Thiếu encoding.{key}")
        self._positive(enc["gop"], "encoding.gop")
        if enc["rate_control"] not in {"abr", "capped_vbr"}:
            raise ConfigError("encoding.rate_control chỉ hỗ trợ 'abr' hoặc 'capped_vbr'.")

        sel = cfg["selection"]
        for key in ["target_rungs", "min_bitrate_ratio", "min_vmaf_gain"]:
            if key not in sel:
                raise ConfigError(f"Thiếu selection.{key}")
            self._positive(sel[key], f"selection.{key}")

        ffmpeg = shutil.which("ffmpeg")
        ffprobe = shutil.which("ffprobe")
        if not ffmpeg:
            raise ConfigError("Không tìm thấy FFmpeg trong PATH.")
        if not ffprobe:
            raise ConfigError("Không tìm thấy FFprobe trong PATH.")

        ffmpeg_ver = self._run([ffmpeg, "-version"]).stdout.splitlines()
        ffprobe_ver = self._run([ffprobe, "-version"]).stdout.splitlines()
        filter_proc = self._run([ffmpeg, "-hide_banner", "-filters"])
        filter_text = filter_proc.stdout + "\n" + filter_proc.stderr
        libvmaf = "libvmaf" in filter_text
        if not libvmaf:
            raise ConfigError(
                "FFmpeg hiện tại không có filter libvmaf. Hãy cài bản FFmpeg có libvmaf trước khi chạy."
            )

        tools = ToolInfo(
            ffmpeg=ffmpeg,
            ffprobe=ffprobe,
            ffmpeg_version=ffmpeg_ver[0] if ffmpeg_ver else "unknown",
            ffprobe_version=ffprobe_ver[0] if ffprobe_ver else "unknown",
            libvmaf_available=libvmaf,
        )
        self.config = cfg
        self.tools = tools
        return cfg, tools

    @staticmethod
    def _positive(value: Any, name: str) -> None:
        if not isinstance(value, (int, float)) or value <= 0:
            raise ConfigError(f"{name} phải > 0, nhận được: {value!r}")

    @staticmethod
    def _validate_resolution(value: Any, name: str) -> None:
        if not (
            isinstance(value, list)
            and len(value) == 2
            and all(isinstance(v, int) and v > 0 for v in value)
        ):
            raise ConfigError(f"{name} phải có dạng [width, height] với số nguyên dương.")
        if value[0] % 2 or value[1] % 2:
            raise ConfigError(f"{name} phải có width/height chẵn để phù hợp H.264: {value}")
