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

# Tilesheet + cắt frame lẻ
python cli.py tilesheet "running robot" --frames 10 --slice
```

---

## Kích thước chuẩn

| Key | Kích thước | Dùng cho |
|-----|-----------|----------|
| `background_hd` | 1920×1080 | GameMaker full HD |
| `background_sd` | 1280×720 | Scratch Stage |
| `background_sq` | 1080×1080 | Scratch vuông |
| `sprite_small`  | 64×64 | Icon, item nhỏ |
| `sprite_medium` | 128×128 | Nhân vật chính |
| `sprite_large`  | 256×256 | Boss, NPC lớn |
| `tilesheet`     | 512×512 | Base tilesheet |

---

## Cấu trúc output

```
output/
├── backgrounds/
├── sprites/
├── pixel_art/
└── tilesheets/
    └── tilesheet_walking_cat_10f/   ← frames lẻ (nếu --slice)
        ├── frame_00.png
        ├── frame_01.png
        └── ...
```
