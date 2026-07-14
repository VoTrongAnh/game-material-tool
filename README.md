# 🎮 AI Game Asset Studio — Module AI/Model

**Platform:** [Pollinations.ai](https://pollinations.ai)

---

## Cài đặt

```bash
pip install -r requirements.txt
```

## Cấu hình API Key (tuỳ chọn)

Free tier không cần key nhưng có watermark và rate limit (1 req/15s).
Đăng ký tại [enter.pollinations.ai](https://enter.pollinations.ai) để lấy key:

```bash
export POLLINATIONS_API_KEY=sk_your_key_here
```

---

## Dùng CLI

```bash
# Background
python cli.py background "dark dungeon cave" --size background_sd --style pixel_art

# Sprite
python cli.py sprite "knight warrior" --transparent --size sprite_medium

# Pixel art
python cli.py pixel "wooden shield" --block 4 --colors 16

# Tilesheet (animation frames) + cắt frame lẻ
python cli.py tilesheet "running robot" --frames 10 --slice

# Tileset (lưới các tile rời cho GameMaker/Tiled), dùng bộ preset dựng sẵn
python cli.py tileset --preset platformer_basic --cell-size tile_32 --columns 8 --slice

# Tileset tự chọn tile
python cli.py tileset "grass ground tile" "water tile" "lava tile" --cell-size tile_16 --columns 4
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

---

## Tileset (mới)

Sinh ra một **sheet dạng lưới** gồm nhiều tile riêng biệt (cỏ, nước, dung nham, cây, rương, đuốc...), mỗi tile một ô kích thước cố định, nền trong suốt — import thẳng vào GameMaker's "Create Tile Set" hoặc Tiled.

```bash
python cli.py tileset --preset platformer_basic --cell-size tile_32 --columns 8 --spacing 2 --slice
```

Các tuỳ chọn chính:

| Tham số | Ý nghĩa |
|---|---|
| `tiles` (positional) | Danh sách mô tả từng tile, mỗi mô tả = 1 ô lưới |
| `--preset` | Dùng bộ tile dựng sẵn thay vì tự liệt kê: `platformer_basic`, `dungeon`, `cave` |
| `--cell-size` | Kích thước mỗi ô: `tile_16` / `tile_24` / `tile_32` / `tile_48` / `tile_64` |
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