"""
AI Game Asset Studio - AI embeddable module.

Scope:
- Build prompts for game assets.
- Call an image provider (currently Pollinations).
- Post-process generated images into predictable game-ready outputs.
- Return metadata that a web/backend team can consume.
"""

from __future__ import annotations

import io
import json
import os
import re
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import quote

import requests
from PIL import Image, ImageChops, ImageFilter, ImageOps, UnidentifiedImageError


POLLINATIONS_BASE_URL = "https://image.pollinations.ai/prompt"
API_KEY = os.getenv("POLLINATIONS_API_KEY", "")
OUTPUT_DIR = Path("output")


ASSET_SIZES: dict[str, tuple[int, int]] = {
    "scratch_bg": (480, 360),
    "background_hd": (1920, 1080),
    "background_4k": (3840, 2160),
    "background_sd": (1280, 720),
    "background_sq": (1080, 1080),
    "sprite_small": (64, 64),
    "sprite_medium": (128, 128),
    "sprite_large": (256, 256),
    "icon": (32, 32),
}

BACKGROUND_SIZE_KEYS = {"scratch_bg", "background_hd", "background_4k", "background_sd", "background_sq"}
SPRITE_SIZE_KEYS = {"sprite_small", "sprite_medium", "sprite_large", "icon"}
PIXEL_SIZE_KEYS = SPRITE_SIZE_KEYS | {"background_sq"}


# ── Asset category / view / theme options for frontend ──────────

ASSET_CATEGORIES: dict[str, dict] = {
    "character": {
        "label": "Nhân vật",
        "description": "Game characters (heroes, enemies, NPCs)",
        "allowed_views": ["front", "left", "right", "side", "back", "three_quarter", "isometric", "top_down"],
        "allowed_styles": ["pixel_art", "cartoon", "realistic", "chibi"],
        "transparent_default": True,
    },
    "prop": {
        "label": "Vật phẩm",
        "description": "Items, weapons, shields, potions, collectibles",
        "allowed_views": ["front", "isometric", "top_down"],
        "allowed_styles": ["pixel_art", "cartoon", "realistic", "chibi"],
        "transparent_default": True,
    },
    "environment": {
        "label": "Hình nền",
        "description": "Backgrounds and environments",
        "allowed_views": ["side_scroll", "top_down", "isometric"],
        "allowed_styles": ["pixel_art", "cartoon", "realistic"],
        "transparent_default": False,
    },
}

VIEW_ANGLES: dict[str, str] = {
    "front": "front-facing view",
    "left": "left-facing side profile view",
    "right": "right-facing side profile view",
    "side": "right-facing side profile view",
    "back": "rear view, back facing",
    "three_quarter": "three-quarter view, slightly angled",
    "isometric": "isometric 45-degree angle view, 2:1 isometric perspective",
    "top_down": "top-down bird's eye view, directly from above",
    "side_scroll": "side-scrolling platformer view",
}

ENVIRONMENT_THEMES: dict[str, str] = {
    "fantasy": "fantasy medieval, castles, dragons, enchanted forests, magical atmosphere",
    "cyberpunk": "cyberpunk, neon lights, futuristic city, holographic signs, rain-soaked streets",
    "medieval": "medieval, stone castles, villages, cobblestone roads, torchlight",
    "sci_fi": "science fiction, space stations, alien planets, advanced technology",
    "nature": "natural landscape, forests, rivers, mountains, peaceful atmosphere",
    "mythological": "mythological, ancient temples, gods, legendary creatures, epic clouds",
    "horror": "dark horror, abandoned buildings, fog, eerie atmosphere, moonlight",
    "underwater": "underwater ocean, coral reefs, deep sea, bioluminescent creatures",
}

ITEM_TYPES: dict[str, str] = {
    "weapon": "weapon, sharp edges, battle-ready",
    "shield": "shield, defensive gear, emblem",
    "potion": "potion bottle, liquid, magical glow",
    "armor": "armor piece, protective gear, metallic",
    "collectible": "collectible item, treasure, pickup",
    "food": "food item, consumable, colorful",
    "key": "key, unlock item, ornate",
    "scroll": "scroll, parchment, magical runes",
}


@dataclass
class FrameMetadata:
    index: int
    x: int
    y: int
    w: int
    h: int
    file_path: str | None = None


@dataclass
class GeneratedAsset:
    asset_id: str
    asset_type: str
    prompt: str
    provider: str
    model: str
    seed: int
    width: int
    height: int
    format: str
    file_path: str
    has_alpha: bool
    frames: list[FrameMetadata] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def path(self) -> Path:
        return Path(self.file_path)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def __fspath__(self) -> str:
        return self.file_path

    def __str__(self) -> str:
        return self.file_path


@dataclass
class ProviderResult:
    image: Image.Image
    provider: str
    model: str
    seed: int
    warnings: list[str] = field(default_factory=list)


class AIImageProvider(Protocol):
    name: str
    model: str

    def generate(
        self,
        prompt: str,
        *,
        width: int,
        height: int,
        seed: int = -1,
        negative_prompt: str | None = None,
    ) -> ProviderResult:
        ...


class PromptOptimizer:
    """Build prompts for different game asset types."""

    STYLE_TAGS = {
        "pixel_art": (
            "premium hand-crafted pixel art, crisp hard pixels, clean 2D game production style, "
            "intentional pixel clusters, readable silhouette, vibrant child-friendly palette, "
            "limited professional palette, no anti-aliasing, no blurry AI texture"
        ),
        "cartoon": (
            "polished 2D cartoon game art, flat colors, clean confident outlines, "
            "appealing shape language, vibrant child-friendly palette, readable silhouette"
        ),
        "realistic": "stylized realistic 2D game art, detailed but game-readable textures, high quality, balanced composition",
        "chibi": "cute premium chibi game sprite, rounded shapes, vibrant colors, clean outline, child-friendly",
    }

    NEGATIVE_BASE = (
        "blurry, watermark, text, logo, signature, extra limbs, bad anatomy, "
        "low quality, cheap clipart, generic placeholder, cropped, deformed, noisy, "
        "muddy colors, cluttered composition, inconsistent style, melted details"
    )

    @staticmethod
    def build_background_prompt(
        subject: str,
        style: str = "pixel_art",
        time_of_day: str = "day",
    ) -> str:
        style_tag = PromptOptimizer.STYLE_TAGS.get(style, style)
        return (
            f"{subject}, {time_of_day} lighting, polished 2D game background, "
            f"side-scrolling platformer environment, clear foreground midground background layers, "
            f"vibrant appealing colors, balanced composition, visual depth, no characters, no HUD, "
            f"{style_tag}, wide shot, clean readable shapes for Scratch children"
        )

    @staticmethod
    def build_sprite_prompt(
        subject: str,
        style: str = "pixel_art",
        facing: str = "front",
    ) -> str:
        style_tag = PromptOptimizer.STYLE_TAGS.get(style, style)
        return (
            f"single full-body 2D game character sprite, {subject}, {facing} facing, "
            f"centered inside frame with comfortable padding, complete body visible, "
            f"no cropped limbs, no cropped weapon, no cropped accessories, transparent background, "
            f"bold readable silhouette, polished game-ready design, Scratch-style friendly character, "
            f"{style_tag}, limited palette, crisp edges, no scenery"
        )

    # New per‑frame animation prompt
    @staticmethod
    def build_animation_frame_prompt(
        subject: str,
        action: str,
        frame_index: int,
        total_frames: int,
        style: str = "pixel_art",
        facing: str = "right",
    ) -> str:
        """Build a prompt for a single animation frame with a specific pose."""
        style_tag = PromptOptimizer.STYLE_TAGS.get(style, style)
        # Provide a more explicit description based on the frame index
        # This is a simple mapping; you can expand it for more actions.
        frame_desc = PromptOptimizer._get_frame_description(action, frame_index, total_frames)
        return (
            f"single full-body 2D game character sprite, {subject}, {facing} facing, "
            f"{frame_desc}, "
            f"centered inside frame with comfortable padding, complete body visible, "
            f"no cropped limbs, no cropped weapon, no cropped accessories, transparent background, "
            f"bold readable silhouette, polished game-ready design, Scratch-style friendly character, "
            f"{style_tag}, limited palette, crisp edges, no scenery"
        )

    @staticmethod
    def _get_frame_description(action: str, idx: int, total: int) -> str:
        """Generate a pose description based on action and frame index."""
        # Simple canned descriptions – feel free to enhance
        if action == "idle":
            poses = [
                "standing still, arms relaxed at sides, chest slightly puffed",
                "standing, weight shifting to one foot, arms hanging naturally",
                "standing, looking ahead, slight sway, calm breathing",
                "standing, feet apart, arms slightly bent, ready stance",
            ]
        elif action == "walk":
            poses = [
                "right leg forward, left arm forward",
                "feet together, arms at sides",
                "left leg forward, right arm forward",
                "feet together, arms swinging slightly",
            ]
        elif action == "run":
            poses = [
                "right leg stretched forward, left arm forward, leaning",
                "both feet off ground, arms pumping",
                "left leg forward, right arm forward, body leaning",
                "both feet off ground, arms behind, forward momentum",
            ]
        elif action == "attack":
            poses = [
                "winding up weapon, blade raised behind head",
                "swinging weapon forward, torso twisted",
                "weapon fully extended, striking pose",
                "recovering, weapon held diagonally",
            ]
        elif action == "jump":
            poses = [
                "crouching, hands down, ready to spring",
                "launching upward, arms raised, legs tucked",
                "at peak height, arms up, legs bent",
                "falling, arms out, legs straightening",
                "landing, bent knees, arms out for balance",
            ]
        else:
            # generic: just use index
            return f"pose {idx+1} of {total} in a {action} animation cycle"

        # Cycle through the list based on index
        return poses[idx % len(poses)]

    # Updated tile prompt – now takes the tile name explicitly
    @staticmethod
    def build_tile_prompt(
        subject: str,
        tile_name: str,
        style: str = "pixel_art",
    ) -> str:
        style_tag = PromptOptimizer.STYLE_TAGS.get(style, style)
        return (
            f"seamless square {tile_name} terrain tile for {subject}, tileable on all four edges, "
            f"orthographic top-down view, no perspective horizon, no large object crossing tile boundaries, "
            f"professional game tileset texture, readable material pattern, balanced contrast, "
            f"vibrant game-ready palette, no characters, no UI, no text, {style_tag}, "
            f"designed for direct grid import into Scratch or Gamemaker"
        )

    @staticmethod
    def build_pixel_art_prompt(subject: str) -> str:
        return (
            f"{subject}, polished pixel art game asset, centered icon-like composition, "
            f"readable silhouette, bright distinguishable palette, dark outline, transparent background, "
            f"no blur, no gradients, crisp hard pixel edges, classic NES/SNES style, game-ready"
        )

    @staticmethod
    def get_negative_prompt(asset_type: str = "general") -> str:
        extras = {
            "background": ", characters, people, HUD, UI elements",
            "sprite": ", background scenery, multiple objects, multiple poses, icon-only crop, cut off weapon",
            "prop": ", character, hand holding item, scenery, table, icon-only crop, photorealistic mockup",
            "sprite_sheet": ", merged frames, uneven spacing, different character scale, changing outfit, changing face",
            "tileset": ", characters, people, text, UI, perspective scene, horizon line, non-tileable edges, random objects",
            "tile": ", landscape, full scene, large objects crossing edges",  # new for individual tiles
        }
        # Backward compatibility for old asset type name
        if asset_type == "tile_sheet":
            asset_type = "tileset"
        return PromptOptimizer.NEGATIVE_BASE + extras.get(asset_type, "")

    @staticmethod
    def canonical_view_angle(view_angle: str) -> str:
        """Use a stable generation direction; left-facing output is mirrored after generation."""
        if view_angle in {"left", "side"}:
            return "right"
        return view_angle

    @staticmethod
    def build_character_prompt(
        subject: str,
        style: str = "pixel_art",
        view_angle: str = "front",
    ) -> str:
        """Build prompt for character sprites with camera view angle support."""
        style_tag = PromptOptimizer.STYLE_TAGS.get(style, style)
        canonical_view = PromptOptimizer.canonical_view_angle(view_angle)
        view_tag = VIEW_ANGLES.get(canonical_view, canonical_view)
        direction_rule = (
            "strict clean profile facing right, head nose feet and weapon all point right, "
            "do not draw front-facing pose, "
            if canonical_view == "right"
            else ""
        )
        return (
            f"single full-body 2D game character sprite, {subject}, {view_tag}, "
            f"{direction_rule}"
            f"production-quality Scratch and Gamemaker asset, not a prototype, "
            f"centered inside frame with 12 percent transparent padding, complete body visible, "
            f"no cropped limbs, no cropped weapon, no cropped accessories, transparent background, "
            f"strong readable silhouette, appealing proportions, clean face, intentional costume design, "
            f"one character only, no duplicate poses, {style_tag}, crisp edges, no scenery"
        )

    @staticmethod
    def build_prop_prompt(
        subject: str,
        item_type: str = "collectible",
        style: str = "pixel_art",
        view_angle: str = "front",
    ) -> str:
        """Build prompt for item/prop sprites (weapon, shield, potion, etc.)."""
        style_tag = PromptOptimizer.STYLE_TAGS.get(style, style)
        canonical_view = PromptOptimizer.canonical_view_angle(view_angle)
        view_tag = VIEW_ANGLES.get(canonical_view, canonical_view)
        type_tag = ITEM_TYPES.get(item_type, item_type)
        return (
            f"single 2D game prop sprite, {subject}, {type_tag}, {view_tag}, "
            f"production-quality collectible asset, centered with transparent padding, "
            f"clear readable silhouette, polished highlights and shadows, bold clean outline, "
            f"no character, no hand, no scenery, no UI, {style_tag}, game-ready asset"
        )

    @staticmethod
    def build_environment_prompt(
        subject: str,
        theme: str = "fantasy",
        style: str = "pixel_art",
        time_of_day: str = "day",
        view_angle: str = "side_scroll",
    ) -> str:
        """Build prompt for environment/background with theme taxonomy."""
        style_tag = PromptOptimizer.STYLE_TAGS.get(style, style)
        theme_tag = ENVIRONMENT_THEMES.get(theme, theme)
        view_tag = VIEW_ANGLES.get(view_angle, view_angle)
        return (
            f"{subject}, {theme_tag}, {time_of_day} lighting, "
            f"polished 2D game background, {view_tag}, production-quality environment art, "
            f"clear foreground midground background layers with parallax depth, vibrant appealing colors, "
            f"landmarks, paths, platforms, environmental storytelling, distant silhouettes, atmospheric depth, "
            f"balanced composition, readable gameplay space, open areas for sprites, no characters, no HUD, "
            f"{style_tag}, wide shot, clean readable shapes, detailed but not cluttered, not a rough AI concept"
        )


class PollinationsProvider:
    """Pollinations image provider adapter."""

    name = "pollinations"

    def __init__(
        self,
        api_key: str = API_KEY,
        model: str = "flux",
        base_url: str = POLLINATIONS_BASE_URL,
        timeout: int = 90,
        retries: int = 3,
        private: bool = True,
        enhance: bool = False,
        nologo: bool = True,
    ):
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.retries = retries
        self.private = private
        self.enhance = enhance
        self.nologo = nologo

    def generate(
        self,
        prompt: str,
        *,
        width: int,
        height: int,
        seed: int = -1,
        negative_prompt: str | None = None,
    ) -> ProviderResult:
        actual_seed = seed if seed >= 0 else int(time.time() * 1000) % 2_147_483_647
        full_prompt = prompt
        if negative_prompt:
            full_prompt = f"{prompt}. Avoid: {negative_prompt}"

        url = f"{self.base_url}/{quote(full_prompt)}"
        params: dict[str, Any] = {
            "model": self.model,
            "width": width,
            "height": height,
            "seed": actual_seed,
            "nologo": str(self.nologo).lower(),
            "private": str(self.private).lower(),
            "enhance": str(self.enhance).lower(),
        }
        if self.api_key:
            # Pollinations deployments have used both key/token naming; sending both is harmless for GET params.
            params["key"] = self.api_key
            params["token"] = self.api_key

        last_error: Exception | None = None
        for attempt in range(1, self.retries + 1):
            try:
                response = requests.get(url, params=params, timeout=self.timeout)
                response.raise_for_status()

                content_type = response.headers.get("content-type", "")
                if "image" not in content_type.lower():
                    preview = response.text[:200]
                    raise RuntimeError(f"Provider did not return an image. Content-Type={content_type}. Body={preview!r}")

                image = Image.open(io.BytesIO(response.content)).convert("RGBA")
                warnings: list[str] = []
                if image.size != (width, height):
                    warnings.append(
                        f"Provider returned {image.size[0]}x{image.size[1]} instead of requested {width}x{height}; post-processed locally."
                    )
                return ProviderResult(
                    image=image,
                    provider=self.name,
                    model=self.model,
                    seed=actual_seed,
                    warnings=warnings,
                )
            except (requests.RequestException, UnidentifiedImageError, RuntimeError) as exc:
                last_error = exc
                if attempt < self.retries:
                    time.sleep(2 * attempt)

        raise RuntimeError(f"Cannot generate image after {self.retries} attempts: {last_error}") from last_error


class ImageGenerator:
    """Backward-compatible wrapper around the selected provider."""

    def __init__(self, api_key: str = API_KEY, model: str = "flux", provider: AIImageProvider | None = None):
        self.provider = provider or PollinationsProvider(api_key=api_key, model=model)

    def generate(
        self,
        prompt: str,
        width: int = 512,
        height: int = 512,
        seed: int = -1,
        negative_prompt: str | None = None,
    ) -> Image.Image:
        return self.generate_with_metadata(
            prompt,
            width=width,
            height=height,
            seed=seed,
            negative_prompt=negative_prompt,
        ).image

    def generate_with_metadata(
        self,
        prompt: str,
        *,
        width: int,
        height: int,
        seed: int = -1,
        negative_prompt: str | None = None,
    ) -> ProviderResult:
        return self.provider.generate(
            prompt,
            width=width,
            height=height,
            seed=seed,
            negative_prompt=negative_prompt,
        )


class AssetPostProcessor:
    """Post-process images into predictable game asset outputs."""

    @staticmethod
    def fit_to_canvas(
        img: Image.Image,
        target_size: tuple[int, int],
        *,
        resample: Image.Resampling = Image.Resampling.LANCZOS,
        background: tuple[int, int, int, int] = (0, 0, 0, 0),
        padding: int = 0,
    ) -> Image.Image:
        """Keep aspect ratio and center image on a fixed-size transparent canvas."""
        img = img.convert("RGBA")
        inner_size = (
            max(1, target_size[0] - padding * 2),
            max(1, target_size[1] - padding * 2),
        )
        fitted = ImageOps.contain(img, inner_size, method=resample)
        canvas = Image.new("RGBA", target_size, background)
        x = (target_size[0] - fitted.width) // 2
        y = (target_size[1] - fitted.height) // 2
        canvas.alpha_composite(fitted, (x, y))
        return canvas

    @staticmethod
    def cover_to_canvas(
        img: Image.Image,
        target_size: tuple[int, int],
        *,
        resample: Image.Resampling = Image.Resampling.LANCZOS,
    ) -> Image.Image:
        """Fill target canvas without distortion, cropping overflow."""
        return ImageOps.fit(img.convert("RGBA"), target_size, method=resample, centering=(0.5, 0.5))

    @staticmethod
    def resize_to_standard(
        img: Image.Image,
        asset_type: str,
        *,
        mode: str = "contain",
        pixel_art: bool = False,
    ) -> Image.Image:
        target = ASSET_SIZES.get(asset_type)
        if not target:
            raise ValueError(f"Unknown size key '{asset_type}'. Valid keys: {list(ASSET_SIZES)}")

        resample = Image.Resampling.NEAREST if pixel_art else Image.Resampling.LANCZOS
        if mode == "cover":
            return AssetPostProcessor.cover_to_canvas(img, target, resample=resample)
        if mode == "contain":
            return AssetPostProcessor.fit_to_canvas(img, target, resample=resample)
        raise ValueError("mode must be either 'contain' or 'cover'")

    @staticmethod
    def apply_pixel_art_effect(img: Image.Image, block_size: int = 8) -> Image.Image:
        if block_size < 1:
            raise ValueError("block_size must be >= 1")

        img = img.convert("RGBA")
        w, h = img.size
        small_w = max(1, w // block_size)
        small_h = max(1, h // block_size)
        small = img.resize((small_w, small_h), Image.Resampling.NEAREST)
        return small.resize((w, h), Image.Resampling.NEAREST)

    @staticmethod
    def reduce_palette(img: Image.Image, colors: int = 32) -> Image.Image:
        if colors < 2 or colors > 256:
            raise ValueError("colors must be between 2 and 256")

        img = img.convert("RGBA")
        alpha = img.getchannel("A")
        rgb = img.convert("RGB")
        reduced = rgb.quantize(colors=colors).convert("RGBA")
        reduced.putalpha(alpha)
        return reduced

    @staticmethod
    def normalize_pixel_asset(img: Image.Image, colors: int = 24) -> Image.Image:
        """Make small generated assets look more deliberate and less like soft AI thumbnails."""
        img = img.convert("RGBA")
        img = AssetPostProcessor.reduce_palette(img, colors=colors)
        # Re-apply nearest scaling through the same size to remove palette conversion softness.
        return img.resize(img.size, Image.Resampling.NEAREST)

    @staticmethod
    def mirror_if_left(img: Image.Image, requested_view: str) -> Image.Image:
        """Generate one canonical side direction and mirror it for left-facing assets."""
        if requested_view == "left":
            return ImageOps.mirror(img.convert("RGBA"))
        return img.convert("RGBA")

    @staticmethod
    def make_tileable(img: Image.Image, edge_blend: int = 6) -> Image.Image:
        """
        Lightly fix tile seams by blending opposite edges.

        This does not replace true seamless generation, but it makes AI/provider output more usable
        for Scratch/Gamemaker tile import by reducing visible hard seams.
        """
        img = img.convert("RGBA")
        w, h = img.size
        if w < 8 or h < 8:
            return img

        blend = max(1, min(edge_blend, w // 4, h // 4))
        px = img.load()

        for x in range(w):
            for i in range(blend):
                top = px[x, i]
                bottom = px[x, h - 1 - i]
                mixed = tuple((top[c] + bottom[c]) // 2 for c in range(4))
                px[x, i] = mixed
                px[x, h - 1 - i] = mixed

        for y in range(h):
            for i in range(blend):
                left = px[i, y]
                right = px[w - 1 - i, y]
                mixed = tuple((left[c] + right[c]) // 2 for c in range(4))
                px[i, y] = mixed
                px[w - 1 - i, y] = mixed

        return img

    @staticmethod
    def add_alpha_outline(
        img: Image.Image,
        color: tuple[int, int, int, int] = (28, 30, 38, 255),
        radius: int = 1,
    ) -> Image.Image:
        """Add a crisp outline around transparent sprites for better game readability."""
        if radius < 1:
            return img.convert("RGBA")

        img = img.convert("RGBA")
        alpha = img.getchannel("A")
        expanded_alpha = alpha.filter(ImageFilter.MaxFilter(radius * 2 + 1))
        outline_alpha = ImageChops.subtract(expanded_alpha, alpha)

        outline = Image.new("RGBA", img.size, color)
        outline.putalpha(outline_alpha)
        outline.alpha_composite(img)
        return outline

    @staticmethod
    def remove_background(img: Image.Image, threshold: int = 245) -> Image.Image:
        """Remove background. Use rembg if installed; otherwise fall back to near-white removal."""
        img = img.convert("RGBA")
        try:
            from rembg import remove  # type: ignore

            return remove(img).convert("RGBA")
        except (ImportError, OSError, RuntimeError, SystemExit):
            cleaned = AssetPostProcessor.remove_near_white_background(img, threshold=threshold)
            return AssetPostProcessor.remove_checkerboard_background(cleaned)

    @staticmethod
    def remove_near_white_background(img: Image.Image, threshold: int = 245) -> Image.Image:
        img = img.convert("RGBA")
        pixels = []
        for r, g, b, a in img.getdata():
            if r >= threshold and g >= threshold and b >= threshold:
                pixels.append((r, g, b, 0))
            else:
                pixels.append((r, g, b, a))
        img.putdata(pixels)
        return img

    @staticmethod
    def remove_checkerboard_background(img: Image.Image) -> Image.Image:
        """
        Remove baked transparent-preview checkerboards connected to the image border.

        This targets demo/reference PNGs that already contain gray checker pixels instead
        of a real alpha channel, without erasing interior gray armor/details.
        """
        img = img.convert("RGBA")
        width, height = img.size
        pixels = img.load()

        def is_checker_pixel(x: int, y: int) -> bool:
            r, g, b, a = pixels[x, y]
            if a == 0:
                return True
            neutral = abs(r - g) <= 4 and abs(g - b) <= 4 and abs(r - b) <= 4
            return neutral and 110 <= r <= 230

        stack: list[tuple[int, int]] = []
        visited: set[tuple[int, int]] = set()
        for x in range(width):
            stack.append((x, 0))
            stack.append((x, height - 1))
        for y in range(height):
            stack.append((0, y))
            stack.append((width - 1, y))

        while stack:
            x, y = stack.pop()
            if (x, y) in visited or x < 0 or y < 0 or x >= width or y >= height:
                continue
            visited.add((x, y))
            if not is_checker_pixel(x, y):
                continue

            r, g, b, _ = pixels[x, y]
            pixels[x, y] = (r, g, b, 0)
            stack.extend(((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)))

        return img

    @staticmethod
    def compose_sprite_sheet(frames: list[Image.Image], frame_size: tuple[int, int]) -> Image.Image:
        if not frames:
            raise ValueError("frames cannot be empty")

        frame_w, frame_h = frame_size
        sheet = Image.new("RGBA", (frame_w * len(frames), frame_h), (0, 0, 0, 0))
        for index, frame in enumerate(frames):
            normalized = AssetPostProcessor.fit_to_canvas(
                frame,
                frame_size,
                resample=Image.Resampling.NEAREST,
            )
            sheet.alpha_composite(normalized, (index * frame_w, 0))
        return sheet

    @staticmethod
    def compose_tileset(
        tiles: list[Image.Image],
        tile_size: tuple[int, int],
        columns: int,
    ) -> Image.Image:
        if not tiles:
            raise ValueError("tiles cannot be empty")
        if columns < 1:
            raise ValueError("columns must be >= 1")

        tile_w, tile_h = tile_size
        rows = (len(tiles) + columns - 1) // columns
        sheet = Image.new("RGBA", (columns * tile_w, rows * tile_h), (0, 0, 0, 0))
        for index, tile in enumerate(tiles):
            x = (index % columns) * tile_w
            y = (index // columns) * tile_h
            normalized = AssetPostProcessor.cover_to_canvas(
                tile,
                tile_size,
                resample=Image.Resampling.NEAREST,
            )
            sheet.alpha_composite(normalized, (x, y))
        return sheet

    @staticmethod
    def compose_tile_sheet(*args, **kwargs) -> Image.Image:
        return AssetPostProcessor.compose_tileset(*args, **kwargs)

    @staticmethod
    def slice_sprite_sheet(img: Image.Image, frames: int, frame_size: tuple[int, int]) -> list[Image.Image]:
        """
        Slices a horizontal spritesheet into equal frames with uniform scaling.
        Guarantees that all frames are scaled by the exact same factor and centered stably.
        """
        img = img.convert("RGBA")
        if img.width <= 0 or img.height <= 0:
            return []

        cell_w = img.width // frames
        cell_h = img.height

        # 1. Slice into cells and find active bboxes
        cells = []
        bboxes = []
        for i in range(frames):
            cell = img.crop((i * cell_w, 0, (i + 1) * cell_w, cell_h))
            cells.append(cell)
            bbox = cell.getbbox()
            bboxes.append(bbox)

        # 2. Find max active width and height across all non-empty cells
        valid_bboxes = [b for b in bboxes if b is not None]
        if not valid_bboxes:
            # Fallback if entire sheet is empty
            return cells

        max_w = max(b[2] - b[0] for b in valid_bboxes)
        max_h = max(b[3] - b[1] for b in valid_bboxes)

        # Ensure max_w and max_h are at least 1
        max_w = max(1, max_w)
        max_h = max(1, max_h)

        # 3. Calculate the average center of mass/bbox relative to each cell
        centers = []
        for bbox in bboxes:
            if bbox is not None:
                cx = (bbox[0] + bbox[2]) // 2
                cy = (bbox[1] + bbox[3]) // 2
                centers.append((cx, cy))

        if centers:
            avg_cx = sum(c[0] for c in centers) // len(centers)
            avg_cy = sum(c[1] for c in centers) // len(centers)
        else:
            avg_cx = cell_w // 2
            avg_cy = cell_h // 2

        # 4. Crop each cell to a uniform box of size max_w x max_h centered on the average character center
        uniform_cropped = []
        for i in range(frames):
            cell = cells[i]
            left = avg_cx - max_w // 2
            top = avg_cy - max_h // 2
            right = left + max_w
            bottom = top + max_h

            cropped = cell.crop((left, top, right, bottom))
            uniform_cropped.append(cropped)

        return uniform_cropped

    @staticmethod
    def save(img: Image.Image, path: Path, fmt: str = "PNG") -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        img.save(path, fmt)

    @staticmethod
    def match_palette(source_img: Image.Image, reference_img: Image.Image) -> Image.Image:
        """Adjust source image colors to match the reference image's color palette."""
        source_rgb = source_img.convert("RGB")
        ref_rgb = reference_img.convert("RGB")
        
        ref_paletted = ref_rgb.convert("P", palette=Image.Palette.ADAPTIVE, colors=256)
        matched = source_rgb.quantize(palette=ref_paletted, dither=Image.Dither.NONE)
        
        matched_rgba = matched.convert("RGBA")
        if "A" in source_img.getbands():
            matched_rgba.putalpha(source_img.getchannel("A"))
            
        return matched_rgba


class GameAssetStudio:
    """Facade used by backend/web integration code."""

    def __init__(
        self,
        api_key: str = API_KEY,
        model: str = "flux",
        output_dir: str | Path = OUTPUT_DIR,
        provider: AIImageProvider | None = None,
    ):
        self.gen = ImageGenerator(api_key=api_key, model=model, provider=provider)
        self.proc = AssetPostProcessor()
        self.out = Path(output_dir)
        self.out.mkdir(parents=True, exist_ok=True)

    def generate_background(
        self,
        subject: str,
        size_key: str = "background_hd",
        style: str = "pixel_art",
        time_of_day: str = "day",
        theme: str = "fantasy",
        view_angle: str = "side_scroll",
        seed: int = -1,
        filename: str | None = None,
    ) -> GeneratedAsset:
        self._validate_size_key(size_key, BACKGROUND_SIZE_KEYS, "background")
        width, height = ASSET_SIZES[size_key]
        prompt = PromptOptimizer.build_environment_prompt(subject, theme, style, time_of_day, view_angle)
        result = self.gen.generate_with_metadata(
            prompt,
            width=width,
            height=height,
            seed=seed,
            negative_prompt=PromptOptimizer.get_negative_prompt("background"),
        )
        img = self.proc.cover_to_canvas(result.image, (width, height))

        out_name = self._safe_name(filename or f"bg_{subject}_{size_key}")
        path = self.out / "backgrounds" / f"{out_name}.png"
        self.proc.save(img, path)
        return self._asset_metadata("background", prompt, result, img, path)

    def generate_sprite(
        self,
        subject: str,
        size_key: str = "sprite_medium",
        style: str = "pixel_art",
        view_angle: str = "front",
        transparent_bg: bool = True,
        seed: int = -1,
        filename: str | None = None,
    ) -> GeneratedAsset:
        self._validate_size_key(size_key, SPRITE_SIZE_KEYS, "sprite")
        width, height = ASSET_SIZES[size_key]
        prompt = PromptOptimizer.build_character_prompt(subject, style, view_angle)
        result = self.gen.generate_with_metadata(
            prompt,
            width=max(width, 512),
            height=max(height, 512),
            seed=seed,
            negative_prompt=PromptOptimizer.get_negative_prompt("sprite"),
        )

        img = result.image
        if transparent_bg:
            img = self.proc.remove_background(img)
        img = self.proc.fit_to_canvas(
            img,
            (width, height),
            resample=Image.Resampling.NEAREST if style == "pixel_art" else Image.Resampling.LANCZOS,
            padding=max(2, min(width, height) // 18),
        )
        img = self.proc.mirror_if_left(img, view_angle)
        if style == "pixel_art":
            img = self.proc.normalize_pixel_asset(img, colors=24)
        if style in ("pixel_art", "cartoon", "chibi"):
            img = self.proc.add_alpha_outline(img, radius=1)

        out_name = self._safe_name(filename or f"sprite_{subject}_{size_key}")
        path = self.out / "sprites" / f"{out_name}.png"
        self.proc.save(img, path)
        asset = self._asset_metadata("sprite", prompt, result, img, path)
        if view_angle == "left":
            asset.warnings.append("Generated canonical right-facing sprite and mirrored it to preserve left/right consistency.")
        return asset

    def generate_base_character(
        self,
        subject: str,
        *,
        base_image_path: str | Path | None = None,
        size_key: str = "sprite_medium",
        style: str = "pixel_art",
        view_angle: str = "right",
        seed: int = -1,
        filename: str | None = None,
    ) -> GeneratedAsset:
        """
        Create or normalize the single source character used by views and animations.

        If base_image_path is provided, the user's image becomes the base character.
        Otherwise the provider generates a new base character first.
        """
        self._validate_size_key(size_key, SPRITE_SIZE_KEYS, "base character")
        width, height = ASSET_SIZES[size_key]

        if base_image_path:
            source = Path(base_image_path)
            img = Image.open(source).convert("RGBA")
            img = self.proc.remove_background(img)
            img = self.proc.fit_to_canvas(
                img,
                (width, height),
                resample=Image.Resampling.NEAREST if style == "pixel_art" else Image.Resampling.LANCZOS,
                padding=max(2, min(width, height) // 18),
            )
            if style == "pixel_art":
                img = self.proc.normalize_pixel_asset(img, colors=24)
            if style in ("pixel_art", "cartoon", "chibi"):
                img = self.proc.add_alpha_outline(img, radius=1)

            out_name = self._safe_name(filename or f"base_character_from_{source.stem}_{size_key}")
            path = self.out / "character_packs" / out_name / "base.png"
            self.proc.save(img, path)
            result = ProviderResult(
                image=img,
                provider="user_base_image",
                model="local_base_character_normalizer",
                seed=-1,
                warnings=[f"Using user-provided base character: {source}"],
            )
            return self._asset_metadata("base_character", f"normalize user base character: {source.name}", result, img, path)

        asset = self.generate_sprite(
            subject=subject,
            size_key=size_key,
            style=style,
            view_angle=view_angle,
            transparent_bg=True,
            seed=seed,
            filename=filename or f"base_character_{subject}_{view_angle}",
        )
        asset.asset_type = "base_character"
        base_dir = self.out / "character_packs" / self._safe_name(filename or subject)
        base_path = base_dir / "base.png"
        self.proc.save(Image.open(asset.file_path).convert("RGBA"), base_path)
        asset.file_path = str(base_path)
        return asset

    def generate_character_views_from_base(
        self,
        base_asset: GeneratedAsset | str | Path,
        *,
        frame_size: tuple[int, int] = (128, 128),
        pack_name: str = "character_pack",
    ) -> dict[str, GeneratedAsset]:
        """Create stable front/right/left view files from a base image. Left is mirrored from right."""
        base_path = Path(base_asset.file_path) if isinstance(base_asset, GeneratedAsset) else Path(base_asset)
        img = Image.open(base_path).convert("RGBA")
        right = self.proc.fit_to_canvas(img, frame_size, resample=Image.Resampling.NEAREST, padding=max(2, min(frame_size) // 18))
        left = ImageOps.mirror(right)

        pack_dir = self.out / "character_packs" / self._safe_name(pack_name) / "views"
        assets: dict[str, GeneratedAsset] = {}
        for view, view_img in {"right": right, "left": left}.items():
            path = pack_dir / f"{view}.png"
            self.proc.save(view_img, path)
            result = ProviderResult(
                image=view_img,
                provider="local_character_pack",
                model="mirror_and_normalize",
                seed=-1,
                warnings=["Generated from base character for consistent views."],
            )
            assets[view] = self._asset_metadata(f"character_view_{view}", f"{view} view from base character", result, view_img, path)
        return assets

    def generate_character_pack(
        self,
        subject: str,
        *,
        base_image_path: str | Path | None = None,
        actions: list[str] | None = None,
        frames: int = 6,
        size_key: str = "sprite_medium",
        frame_size: tuple[int, int] = (64, 64),
        style: str = "pixel_art",
        seed: int = -1,
        pack_name: str | None = None,
    ) -> dict[str, Any]:
        """Generate a reusable character pack: base, mirrored views, and action sheets."""
        pack_slug = self._safe_name(pack_name or subject)
        
        base = self.generate_base_character(
            subject,
            base_image_path=base_image_path,
            size_key=size_key,
            style=style,
            view_angle="right",
            seed=seed,
            filename=pack_slug,
        )
        views = self.generate_character_views_from_base(
            base,
            frame_size=ASSET_SIZES[size_key],
            pack_name=pack_slug,
        )
        
        action_names = actions or ["idle", "walk", "attack"]
        animations: dict[str, GeneratedAsset] = {}
        for action in action_names:
            # Generate right animation (default)
            right_anim = self.generate_animation_sheet(
                subject=subject,
                action=action,
                frames=frames,
                frame_size=frame_size,
                style=style,
                seed=seed,
                filename=f"{pack_slug}_{action}_right_{frames}f",
                facing="right",
            )
            animations[f"{action}_right"] = right_anim
            # For backward compatibility
            animations[action] = right_anim

            # Generate left animation by mirroring right frames
            left_anim = self.mirror_animation_sheet(
                right_anim,
                frames=frames,
                frame_size=frame_size,
                filename=f"{pack_slug}_{action}_left_{frames}f",
            )
            animations[f"{action}_left"] = left_anim
            
        pack_dir = self.out / "character_packs" / pack_slug
        manifest = {
            "pack_name": pack_slug,
            "subject": subject,
            "base": base.to_dict(),
            "views": {name: asset.to_dict() for name, asset in views.items()},
            "animations": {name: asset.to_dict() for name, asset in animations.items()},
        }
        pack_dir.mkdir(parents=True, exist_ok=True)
        (pack_dir / "metadata.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        return {"base": base, "views": views, "animations": animations, "manifest_path": str(pack_dir / "metadata.json")}

    def mirror_animation_sheet(
        self,
        base_asset: GeneratedAsset,
        frames: int,
        frame_size: tuple[int, int],
        filename: str,
    ) -> GeneratedAsset:
        """Mirror each frame of an animation sheet horizontally to create the opposite direction sheet."""
        sheet = Image.open(base_asset.file_path).convert("RGBA")
        frame_w, frame_h = frame_size
        
        mirrored_frames = []
        for index in range(frames):
            x = index * frame_w
            frame = sheet.crop((x, 0, x + frame_w, frame_h))
            mirrored_frame = ImageOps.mirror(frame)
            mirrored_frames.append(mirrored_frame)
            
        new_sheet = self.proc.compose_sprite_sheet(mirrored_frames, frame_size)
        path = Path(base_asset.file_path).parent / f"{filename}.png"
        self.proc.save(new_sheet, path)
        
        frame_meta = []
        for index, frame in enumerate(mirrored_frames):
            frame_path = None
            if base_asset.frames and base_asset.frames[index].file_path:
                orig_frame_path = Path(base_asset.frames[index].file_path)
                frame_path = orig_frame_path.parent.parent / filename / f"frame_{index:02d}.png"
                self.proc.save(frame, frame_path)
                
            frame_meta.append(
                FrameMetadata(
                    index=index,
                    x=index * frame_w,
                    y=0,
                    w=frame_w,
                    h=frame_h,
                    file_path=str(frame_path) if frame_path else None,
                )
            )
            
        return GeneratedAsset(
            asset_id=str(uuid.uuid4()),
            asset_type="animation_sheet",
            prompt=f"{base_asset.prompt} (Mirrored left)",
            provider=base_asset.provider,
            model=base_asset.model,
            seed=base_asset.seed,
            width=new_sheet.width,
            height=new_sheet.height,
            format="png",
            file_path=str(path),
            has_alpha=base_asset.has_alpha,
            frames=frame_meta,
            warnings=base_asset.warnings,
        )

    def generate_prop(
        self,
        subject: str,
        item_type: str = "collectible",
        size_key: str = "sprite_medium",
        style: str = "pixel_art",
        view_angle: str = "front",
        seed: int = -1,
        filename: str | None = None,
    ) -> GeneratedAsset:
        """Generate an item/prop sprite (weapon, shield, potion, etc.)."""
        self._validate_size_key(size_key, SPRITE_SIZE_KEYS, "prop")
        width, height = ASSET_SIZES[size_key]
        prompt = PromptOptimizer.build_prop_prompt(subject, item_type, style, view_angle)
        result = self.gen.generate_with_metadata(
            prompt,
            width=max(width, 512),
            height=max(height, 512),
            seed=seed,
            negative_prompt=PromptOptimizer.get_negative_prompt("prop"),
        )

        img = self.proc.remove_background(result.image)
        img = self.proc.fit_to_canvas(
            img,
            (width, height),
            resample=Image.Resampling.NEAREST if style == "pixel_art" else Image.Resampling.LANCZOS,
            padding=max(2, min(width, height) // 16),
        )
        img = self.proc.mirror_if_left(img, view_angle)
        if style == "pixel_art":
            img = self.proc.normalize_pixel_asset(img, colors=20)
        if style in ("pixel_art", "cartoon", "chibi"):
            img = self.proc.add_alpha_outline(img, radius=1)

        out_name = self._safe_name(filename or f"prop_{item_type}_{subject}_{size_key}")
        path = self.out / "props" / f"{out_name}.png"
        self.proc.save(img, path)
        asset = self._asset_metadata("prop", prompt, result, img, path)
        if view_angle == "left":
            asset.warnings.append("Generated canonical right-facing prop and mirrored it to preserve left/right consistency.")
        return asset

    def generate_pixel_art(
        self,
        subject: str,
        size_key: str = "sprite_medium",
        block_size: int = 8,
        colors: int = 32,
        seed: int = -1,
        filename: str | None = None,
    ) -> GeneratedAsset:
        self._validate_size_key(size_key, PIXEL_SIZE_KEYS, "pixel art")
        width, height = ASSET_SIZES[size_key]
        prompt = PromptOptimizer.build_pixel_art_prompt(subject)
        result = self.gen.generate_with_metadata(
            prompt,
            width=max(width, 512),
            height=max(height, 512),
            seed=seed,
            negative_prompt=PromptOptimizer.get_negative_prompt("sprite"),
        )

        img = self.proc.remove_background(result.image)
        img = self.proc.fit_to_canvas(
            img,
            (width, height),
            resample=Image.Resampling.NEAREST,
            padding=max(2, min(width, height) // 16),
        )
        img = self.proc.apply_pixel_art_effect(img, block_size=block_size)
        img = self.proc.reduce_palette(img, colors=colors)
        img = self.proc.add_alpha_outline(img, radius=1)

        out_name = self._safe_name(filename or f"pixel_{subject}_{size_key}")
        path = self.out / "pixel_art" / f"{out_name}.png"
        self.proc.save(img, path)
        return self._asset_metadata("pixel_art", prompt, result, img, path)

    def convert_image_to_pixel_art(
        self,
        image_path: str | Path,
        size_key: str = "sprite_medium",
        block_size: int = 8,
        colors: int = 32,
        filename: str | None = None,
    ) -> GeneratedAsset:
        """Deterministic local image-to-pixel pipeline for uploaded HD assets."""
        self._validate_size_key(size_key, PIXEL_SIZE_KEYS, "pixel art")
        width, height = ASSET_SIZES[size_key]
        source = Path(image_path)
        img = Image.open(source).convert("RGBA")
        img = self.proc.fit_to_canvas(
            img,
            (width, height),
            resample=Image.Resampling.NEAREST,
            padding=max(2, min(width, height) // 16),
        )
        img = self.proc.apply_pixel_art_effect(img, block_size=block_size)
        img = self.proc.reduce_palette(img, colors=colors)
        img = self.proc.add_alpha_outline(img, radius=1)

        out_name = self._safe_name(filename or f"pixel_from_{source.stem}_{size_key}")
        path = self.out / "pixel_art" / f"{out_name}.png"
        self.proc.save(img, path)

        result = ProviderResult(
            image=img,
            provider="local_postprocess",
            model="pillow_pixel_pipeline",
            seed=-1,
        )
        return self._asset_metadata("pixel_art", f"convert image to pixel art: {source.name}", result, img, path)

    def generate_tileset(
        self,
        subject: str,
        tiles: list[str] | None = None,
        columns: int = 4,
        style: str = "pixel_art",
        seed: int = -1,
        slice_tiles: bool = True,
        filename: str | None = None,
        tile_size: tuple[int, int] = (64, 64),
    ) -> GeneratedAsset:
        """Generate a real map tileset by generating each tile individually and stitching them."""
        if tiles is None:
            # Fallback default tiles
            tiles = ["grass", "dirt", "water", "stone", "wood", "sand", "lava", "snow"]
        if len(tiles) == 0:
            raise ValueError("tiles list cannot be empty")
        if columns < 1:
            raise ValueError("columns must be >= 1")
        if tile_size[0] < 16 or tile_size[1] < 16:
            raise ValueError("tile_size must be at least 16x16")

        # Generate each tile individually
        tile_images: list[Image.Image] = []
        frame_meta: list[FrameMetadata] = []
        warnings: list[str] = []
        used_seed = seed
        provider_name = ""
        model = ""

        for idx, tile_name in enumerate(tiles):
            # Build prompt for this tile
            prompt = PromptOptimizer.build_tile_prompt(subject, tile_name, style)
            # Use a higher resolution for generation to preserve details, then downscale
            gen_size = max(tile_size[0] * 2, 256), max(tile_size[1] * 2, 256)
            result = self.gen.generate_with_metadata(
                prompt,
                width=gen_size[0],
                height=gen_size[1],
                seed=seed if seed >= 0 else -1,
                negative_prompt=PromptOptimizer.get_negative_prompt("tile"),
            )
            if idx == 0:
                used_seed = result.seed
                provider_name = result.provider
                model = result.model
            warnings.extend(result.warnings)

            img = result.image.convert("RGBA")
            # Remove background (in case it's not transparent)
            img = self.proc.remove_background(img)
            # Ensure tileable edges
            img = self.proc.make_tileable(img, edge_blend=max(2, min(tile_size) // 8))
            # Downscale to exact tile size using nearest neighbour (for pixel art) or lanczos
            resample = Image.Resampling.NEAREST if style == "pixel_art" else Image.Resampling.LANCZOS
            img = img.resize(tile_size, resample)
            # Normalize palette if pixel art
            if style == "pixel_art":
                img = self.proc.normalize_pixel_asset(img, colors=28)
            # Add outline for game readability
            if style in ("pixel_art", "cartoon", "chibi"):
                img = self.proc.add_alpha_outline(img, radius=1)

            tile_images.append(img)

            # Save individual tile if requested
            tile_path = None
            if slice_tiles:
                out_name = self._safe_name(filename or f"tileset_{subject}_{columns}x{len(tiles)}")
                tile_path = self.out / "tilesets" / out_name / f"{tile_name}_{idx:02d}.png"
                self.proc.save(img, tile_path)
            frame_meta.append(
                FrameMetadata(
                    index=idx,
                    x=(idx % columns) * tile_size[0],
                    y=(idx // columns) * tile_size[1],
                    w=tile_size[0],
                    h=tile_size[1],
                    file_path=str(tile_path) if tile_path else None,
                )
            )

        # Assemble the grid
        sheet = self.proc.compose_tileset(tile_images, tile_size, columns)

        out_name = self._safe_name(filename or f"tileset_{subject}_{columns}x{len(tiles)}")
        path = self.out / "tilesets" / f"{out_name}.png"
        self.proc.save(sheet, path)

        prompt_summary = f"Tileset of {len(tiles)} tiles for {subject}, {columns} columns, {style}"
        return GeneratedAsset(
            asset_id=str(uuid.uuid4()),
            asset_type="tileset",
            prompt=prompt_summary,
            provider=provider_name,
            model=model,
            seed=used_seed,
            width=sheet.width,
            height=sheet.height,
            format="png",
            file_path=str(path),
            has_alpha=True,
            frames=frame_meta,
            warnings=warnings,
        )

    # Backward-compatible aliases
    def generate_tile_sheet(self, *args, **kwargs) -> GeneratedAsset:
        kwargs.pop("tiles", None)  # just in case
        return self.generate_tileset(*args, **kwargs)

    def generate_tile_set(self, *args, **kwargs) -> GeneratedAsset:
        return self.generate_tileset(*args, **kwargs)

    def generate_tilesheet(self, *args, **kwargs) -> GeneratedAsset:
        return self.generate_tileset(*args, **kwargs)

    def generate_animation_sheet(
        self,
        subject: str,
        frames: int = 10,
        style: str = "pixel_art",
        seed: int = -1,
        slice_frames: bool = False,
        filename: str | None = None,
        frame_size: tuple[int, int] = (64, 64),
        action: str = "running",
        facing: str = "right",
    ) -> GeneratedAsset:
        """Generate each animation frame individually, then compose a deterministic horizontal sheet."""
        if frames < 1 or frames > 32:
            raise ValueError("frames must be between 1 and 32")
        if frame_size[0] < 16 or frame_size[1] < 16:
            raise ValueError("frame_size must be at least 16x16")

        generated_frames: list[Image.Image] = []
        warnings: list[str] = []
        provider_name = ""
        model = ""
        used_seed = seed

        # We'll use a higher resolution for generation to keep details, then downscale.
        gen_size = max(frame_size[0] * 2, 256), max(frame_size[1] * 2, 256)

        for idx in range(frames):
            prompt = PromptOptimizer.build_animation_frame_prompt(
                subject, action, idx, frames, style, facing
            )
            # Retry if frame is mostly transparent (quality check)
            for attempt in range(3):
                result = self.gen.generate_with_metadata(
                    prompt,
                    width=gen_size[0],
                    height=gen_size[1],
                    seed=seed if seed >= 0 else -1,
                    negative_prompt=PromptOptimizer.get_negative_prompt("sprite"),
                )
                if idx == 0:
                    used_seed = result.seed
                    provider_name = result.provider
                    model = result.model
                warnings.extend(result.warnings)

                img = result.image.convert("RGBA")
                # Remove background
                img = self.proc.remove_background(img)
                # Check if the image is mostly empty (alpha > 240 average)
                alpha = img.getchannel("A")
                mean_alpha = sum(alpha.getdata()) / (alpha.width * alpha.height)
                if mean_alpha > 240 and attempt < 2:
                    # Too transparent, regenerate with a different seed
                    seed = (seed + 1) if seed >= 0 else -1
                    continue
                break
            else:
                # If we exhausted retries, keep the last one anyway
                pass

            # Normalise the frame
            img = self.proc.fit_to_canvas(
                img,
                frame_size,
                resample=Image.Resampling.NEAREST if style == "pixel_art" else Image.Resampling.LANCZOS,
                padding=max(2, min(frame_size) // 18),
            )
            if style in ("pixel_art", "cartoon", "chibi"):
                img = self.proc.add_alpha_outline(img, radius=1)
            if style == "pixel_art":
                img = self.proc.normalize_pixel_asset(img, colors=24)
            generated_frames.append(img)

        # Compose the sheet
        sheet = self.proc.compose_sprite_sheet(generated_frames, frame_size)
        out_name = self._safe_name(filename or f"spritesheet_{subject}_{action}_{frames}f_{facing}")
        path = self.out / "animations" / f"{out_name}.png"
        self.proc.save(sheet, path)

        frame_meta: list[FrameMetadata] = []
        for index, frame in enumerate(generated_frames):
            frame_path: Path | None = None
            if slice_frames:
                frame_path = self.out / "animations" / out_name / f"frame_{index:02d}.png"
                self.proc.save(frame, frame_path)
            frame_meta.append(
                FrameMetadata(
                    index=index,
                    x=index * frame_size[0],
                    y=0,
                    w=frame_size[0],
                    h=frame_size[1],
                    file_path=str(frame_path) if frame_path else None,
                )
            )

        prompt_summary = f"{subject}, {action}, {frames} frames, {style}, facing {facing}"
        return GeneratedAsset(
            asset_id=str(uuid.uuid4()),
            asset_type="animation_sheet",
            prompt=prompt_summary,
            provider=provider_name,
            model=model,
            seed=used_seed,
            width=sheet.width,
            height=sheet.height,
            format="png",
            file_path=str(path),
            has_alpha=True,
            frames=frame_meta,
            warnings=warnings,
        )

    # Backward‑compatible alias
    def generate_tilesheet(
        self,
        subject: str,
        frames: int = 10,
        style: str = "pixel_art",
        seed: int = -1,
        slice_frames: bool = False,
        filename: str | None = None,
        frame_size: tuple[int, int] = (64, 64),
        action: str = "running",
    ) -> GeneratedAsset:
        return self.generate_animation_sheet(
            subject=subject,
            frames=frames,
            style=style,
            seed=seed,
            slice_frames=slice_frames,
            filename=filename,
            frame_size=frame_size,
            action=action,
            facing="right",   # default
        )

    @staticmethod
    def get_frontend_config() -> dict[str, Any]:
        """Return all available options for frontend dropdowns/selections."""
        return {
            "categories": ASSET_CATEGORIES,
            "view_angles": dict(VIEW_ANGLES),
            "styles": list(PromptOptimizer.STYLE_TAGS.keys()),
            "themes": {k: v.split(",")[0].strip() for k, v in ENVIRONMENT_THEMES.items()},
            "item_types": list(ITEM_TYPES.keys()),
            "sizes": {k: {"width": v[0], "height": v[1]} for k, v in ASSET_SIZES.items()},
            "time_of_day": ["day", "night", "dusk", "dawn"],
        }

    @staticmethod
    def _validate_size_key(size_key: str, allowed: set[str], label: str) -> None:
        if size_key not in allowed:
            raise ValueError(f"Invalid {label} size '{size_key}'. Valid values: {sorted(allowed)}")

    @staticmethod
    def _safe_name(name: str) -> str:
        slug = re.sub(r"[^a-zA-Z0-9_\-]", "_", name.lower()).strip("_")
        return slug[:80] or "asset"

    @staticmethod
    def _asset_metadata(
        asset_type: str,
        prompt: str,
        result: ProviderResult,
        img: Image.Image,
        path: Path,
        frames: list[FrameMetadata] | None = None,
    ) -> GeneratedAsset:
        has_alpha = img.mode == "RGBA" and img.getextrema()[3][0] < 255
        return GeneratedAsset(
            asset_id=str(uuid.uuid4()),
            asset_type=asset_type,
            prompt=prompt,
            provider=result.provider,
            model=result.model,
            seed=result.seed,
            width=img.width,
            height=img.height,
            format="png",
            file_path=str(path),
            has_alpha=has_alpha,
            warnings=result.warnings,
            frames=frames if frames is not None else [],
        )


if __name__ == "__main__":
    studio = GameAssetStudio(
        api_key=os.getenv("POLLINATIONS_API_KEY", ""),
        model="flux",
        output_dir="output",
    )

    print(studio.generate_background("fantasy forest with mushrooms and glowing fireflies", "background_sd", "pixel_art", "night", seed=42).to_dict())
    print(studio.generate_sprite("cute wizard character", "sprite_medium", "pixel_art", "front", True, seed=42).to_dict())
    print(studio.generate_pixel_art("treasure chest", "sprite_small", block_size=4, colors=16, seed=42).to_dict())
    # Now tileset requires a tile list
    print(studio.generate_tileset("forest terrain", tiles=["grass", "dirt", "water", "stone"], columns=2, style="pixel_art", seed=42).to_dict())
    print(studio.generate_animation_sheet("running robot character", frames=10, style="pixel_art", seed=42, slice_frames=True, facing="right").to_dict())