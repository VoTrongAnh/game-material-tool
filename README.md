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

# Character từ Form Output (JSON do Web team xuất ra)
python cli.py character --form-file form_output.json

# Character bằng flags riêng lẻ (tương đương form-file ở trên)
python cli.py character --base base_tall_slim --hair hair_short_black \
  --outfit outfit_knight_armor --shoes shoes_boots_brown --accessory accessory_sword

# Sheet animation (idle/run/attack) cho cùng 1 nhân vật, giữ nguyên tóc/trang phục qua từng frame
python cli.py character --form-file form_output.json --animate --slice
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

## Character Customizer — Form Output (Web → AI)

Hướng đi mới: Web team dựng Character Customizer (chọn base → tóc → trang phục →
giày → phụ kiện → biểu cảm trên canvas), rồi đóng gói lựa chọn thành **Form
Output** (JSON) bàn giao cho AI. AI **không** nhận request tự do nữa cho luồng
nhân vật — chỉ nhận Form Output, validate từng ID theo catalog, rồi mới build
prompt + gọi model. ID sai catalog sẽ raise lỗi ngay trước khi tốn API call.

**2 luồng generate, chọn theo nhu cầu:**
- `generate_character` / `generate_character_animation` (mặc định, `POST /character`) — text-to-image thuần từ mô tả catalog, không cần thư viện PNG, dùng được ngay.
- `compose_character` / `generate_character_animation_from_layers` (`POST /character/compose`, `POST /character/animate-from-layers`) — **đúng theo quyết định họp mới nhất**: ghép layer PNG thật (không gọi AI cho bước preview), chỉ gọi AI khi sinh animation. Cần thư viện asset đã sinh qua `character-assets` trước — xem mục dưới.

```json
{
  "base_id": "base_tall_slim",
  "hair_id": "hair_short_black",
  "outfit_id": "outfit_knight_armor",
  "shoes_id": "shoes_boots_brown",
  "accessory_id": "accessory_sword",
  "expression_id": "expr_happy",
  "action": "action_idle",
  "facing": "front",
  "size_key": "sprite_medium",
  "style": "pixel_art",
  "seed": 42
}
```

`base_id`/`hair_id`/`outfit_id`/`shoes_id` là bắt buộc; các trường còn lại có
default. Catalog hiện tại (mở rộng bằng cách thêm 1 dòng vào dict tương ứng
trong `asset_generator.py`, không cần sửa prompt logic):

| Catalog | Các ID hiện có |
|---|---|
| `CHARACTER_BASE_CATALOG` | `base_tall_slim`, `base_short_stocky`, `base_average_athletic`, `base_short_slim` |
| `HAIR_CATALOG` | `hair_short_black`, `hair_long_brown`, `hair_ponytail_blonde`, `hair_spiky_red`, `hair_bald`, `hair_buzzcut_grey` |
| `OUTFIT_CATALOG` | `outfit_knight_armor`, `outfit_casual_hoodie`, `outfit_mage_robe`, `outfit_ninja_suit`, `outfit_explorer_vest` |
| `SHOES_CATALOG` | `shoes_boots_brown`, `shoes_sneakers_white`, `shoes_sandals`, `shoes_armored_greaves` |
| `ACCESSORY_CATALOG` | `accessory_none`, `accessory_sword`, `accessory_shield`, `accessory_backpack`, `accessory_hat`, `accessory_staff` |
| `EXPRESSION_CATALOG` | `expr_neutral`, `expr_happy`, `expr_angry`, `expr_surprised` |
| `ACTION_CATALOG` | `action_idle` (4 frame), `action_run` (8 frame), `action_attack` (6 frame) — dùng cho Animation & Sprite Preview |

```bash
# 1 pose tĩnh (đúng combo Web gửi lên)
python cli.py character --form-file form_output.json

# hoặc truyền trực tiếp bằng flags, không cần file JSON
python cli.py character --base base_tall_slim --hair hair_short_black \
  --outfit outfit_knight_armor --shoes shoes_boots_brown --accessory accessory_sword

# sheet animation cho action trong Form Output (idle/run/attack), giữ 1 base seed
# xuyên suốt các frame để nhân vật không đổi hình giữa chừng
python cli.py character --form-file form_output.json --animate --slice --web-json
```

Dùng trong code:

```python
from asset_generator import GameAssetStudio, CharacterFormOutput

studio = GameAssetStudio(api_key=API_KEY, model="flux", output_dir="output")

form = CharacterFormOutput.from_dict(form_output_json)  # raise ValueError nếu thiếu field bắt buộc
form.validate()                                          # raise ValueError nếu ID không có trong catalog

sprite = studio.generate_character(form)                 # 1 pose
sheet = studio.generate_character_animation(form)         # idle/run/attack sheet theo form.action
```

`generate_character`/`generate_character_animation` trả về `GeneratedAsset` như
mọi lệnh khác, dùng được `.to_web_payload()` / `--web-json` để trả thẳng base64
cho frontend.

### API cho Web gọi trực tiếp (`api.py`)

```bash
export POLLINATIONS_API_KEY=sk_...
uvicorn api:app --host 0.0.0.0 --port 8000
```

| Endpoint | Ý nghĩa |
|---|---|
| `GET /health` | Liveness check |
| `GET /catalog` | **Nguồn sự thật duy nhất** cho mọi ID hợp lệ (base/hair/outfit/shoes/accessory/expression/action), size preset, `layer_order`, và naming convention của file asset |
| `POST /character` | Body = Form Output JSON. Sinh 1 pose **bằng text-to-image** (không dùng thư viện layer) |
| `POST /character?animate=true&slice_frames=true` | Sinh animation sheet theo `action`, cũng bằng text-to-image |
| `POST /character/compose` | **Ghép layer thật, không gọi AI** — load PNG từ thư viện asset theo Form Output, trả ảnh ghép ngay lập tức. Đây là endpoint dùng cho preview |
| `POST /character/animate-from-layers` | Ghép layer thật → caption ảnh đã ghép bằng vision model → sinh animation sheet bám theo đúng combo đã chọn (không chỉ dựa vào text catalog) |

Trả `422` nếu ID sai catalog, `409` nếu thiếu file asset trong thư viện (kèm đường dẫn file thiếu), `502` nếu bước gọi model ảnh thất bại.

### Thư viện asset PNG (ghép layer) — naming convention cần Web thống nhất

Mỗi option (base/hair/outfit/shoes/accessory) là **1 file PNG riêng, cùng canvas
size**, đặt tại:

```
<asset_dir>/<category>/<part_id>.png
# ví dụ:
character_assets/base/base_tall_slim.png
character_assets/hair/hair_short_black.png
character_assets/outfit/outfit_knight_armor.png
character_assets/shoes/shoes_boots_brown.png
character_assets/accessory/accessory_sword.png
```

Thứ tự ghép layer (dưới → trên): `base → shoes → outfit → hair → accessory`. Canvas mặc định `sprite_medium`(128×128) 

Sinh thư viện lần đầu (cần API key thật, chạy 1 lần rồi review/chỉnh tay trước
khi giao cho Web — overlay do AI tách riêng qua text-to-image chỉ là bản nháp,
không đảm bảo căn chỉnh pixel-perfect với base):

```bash
python cli.py character-assets --asset-dir character_assets --size sprite_medium
```

Ghép layer thử (không tốn API call, dùng để test nhanh với Web):

```bash
python cli.py character-compose --base base_tall_slim --hair hair_short_black \
  --outfit outfit_knight_armor --shoes shoes_boots_brown --accessory accessory_sword \
  --asset-dir character_assets
```

Sinh animation bám theo layer đã ghép (đúng luồng bước 4 trong kế hoạch: chọn
action → AI generate animation):

```bash
python cli.py character --form-file form.json --animate --from-layers \
  --asset-dir character_assets --slice
```

---

## Khắc phục pixel art mờ / vỡ nét

Vấn đề cũ: `apply_pixel_art_effect` downscale bằng `NEAREST` (chỉ lấy mẫu 1
pixel/khối, dễ dính đúng pixel anti-alias lệch màu) rồi `reduce_palette` lại
quantize **sau khi** đã phóng to, dùng dithering mặc định của Pillow — dithering
rải nhiễu để giả lập thêm màu, chính là nguyên nhân "vỡ hạt". Kết quả: cạnh mờ +
nhiễu hạt cùng lúc.

Pipeline mới (`AssetPostProcessor.pixelate_clean`, dùng cho mọi asset
`style=pixel_art`: sprite, pixel art, tileset, tilesheet, character):

1. Unsharp mask lên ảnh gốc AI trả về (thường hơi mờ) để giữ lại cạnh thật trước
   khi downscale.
2. Downscale về lưới pixel bằng `BOX` (lấy trung bình cả khối) thay vì `NEAREST`
   (lấy mẫu 1 điểm) — đại diện đúng màu chủ đạo của từng khối.
3. Quantize palette **trên ảnh nhỏ**, tắt dithering (`dither=Image.Dither.NONE`,
   `method=MEDIANCUT`) — đây là điểm khác biệt chính so với pipeline cũ.
4. Nhị phân hoá alpha (`clean_alpha_edges`, ngưỡng mặc định 128) để viền không
   bị quầng xám do bán trong suốt.
5. Phóng to lại bằng `NEAREST` — cạnh pixel cứng, sắc nét.

Có thể chỉnh `block_size`/`colors`/`alpha_threshold` khi gọi trực tiếp
`AssetPostProcessor.pixelate_clean(...)` nếu asset nào cần palette rộng/hẹp
khác mặc định (32 màu).

---

## Cấu trúc output
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