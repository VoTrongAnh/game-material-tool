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
subject + style + time_of_day
→ tạo prompt background
→ gọi AI với width/height đúng theo size_key
→ crop/fit về canvas chuẩn, không làm méo ảnh
→ lưu vào output/backgrounds
→ trả metadata
```

Ví dụ:

```bash
python cli.py background "dark dungeon cave" --size background_sd --style pixel_art
```

### 2. Sprite pipeline

```txt
subject + style + facing
→ tạo prompt sprite
→ gọi AI
→ xóa nền bằng rembg nếu có
→ fallback xóa nền trắng nếu chưa cài rembg
→ fit vào canvas sprite, giữ tỷ lệ
→ lưu PNG có alpha
→ trả metadata
```

Ví dụ:

```bash
python cli.py sprite "knight warrior" --transparent --size sprite_medium
```

### 3. Pixel art pipeline

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

### 4. Sprite sheet pipeline

Sprite sheet đã được đổi sang hướng tạo từng frame riêng rồi ghép lại, thay vì tạo một ảnh lớn rồi cắt không chính xác.

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
python cli.py tilesheet "running robot" --frames 10 --frame-width 64 --frame-height 64 --slice
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
| `sprite_small` | 64x64 | Item/icon nhỏ |
| `sprite_medium` | 128x128 | Nhân vật chính |
| `sprite_large` | 256x256 | Boss/NPC lớn |
| `icon` | 32x32 | Icon |

## Cấu trúc output

```txt
output/
├── backgrounds/
├── sprites/
├── pixel_art/
└── tilesheets/
    └── spritesheet_running_robot_running_10f/
        ├── frame_00.png
        ├── frame_01.png
        └── ...
```

## Ghi chú tích hợp

- Web/backend nên gọi các hàm trong `GameAssetStudio`.
- Không nên phụ thuộc vào tên file tự sinh; nên dùng `asset_id` và metadata trả về.
- Nếu đổi provider AI sau này, chỉ cần thêm provider mới theo interface `AIImageProvider`.
- Sprite sheet tạo theo từng frame nên ổn định kích thước hơn, nhưng sẽ tốn nhiều request AI hơn.
