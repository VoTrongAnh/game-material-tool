# 🎮 AI Game Asset Studio — Module AI/Model

**Platform:** [Pollinations.ai](https://pollinations.ai)

---

## Cài đặt

```bash
pip install -r requirements.txt
```

## Cấu hình API Key

```
POLLINATIONS_API_KEY=sk_your_key_here
```

Lấy key tại [enter.pollinations.ai](https://enter.pollinations.ai).
---

## Dùng CLI

```bash
# Background
python cli.py background "dark dungeon cave" --size background_sd --style pixel_art

# Sprite
python cli.py sprite "knight warrior" --transparent --size sprite_medium

# Pixel art
python cli.py pixel "wooden shield" --block 4 --colors 16

# Convert ảnh có sẵn thành pixel art (xử lý local, không gọi AI sinh lại)
python cli.py pixel-from-image "./input.png" --size sprite_small --block 4

# Ảnh HD nhân vật -> tự mô tả -> sinh sprite pixel art mới (dùng AI, cần API key)
python cli.py sprite-from-image "./luffy_hd.png" --size sprite_medium --extra "holding straw hat"

# Tilesheet (animation frames) + cắt frame lẻ
python cli.py tilesheet "running robot" --frames 10 --slice

# Tileset (lưới các tile rời cho GameMaker/Tiled), dùng bộ preset dựng sẵn
python cli.py tileset --preset platformer_basic --cell-size tile_32 --columns 8 --slice

# Tileset tự chọn tile
python cli.py tileset "grass ground tile" "water tile" "lava tile" --cell-size tile_16 --columns 4
```
### `GeneratedAsset.to_web_payload()`

Chuẩn hóa output của mọi asset về cùng một JSON format để frontend sử dụng trực tiếp:

```json
{
  "image": "data:image/png;base64,...",
  "metadata": {
    "total_frames": 8,
    "layout_format": "horizontal",
    "frame_width": 64,
    "frame_height": 64,
    "columns": 8,
    "rows": 1
  }
}
```

Hỗ trợ:
- `sprite-from-image` → `layout_format: "single"`
- `tilesheet` → `layout_format: "horizontal"`
- `tileset` → `layout_format: "grid"`

### `--web-json`

Thêm cho các lệnh:

```bash
python cli.py sprite-from-image "./luffy_hd.png" --web-json
python cli.py tilesheet "running warrior" --frames 8 --web-json
python cli.py tileset --preset platformer_basic --web-json
```

Xuất trực tiếp JSON (Base64 + metadata), giúp frontend không cần đọc file PNG từ đĩa.
---

## Ảnh HD → Sprite pixel art (mới)

`sprite-from-image` giải quyết bài toán: có 1 tấm ảnh HD (ví dụ nhân vật Luffy) và muốn ra ngay 1 sprite pixel art của nhân vật đó để bỏ vào GameMaker.

Pipeline gồm 3 bước, chạy tự động:

1. **Caption** — gửi ảnh cho model vision (`openai`, GPT-5 Nano trên Pollinations) để mô tả nhân vật: tên (nếu nhận diện được), trang phục, màu sắc, phụ kiện, đặc điểm nổi bật.
2. **Build prompt** — ghép mô tả đó (+ `--extra` nếu có) vào prompt sprite chuẩn của studio (front-facing, isolated, transparent background, pixel art 8-bit...).
3. **Generate** — gọi lại model ảnh (`flux`) để **sinh sprite hoàn toàn mới**, không phải downsize ảnh gốc.

```bash
python cli.py sprite-from-image "./luffy_hd.png" \
  --size sprite_medium \
  --facing front \
  --extra "holding straw hat"
```

| Tham số | Ý nghĩa |
|---|---|
| `image_path` (positional) | Ảnh HD đầu vào (PNG/JPG/WebP) |
| `--size` | Preset (`sprite_small` / `sprite_medium` / `sprite_large`...) hoặc `WIDTHxHEIGHT` tuỳ ý |
| `--style` | `pixel_art` (mặc định) / `cartoon` / `realistic` / `chibi` |
| `--facing` | `front` / `side` / `back` / `three-quarter` |
| `--no-transparent` | Giữ nền thay vì xoá nền (mặc định có xoá nền) |
| `--extra` | Thêm chi tiết vào mô tả tự sinh, ví dụ phụ kiện/pose muốn ép thêm |
| `--seed` | Seed cố định để tái tạo lại kết quả |

**Khác với `pixel-from-image`:** lệnh cũ chỉ xử lý pixel cục bộ trên chính ảnh gốc (downsample + giảm palette), phụ thuộc hoàn toàn vào pose/nền/chất lượng ảnh gốc. `sprite-from-image` sinh **ảnh mới hoàn toàn** qua model, nên sprite ra sạch pose, nền trong suốt, đúng chuẩn game-ready bất kể ảnh gốc trông thế nào — đổi lại cần API key (xem mục Cấu hình API Key ở trên).

JSON trả về có thêm field ghi lại cả caption gốc lẫn prompt cuối để debug:

```json
{
  "prompt": "[reference image: luffy_hd.png] auto-caption: 'Monkey D. Luffy, straw hat pirate...' -> sprite prompt: ...",
  "warnings": []
}
```

---

## Kích thước chuẩn

| Key | Kích thước | Dùng cho |
|-----|-----------|----------|
| `background_hd` | 1920×1080 | GameMaker full HD |
| `background_4k` | 3840×2160 | Background độ phân giải cao |
| `background_sd` | 1280×720 | Scratch Stage |
| `background_sq` | 1080×1080 | Scratch vuông |
| `icon`          | 32×32 | Icon UI |
| `sprite_small`  | 64×64 | Icon, item nhỏ |
| `sprite_medium` | 128×128 | Nhân vật chính |
| `sprite_large`  | 256×256 | Boss, NPC lớn |
| `tile_16`       | 16×16 | Tile nhỏ, retro NES |
| `tile_24`       | 24×24 | Tile trung |
| `tile_32`       | 32×32 | Tile chuẩn phổ biến (GameMaker) |
| `tile_48`       | 48×48 | Tile chi tiết vừa |
| `tile_64`       | 64×64 | Tile chi tiết cao |

> Kích thước từng frame trong `tilesheet` do bạn tự đặt qua `--frame-width` / `--frame-height` (mặc định 64×64), không phải một size cố định.
> Mọi lệnh nhận `--size`/`--cell-size` đều chấp nhận preset key ở trên **hoặc** chuỗi tuỳ ý dạng `WIDTHxHEIGHT` (ví dụ `800x600`).

---

## Tileset

Sinh ra một **sheet dạng lưới** gồm nhiều tile riêng biệt (cỏ, nước, dung nham, cây, rương, đuốc...), mỗi tile một ô kích thước cố định, nền trong suốt — import thẳng vào GameMaker's "Create Tile Set" hoặc Tiled.

```bash
python cli.py tileset --preset platformer_basic --cell-size tile_32 --columns 8 --spacing 2 --slice
```

Các tuỳ chọn chính:

| Tham số | Ý nghĩa |
|---|---|
| `tiles` (positional) | Danh sách mô tả từng tile, mỗi mô tả = 1 ô lưới |
| `--preset` | Dùng bộ tile dựng sẵn thay vì tự liệt kê: `platformer_basic`, `dungeon`, `cave` |
| `--cell-size` | Kích thước mỗi ô: `tile_16` / `tile_24` / `tile_32` / `tile_48` / `tile_64` hoặc `WIDTHxHEIGHT` |
| `--columns` | Số tile mỗi hàng (số hàng tự tính theo tổng số tile) |
| `--margin` | Viền quanh toàn bộ sheet (px) |
| `--spacing` | Khoảng cách giữa các tile (px), tránh GameMaker đọc lem tile khi lấy mẫu |
| `--slice` | Lưu thêm từng tile thành file PNG riêng |
| `--no-transparent` | Giữ nguyên nền thay vì xoá nền |

Mỗi lần chạy sinh ra thêm file `<tên>.json` bên cạnh ảnh PNG, mô tả `tile_width`, `tile_height`, `columns`, `rows`, `margin`, `spacing` và tên/toạ độ (`x`, `y`, `index`) của từng tile — dùng để nhập tự động vào GameMaker/Tiled thay vì canh tay từng ô.

---

## Cấu trúc output

```
output/
├── backgrounds/
├── sprites/
│   └── sprite_from_luffy_hd_sprite_medium.png   ← từ sprite-from-image
├── pixel_art/
├── tilesheets/
│   └── tilesheet_walking_cat_10f/   ← frames lẻ (nếu --slice)
│       ├── frame_00.png
│       ├── frame_01.png
│       └── ...
└── tilesets/
    ├── tileset_platformer_basic_tile_32.png    ← sheet dạng lưới
    ├── tileset_platformer_basic_tile_32.json   ← layout: tile_width, columns, rows, tên/toạ độ từng tile
    └── tileset_platformer_basic_tile_32/       ← tile lẻ (nếu --slice)
        ├── 000_grass_ground_top_edge_tile.png
        ├── 001_grass_ground_top-left_corner_tile.png
        └── ...
```