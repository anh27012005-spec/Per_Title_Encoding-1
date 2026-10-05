# Per-Title Encoding Demo

Project này triển khai đúng luồng BA:

`config -> reference/SI-TI -> candidates -> H.264 encode -> actual bitrate/VMAF -> Pareto -> upper hull -> ladder -> CSV/JSON/PNG`

## 1. Cấu trúc

```text
Per_Title_Encoding/
├── main.py
├── config.yaml
├── requirements.txt
├── modules/
│   ├── config_manager.py
│   ├── video_processor.py
│   ├── encoder.py
│   ├── measurement.py
│   ├── analyzer.py
│   ├── ladder_selector.py
│   └── visualizer.py
├── data/input/
├── output/
└── tests/
```

## 2. Yêu cầu

- Python 3.10+
- FFmpeg + FFprobe trong PATH
- FFmpeg phải có `libvmaf`

Kiểm tra trên Windows:

```powershell
ffmpeg -version
ffprobe -version
ffmpeg -filters | findstr vmaf
```

Cài Python packages:

```powershell
python -m pip install -r requirements.txt
```

## 3. Đặt video

Chép video 10-30 giây vào:

```text
data/input/video_01.mp4
```

Mặc định config yêu cầu tối thiểu 20 giây. Nếu video ngắn hơn, sửa `duration_sec` trong `config.yaml`.

## 4. Chạy

```powershell
python main.py --config config.yaml
```

Mặc định hệ thống sinh 12 candidate = 3 resolution x 4 bitrate:

- 640x360
- 1280x720
- 1920x1080

với bitrate:

- 400 kbps
- 800 kbps
- 1500 kbps
- 2800 kbps

## 5. Kết quả

Mỗi lần chạy tạo một thư mục riêng trong `output/`:

```text
output/video_01_YYYYMMDD_HHMMSS/
├── candidates.csv
├── experiment.json
├── config_used.yaml
├── run.log
├── reference/reference.mkv
├── encoded/*.mp4
├── metrics/
│   ├── si_ti.csv
│   └── *_vmaf.json
├── analysis/
│   ├── valid_candidates.csv
│   ├── pareto.csv
│   └── convex_hull.csv
├── ladder/
│   ├── ladder.csv
│   └── ladder.json
└── figures/
    ├── rate_quality.png
    └── si_ti.png
```

## 6. Chính sách chọn ladder đang dùng

Tài liệu BA ghi rằng chính sách xếp hạng cụ thể cần nhóm chốt. Bản code này dùng một chính sách demo xác định, không tạo dữ liệu giả:

1. Chỉ dùng candidate đo thành công.
2. Pareto dùng `actual_bitrate_kbps` và `VMAF`.
3. Upper hull được tính trên `x = log2(actual bitrate)`, `y = VMAF`.
4. Tìm tổ hợp tối đa `target_rungs`.
5. Mỗi mức liên tiếp phải thỏa `min_bitrate_ratio` và `min_vmaf_gain`.
6. Khi có nhiều tổ hợp cùng số mức: ưu tiên nhiều điểm hull hơn, sau đó ưu tiên phủ dải bitrate rộng hơn.
7. Nếu không đủ candidate, xuất ladder ngắn hơn và ghi rõ lý do.

## 7. Kiểm thử thuật toán

```powershell
python -m unittest discover -s tests -v
```

Test có trường hợp AC04: `(800 kbps, 78 VMAF)` chi phối `(1000 kbps, 76 VMAF)`.
