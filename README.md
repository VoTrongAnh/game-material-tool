# AI Game Asset Studio — Module AI/Model

Module AI dùng để sinh game asset như background, sprite, pixel art và sprite sheet animation.  
Phần này tập trung vào AI pipeline và xử lý ảnh; phần giao diện web/backend tích hợp sẽ do team web phát triển.

## Công nghệ sử dụng

- Python
- Pollinations.ai image API
- Pillow cho xử lý ảnh
- rembg cho xóa nền sprite

## Cài đặt

```bash
pip install -r requirements.txt
```

## Chạy full pipeline / testing phase

Để kiểm tra toàn bộ yêu cầu bằng một lệnh, dùng:

```bash
python run_full_pipeline.py --provider demo
```

Lệnh này chạy đầy đủ flow:

```txt
01 background
02 base character (tự tạo hoặc normalize từ ảnh user đưa vào)
03 character view right từ base
04 character view left mirror từ base
05 idle animation từ base
06 walk animation từ base
07 attack animation từ base
08 prop/item
09 text-to-pixel-art
10 image-to-pixel-art
11 tile sheet 32 tiles
12 turn animation từ base
13 GIF animation previews
14 manifest.json + character pack metadata
```

Output nằm trong:

```txt
output/full_demo/
```

Nếu muốn chạy bằng AI thật qua Pollinations:

```bash
python run_full_pipeline.py --provider pollinations
```

Có thể chỉnh số frame/kích thước:

```bash
python run_full_pipeline.py --provider pollinations --frames 8 --tile-size 64 --frame-size 64
```

Nếu người dùng đã có nhân vật gốc, truyền ảnh base character vào:

```bash
python run_full_pipeline.py --provider demo --base-char ./hero.png
```

File `manifest.json` sẽ chứa metadata của toàn bộ asset đã tạo, dùng để kiểm tra hoặc bàn giao cho backend/web.

Pipeline hiện tạo character pack trước: base character → right/left views → idle/walk/attack/turn animation. Hướng left được tạo bằng mirror từ base/right để giữ silhouette, scale, outfit và weapon ổn định hơn so với bắt AI vẽ lại một asset mới.

Lưu ý: `--provider demo` chỉ dùng để kiểm tra flow và kích thước output. Chất lượng hình ảnh cuối cùng nên kiểm tra bằng `--provider pollinations` hoặc provider AI production khác.

Sau khi chạy full pipeline, kiểm tra output bằng:

```bash
python check_outputs.py
```

Nếu muốn kiểm tra manifest ở thư mục khác:

```bash
python check_outputs.py --manifest output/full_pollinations/manifest.json
```

Quy trình test khuyến nghị:

```bash
python run_full_pipeline.py --provider demo
python check_outputs.py
```

Nếu hai lệnh trên đều pass, nghĩa là pipeline đã tạo đủ asset, đúng kích thước, có metadata frame/tile và có GIF preview.

## Chạy smoke test offline

Nếu chỉ muốn kiểm tra pipeline có sinh đủ asset hay không, chạy:

```bash
python demo_pipeline.py
```

Script này không gọi API thật. Nó dùng fake provider để tạo nhanh và validate các output sau:

- background
- sprite
- prop/item
- pixel art
- tile sheet thật
- animation sprite sheet
- frame animation đã slice riêng

Output demo nằm trong:

```txt
output/demo/
```

## Cấu hình API key

Pollinations có thể chạy không cần key, nhưng nên cấu hình key nếu dùng nhiều request:

```bash
set POLLINATIONS_API_KEY=your_key_here
```

Trên macOS/Linux:

```bash
export POLLINATIONS_API_KEY=your_key_here
```

## Pipeline xử lý asset

Pipeline hiện tại không chỉ gọi AI rồi lưu ảnh, mà đi qua các bước chuẩn hóa để web/backend dễ tích hợp.

```txt
User input
→ Build prompt theo loại asset
→ Gọi AI provider
→ Kiểm tra ảnh trả về
→ Post-process theo loại asset
→ Lưu file
→ Trả metadata cho backend/web
```

### 1. Background pipeline

```txt
subject + style + time_of_day + theme + view_angle
→ tạo prompt background
→ gọi AI với width/height đúng theo size_key
→ crop/fit về canvas chuẩn, không làm méo ảnh
→ lưu vào output/backgrounds
→ trả metadata
```

Ví dụ:

```bash
python cli.py background "dark dungeon cave" --size background_sd --style pixel_art --theme fantasy --view-angle side_scroll
```

### 2. Sprite pipeline

```txt
subject + style + view_angle
→ tạo prompt sprite
→ gọi AI
→ xóa nền bằng rembg nếu có
→ fallback xóa nền trắng nếu chưa cài rembg
→ fit vào canvas sprite, giữ tỷ lệ
→ nếu view_angle là left: mirror từ canonical right-facing sprite để giữ nhất quán
→ giảm palette/chuẩn hóa pixel nếu là pixel_art để bớt cảm giác soft/cheap
→ lưu PNG có alpha
→ trả metadata
```

Ví dụ:

```bash
python cli.py sprite "knight warrior" --transparent --size sprite_medium --view-angle front
```

### 3. Prop/item pipeline

```txt
subject + item_type + style + view_angle
→ tạo prompt prop/item
→ gọi AI
→ xóa nền
→ fit vào canvas prop, giữ tỷ lệ
→ giảm palette/chuẩn hóa pixel nếu là pixel_art
→ thêm outline nếu là pixel_art/cartoon/chibi
→ lưu PNG có alpha
→ trả metadata
```

Ví dụ:

```bash
python cli.py prop "gold sword" --item-type weapon --size sprite_small --view-angle front
```

### 4. Pixel art pipeline

Có hai hướng xử lý pixel art:

```txt
Text-to-pixel:
subject
→ tạo prompt pixel art
→ gọi AI
→ fit canvas
→ pixelate bằng NEAREST
→ giảm palette màu
→ lưu PNG
```

```txt
Image-to-pixel:
ảnh upload/local image
→ fit canvas
→ pixelate bằng NEAREST
→ giảm palette màu
→ lưu PNG
```

Ví dụ text-to-pixel:

```bash
python cli.py pixel "wooden shield" --size sprite_small --block 4 --colors 16
```

Ví dụ image-to-pixel:

```bash
python cli.py pixel-from-image "./input.png" --size sprite_small --block 4 --colors 16
```

### 5. Tile sheet pipeline

Tile sheet dùng cho map/terrain/object tiles. Đây là loại asset khác với animation sheet.

```txt
subject + tile_names + tile_size + columns
→ tạo prompt riêng cho từng tile
→ gọi AI từng tile
→ chuẩn hóa mỗi tile về cùng kích thước
→ xử lý seam nhẹ ở 4 cạnh và giảm palette cho pixel_art
→ ghép thành grid tile sheet
→ nếu bật slice thì lưu từng tile riêng
→ trả metadata vị trí từng tile
```

Ví dụ:

```bash
python cli.py tile-sheet "forest terrain" --tiles grass dirt water stone --columns 2 --tile-width 64 --tile-height 64
```

Với 4 tile, mỗi tile 64x64 và 2 cột, output sheet sẽ có kích thước:

```txt
128x128
```

### 6. Animation sheet pipeline

Animation sheet dùng cho chuyển động nhân vật/vật thể. Pipeline tạo từng frame riêng rồi ghép ngang, thay vì tạo một ảnh lớn rồi cắt không chính xác.

```txt
subject + action + frame_count + frame_size
→ tạo prompt riêng cho từng frame
→ gọi AI từng frame
→ xóa nền từng frame
→ fit mỗi frame về kích thước chuẩn
→ ghép ngang thành sprite sheet
→ nếu --slice thì lưu thêm từng frame riêng
→ trả metadata frame box
```

Ví dụ:

```bash
python cli.py animation "running robot" --frames 10 --frame-width 64 --frame-height 64 --slice
```

Với 10 frame, mỗi frame 64x64, output sheet sẽ có kích thước:

```txt
640x64
```

## Metadata trả về

Các hàm trong `GameAssetStudio` trả về object `GeneratedAsset`, không chỉ trả đường dẫn file.

Thông tin chính gồm:

```json
{
  "asset_id": "uuid",
  "asset_type": "sprite",
  "prompt": "...",
  "provider": "pollinations",
  "model": "flux",
  "seed": 123,
  "width": 128,
  "height": 128,
  "format": "png",
  "file_path": "output/sprites/example.png",
  "has_alpha": true,
  "frames": [],
  "warnings": []
}
```

Với sprite sheet, `frames` sẽ chứa vị trí từng frame:

```json
{
  "index": 0,
  "x": 0,
  "y": 0,
  "w": 64,
  "h": 64,
  "file_path": "output/tilesheets/example/frame_00.png"
}
```

## Kích thước chuẩn

| Key | Kích thước | Dùng cho |
| --- | --- | --- |
| `background_hd` | 1920x1080 | Background Full HD |
| `background_4k` | 3840x2160 | Background 4K |
| `background_sd` | 1280x720 | Background nhẹ hơn |
| `background_sq` | 1080x1080 | Background vuông |
| `scratch_bg` | 480x360 | Scratch Stage |
| `sprite_small` | 64x64 | Item/icon nhỏ |
| `sprite_medium` | 128x128 | Nhân vật chính |
| `sprite_large` | 256x256 | Boss/NPC lớn |
| `icon` | 32x32 | Icon |

## Cấu trúc output

```txt
output/
├── backgrounds/
├── sprites/
├── props/
├── pixel_art/
├── tile_sheets/
│   └── tilesheet_forest_terrain_8tiles/
│       ├── tile_00_grass.png
│       ├── tile_01_dirt.png
│       └── ...
└── animations/
    └── spritesheet_running_robot_running_10f/
        ├── frame_00.png
        ├── frame_01.png
        └── ...
```

## Ghi chú tích hợp

- Web/backend nên gọi các hàm trong `GameAssetStudio`.
- Không nên phụ thuộc vào tên file tự sinh; nên dùng `asset_id` và metadata trả về.
- Nếu đổi provider AI sau này, chỉ cần thêm provider mới theo interface `AIImageProvider`.
- Tile sheet và animation sheet là hai pipeline khác nhau:
  - `generate_tile_sheet()` tạo grid tile map.
  - `generate_animation_sheet()` tạo sprite animation theo frame.
- Animation sheet tạo theo từng frame nên ổn định kích thước hơn, nhưng sẽ tốn nhiều request AI hơn.
