"""
AI Game Asset Studio — Module AI/Model
Tác giả: Trọng Anh
Mô tả: Sinh game asset (background, sprite, tilesheet, pixel art) từ Pollinations.ai
"""

import os
import re
import time
import requests
from pathlib import Path
from urllib.parse import quote
from PIL import Image, ImageFilter
import io

# ─────────────────────────────────────────────
# CẤU HÌNH CHUNG
# ─────────────────────────────────────────────

BASE_URL = "https://image.pollinations.ai/prompt"
API_KEY  = os.getenv("POLLINATIONS_API_KEY", "")   # Đặt key vào env hoặc để trống (free tier)
OUTPUT_DIR = Path("output")

# Kích thước chuẩn cho từng loại asset
ASSET_SIZES = {
    "background_hd":   (1920, 1080),
    "background_4k":   (3840, 2160),
    "background_sd":   (1280, 720),
    "background_sq":   (1080, 1080),   # dùng cho Scratch Stage
    "sprite_small":    (64,   64),
    "sprite_medium":   (128,  128),
    "sprite_large":    (256,  256),
    "tilesheet":       (512,  512),    # 10-frame: mỗi frame ~51x512
    "icon":            (32,   32),
}

# ─────────────────────────────────────────────
# PROMPT OPTIMIZER
# ─────────────────────────────────────────────

class PromptOptimizer:
    """
    Tối ưu prompt để Pollinations trả về asset đúng phong cách và định dạng.
    """

    STYLE_TAGS = {
        "pixel_art":    "pixel art, 8-bit, retro game style, crisp pixels, no anti-aliasing",
        "cartoon":      "2D cartoon, flat color, thick outlines, bright palette, game asset",
        "realistic":    "realistic, detailed textures, high quality, game environment",
        "chibi":        "chibi style, cute, rounded shapes, vibrant colors, game sprite",
    }

    NEGATIVE_BASE = (
        "blurry, watermark, text, logo, signature, extra limbs, "
        "bad anatomy, low quality, cropped, deformed"
    )

    @staticmethod
    def build_background_prompt(subject: str, style: str = "pixel_art",
                                 time_of_day: str = "day") -> str:
        style_tag = PromptOptimizer.STYLE_TAGS.get(style, style)
        return (
            f"{subject}, {time_of_day} lighting, seamless background, "
            f"game background, side-scrolling, no characters, {style_tag}, "
            f"high detail, wide shot"
        )

    @staticmethod
    def build_sprite_prompt(subject: str, style: str = "pixel_art",
                             facing: str = "front") -> str:
        style_tag = PromptOptimizer.STYLE_TAGS.get(style, style)
        return (
            f"{subject}, {facing} facing, full body, isolated on white background, "
            f"transparent background, game sprite, {style_tag}, clean edges"
        )

    @staticmethod
    def build_tilesheet_prompt(subject: str, style: str = "pixel_art",
                                frames: int = 10) -> str:
        style_tag = PromptOptimizer.STYLE_TAGS.get(style, style)
        return (
            f"sprite sheet of {subject}, {frames} animation frames in a row, "
            f"horizontal layout, evenly spaced, same size each frame, "
            f"white background, game animation, {style_tag}"
        )

    @staticmethod
    def build_pixel_art_prompt(subject: str) -> str:
        return (
            f"{subject}, pure pixel art, 8-bit retro, low resolution look, "
            f"limited color palette, hard pixel edges, no gradients, "
            f"classic NES/SNES style"
        )

    @staticmethod
    def get_negative_prompt(asset_type: str = "general") -> str:
        extras = {
            "background": ", characters, people, HUD, UI elements",
            "sprite":     ", background scenery, multiple poses",
            "tilesheet":  ", merged frames, uneven spacing",
        }
        return PromptOptimizer.NEGATIVE_BASE + extras.get(asset_type, "")


# ─────────────────────────────────────────────
# IMAGE GENERATOR (gọi Pollinations.ai)
# ─────────────────────────────────────────────

class ImageGenerator:
    """
    Wrapper gọi Pollinations.ai Image API và trả về PIL.Image.
    """

    def __init__(self, api_key: str = API_KEY, model: str = "flux"):
        self.api_key = api_key
        self.model   = model
        # self.headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self.headers = {}

    # def generate(self, prompt: str, width: int = 512, height: int = 512,
    #              seed: int = -1, retries: int = 3) -> Image.Image:
    #     """
    #     Gọi API sinh ảnh, trả về PIL Image.
    #     seed=-1 → random mỗi lần; seed cố định → kết quả reproducible.
    #     """
    #     encoded = quote(prompt)
    #     url = f"{BASE_URL}/{encoded}"
    #     params = {
    #         "model":  self.model,
    #         "width":  width,
    #         "height": height,
    #         "seed":   seed if seed >= 0 else int(time.time()),
    #         "nologo": "true",
    #     }
    #     if self.api_key:
    #         params["key"] = self.api_key

    #     for attempt in range(1, retries + 1):
    #         try:
    #             print(f"  [Gen] Attempt {attempt}/{retries} — {width}×{height}...")
    #             resp = requests.get(url, params=params, headers=self.headers, timeout=60)
    #             resp.raise_for_status()
    #             img = Image.open(io.BytesIO(resp.content)).convert("RGBA")
    #             print(f"  [Gen] ✓ Received {img.size}")
    #             return img
    #         except requests.exceptions.RequestException as e:
    #             print(f"  [Gen] ✗ Error: {e}")
    #             if attempt < retries:
    #                 time.sleep(5 * attempt)
    #             else:
    #                 raise RuntimeError(f"Không thể sinh ảnh sau {retries} lần thử.") from e

    def generate(self, prompt: str) -> Image.Image:

        encoded = quote(prompt)

        url = f"{BASE_URL}/{encoded}"

        print("[DEBUG] URL =", url)

        response = requests.get(
            url,
            timeout=60
        )

        response.raise_for_status()

        img = Image.open(
            io.BytesIO(response.content)
        ).convert("RGBA")

        return img

# ─────────────────────────────────────────────
# POST-PROCESSOR
# ─────────────────────────────────────────────

class AssetPostProcessor:
    """
    Xử lý ảnh sau khi sinh: resize, pixel-art effect, cắt tilesheet.
    """

    @staticmethod
    def resize_to_standard(img: Image.Image, asset_type: str) -> Image.Image:
        target = ASSET_SIZES.get(asset_type)
        if not target:
            raise ValueError(f"Không tìm thấy kích thước cho '{asset_type}'. "
                             f"Các loại hợp lệ: {list(ASSET_SIZES)}")
        return img.resize(target, Image.LANCZOS)

    @staticmethod
    def apply_pixel_art_effect(img: Image.Image, block_size: int = 8) -> Image.Image:
        """
        Pixelate ảnh: thu nhỏ rồi scale lại → hiệu ứng pixel thô.
        """
        w, h  = img.size
        small = img.resize((w // block_size, h // block_size), Image.NEAREST)
        return small.resize((w, h), Image.NEAREST)

    @staticmethod
    def reduce_palette(img: Image.Image, colors: int = 32) -> Image.Image:
        """Giảm số màu → giống hơn 8-bit asset."""
        rgb = img.convert("RGB")
        reduced = rgb.quantize(colors=colors).convert("RGBA")
        return reduced

    @staticmethod
    def remove_white_background(img: Image.Image, threshold: int = 240) -> Image.Image:
        """
        Chuyển pixel trắng/gần trắng thành trong suốt — hữu ích cho sprite.
        """
        img = img.convert("RGBA")
        data = img.getdata()
        new_data = []
        for r, g, b, a in data:
            if r > threshold and g > threshold and b > threshold:
                new_data.append((255, 255, 255, 0))
            else:
                new_data.append((r, g, b, a))
        img.putdata(new_data)
        return img

    @staticmethod
    def slice_tilesheet(img: Image.Image, frames: int = 10) -> list[Image.Image]:
        """
        Cắt tilesheet ngang thành danh sách frame riêng lẻ.
        """
        w, h = img.size
        frame_w = w // frames
        slices = []
        for i in range(frames):
            box = (i * frame_w, 0, (i + 1) * frame_w, h)
            slices.append(img.crop(box))
        return slices

    @staticmethod
    def save(img: Image.Image, path: Path, fmt: str = "PNG") -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        img.save(path, fmt)
        print(f"  [Save] ✓ {path}")


# ─────────────────────────────────────────────
# ASSET STUDIO — FACADE CHÍNH
# ─────────────────────────────────────────────

class GameAssetStudio:
    """
    Lớp chính, tổng hợp PromptOptimizer + ImageGenerator + PostProcessor.
    Khôi & Hậu sẽ gọi các hàm này từ backend.
    """

    def __init__(self, api_key: str = API_KEY, model: str = "flux",
                 output_dir: str = "output"):
        self.gen   = ImageGenerator(api_key=api_key, model=model)
        self.proc  = AssetPostProcessor()
        self.out   = Path(output_dir)
        self.out.mkdir(parents=True, exist_ok=True)

    # ── 1. Background ──────────────────────────────────────────────
    def generate_background(self, subject: str, size_key: str = "background_hd",
                             style: str = "pixel_art", time_of_day: str = "day",
                             seed: int = -1, filename: str = None) -> Path:
        """
        Sinh background với kích thước chuẩn.
        Ví dụ: studio.generate_background("forest with waterfall", size_key="background_hd")
        """
        print(f"\n🌄 Generating background: '{subject}' [{size_key}]")
        prompt   = PromptOptimizer.build_background_prompt(subject, style, time_of_day)
        w, h     = ASSET_SIZES[size_key]
        img      = self.gen.generate(prompt)
        img      = self.proc.resize_to_standard(img, size_key)

        out_name = filename or self._safe_name(f"bg_{subject}_{size_key}")
        path     = self.out / "backgrounds" / f"{out_name}.png"
        self.proc.save(img, path)
        return path

    # ── 2. Sprite ──────────────────────────────────────────────────
    def generate_sprite(self, subject: str, size_key: str = "sprite_medium",
                        style: str = "pixel_art", facing: str = "front",
                        transparent_bg: bool = True, seed: int = -1,
                        filename: str = None) -> Path:
        """
        Sinh sprite nhân vật / đồ vật.
        """
        print(f"\n🧑 Generating sprite: '{subject}' [{size_key}]")
        prompt = PromptOptimizer.build_sprite_prompt(subject, style, facing)
        w, h   = ASSET_SIZES[size_key]
        img    = self.gen.generate(prompt)
        img    = self.proc.resize_to_standard(img, size_key)

        if transparent_bg:
            img = self.proc.remove_white_background(img)

        out_name = filename or self._safe_name(f"sprite_{subject}_{size_key}")
        path     = self.out / "sprites" / f"{out_name}.png"
        self.proc.save(img, path)
        return path

    # ── 3. Pixel Art ───────────────────────────────────────────────
    def generate_pixel_art(self, subject: str, size_key: str = "sprite_medium",
                            block_size: int = 8, colors: int = 32,
                            seed: int = -1, filename: str = None) -> Path:
        """
        Sinh ảnh rồi áp dụng bộ lọc pixel-art + giảm palette.
        """
        print(f"\n🎮 Generating pixel art: '{subject}'")
        prompt = PromptOptimizer.build_pixel_art_prompt(subject)
        w, h   = ASSET_SIZES[size_key]
        img    = self.gen.generate(prompt)
        img    = self.proc.resize_to_standard(img, size_key)
        img    = self.proc.apply_pixel_art_effect(img, block_size=block_size)
        img    = self.proc.reduce_palette(img, colors=colors)

        out_name = filename or self._safe_name(f"pixel_{subject}")
        path     = self.out / "pixel_art" / f"{out_name}.png"
        self.proc.save(img, path)
        return path

    # ── 4. Tilesheet (animation) ───────────────────────────────────
    def generate_tilesheet(self, subject: str, frames: int = 10,
                            style: str = "pixel_art", seed: int = -1,
                            slice_frames: bool = False,
                            filename: str = None) -> Path:
        """
        Sinh tilesheet gồm N frame animation liên tiếp theo chiều ngang.
        Nếu slice_frames=True, cũng lưu từng frame riêng lẻ vào thư mục con.
        """
        print(f"\n🎞  Generating tilesheet: '{subject}' ({frames} frames)")
        prompt  = PromptOptimizer.build_tilesheet_prompt(subject, style, frames)
        # Tilesheet: chiều rộng = frames * frame_width, chiều cao cố định 512
        frame_w = 64          # 64px mỗi frame → phù hợp Scratch/Gamemaker
        total_w = frame_w * frames
        img     = self.gen.generate(prompt)

        out_name = filename or self._safe_name(f"tilesheet_{subject}_{frames}f")
        path     = self.out / "tilesheets" / f"{out_name}.png"
        self.proc.save(img, path)

        if slice_frames:
            slices   = self.proc.slice_tilesheet(img, frames=frames)
            frame_dir = self.out / "tilesheets" / out_name
            for i, frame in enumerate(slices):
                self.proc.save(frame, frame_dir / f"frame_{i:02d}.png")
            print(f"  [Slice] ✓ {frames} frames lưu vào {frame_dir}")

        return path

    # ── Helper ─────────────────────────────────────────────────────
    @staticmethod
    def _safe_name(name: str) -> str:
        """Chuyển tên thành slug an toàn cho filesystem."""
        return re.sub(r"[^a-zA-Z0-9_\-]", "_", name.lower())[:80]


# ─────────────────────────────────────────────
# DEMO / QUICK TEST
# ─────────────────────────────────────────────

if __name__ == "__main__":
    studio = GameAssetStudio(
        api_key=os.getenv("POLLINATIONS_API_KEY", ""),
        model="flux",
        output_dir="output",
    )

    # --- Test 1: Background cho khóa Scratch ---
    studio.generate_background(
        subject="fantasy forest with mushrooms and glowing fireflies",
        size_key="background_sd",   # 1280x720 phù hợp Scratch
        style="pixel_art",
        time_of_day="night",
        seed=42,
    )

    # --- Test 2: Sprite nhân vật ---
    studio.generate_sprite(
        subject="cute wizard character",
        size_key="sprite_medium",   # 128x128
        style="pixel_art",
        facing="front",
        transparent_bg=True,
        seed=42,
    )

    # --- Test 3: Pixel Art item ---
    studio.generate_pixel_art(
        subject="treasure chest",
        size_key="sprite_small",    # 64x64
        block_size=4,
        colors=16,
        seed=42,
    )

    # --- Test 4: Tilesheet chạy bộ 10 frame ---
    studio.generate_tilesheet(
        subject="running robot character",
        frames=10,
        style="pixel_art",
        seed=42,
        slice_frames=True,          # cũng cắt frame lẻ
    )

    print("\n✅ Xong! Kiểm tra thư mục output/")
