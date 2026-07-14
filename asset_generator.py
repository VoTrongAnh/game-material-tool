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
import math
import os
import re
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import quote

import requests
from PIL import Image, ImageOps, UnidentifiedImageError


POLLINATIONS_BASE_URL = "https://image.pollinations.ai/prompt"
API_KEY = os.getenv("POLLINATIONS_API_KEY", "")
OUTPUT_DIR = Path("output")


ASSET_SIZES: dict[str, tuple[int, int]] = {
    "background_hd": (1920, 1080),
    "background_4k": (3840, 2160),
    "background_sd": (1280, 720),
    "background_sq": (1080, 1080),
    "sprite_small": (64, 64),
    "sprite_medium": (128, 128),
    "sprite_large": (256, 256),
    "icon": (32, 32),
    "tile_16": (16, 16),
    "tile_24": (24, 24),
    "tile_32": (32, 32),
    "tile_48": (48, 48),
    "tile_64": (64, 64),
}

BACKGROUND_SIZE_KEYS = {"background_hd", "background_4k", "background_sd", "background_sq"}
SPRITE_SIZE_KEYS = {"sprite_small", "sprite_medium", "sprite_large", "icon"}
PIXEL_SIZE_KEYS = SPRITE_SIZE_KEYS | {"background_sq"}
TILE_SIZE_KEYS = {"tile_16", "tile_24", "tile_32", "tile_48", "tile_64"}


# Ready-made tile lists for common GameMaker-style tilesets (grid packed,
# one distinct tile subject per grid cell, transparent background).
TILE_PRESETS: dict[str, list[str]] = {
    "platformer_basic": [
        "grass ground top edge tile",
        "grass ground top-left corner tile",
        "grass ground top-right corner tile",
        "dirt ground fill tile",
        "stone ground fill tile",
        "wooden platform plank tile",
        "wooden bridge plank tile",
        "stone brick wall tile",
        "water surface tile",
        "water fill tile",
        "lava surface tile",
        "lava fill tile",
        "tree trunk tile",
        "tree leaves canopy tile",
        "bush shrub tile",
        "rock boulder tile",
        "wooden crate tile",
        "treasure chest tile",
        "lit torch tile",
        "wooden sign post tile",
        "ladder tile",
        "spike trap tile",
        "gold coin tile",
        "small flower decoration tile",
    ],
    "dungeon": [
        "stone floor tile",
        "cracked stone floor tile",
        "stone wall tile",
        "stone wall corner tile",
        "wooden door tile",
        "iron gate tile",
        "torch on wall tile",
        "stairs down tile",
        "rubble debris tile",
        "wooden barrel tile",
        "treasure chest tile",
        "skull decoration tile",
    ],
    "cave": [
        "cave floor rock tile",
        "cave wall rock tile",
        "cave wall corner tile",
        "stalactite tile",
        "stalagmite tile",
        "underground water pool tile",
        "glowing crystal tile",
        "mushroom decoration tile",
        "mineral ore vein tile",
    ],
}


@dataclass
class FrameMetadata:
    index: int
    x: int
    y: int
    w: int
    h: int
    file_path: str | None = None
    name: str | None = None


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
        "pixel_art": "pixel art, 8-bit, retro game style, crisp hard pixels, no anti-aliasing",
        "cartoon": "2D cartoon, flat colors, thick outlines, bright palette, game asset",
        "realistic": "realistic, detailed textures, high quality, game environment",
        "chibi": "chibi style, cute, rounded shapes, vibrant colors, game sprite",
    }

    NEGATIVE_BASE = (
        "blurry, watermark, text, logo, signature, extra limbs, bad anatomy, "
        "low quality, cropped, deformed, noisy"
    )

    @staticmethod
    def build_background_prompt(
        subject: str,
        style: str = "pixel_art",
        time_of_day: str = "day",
    ) -> str:
        style_tag = PromptOptimizer.STYLE_TAGS.get(style, style)
        return (
            f"{subject}, {time_of_day} lighting, seamless game background, "
            f"side-scrolling environment, no characters, no HUD, {style_tag}, "
            f"wide shot, clean composition"
        )

    @staticmethod
    def build_sprite_prompt(
        subject: str,
        style: str = "pixel_art",
        facing: str = "front",
    ) -> str:
        style_tag = PromptOptimizer.STYLE_TAGS.get(style, style)
        return (
            f"{subject}, {facing} facing, full body, single centered object, "
            f"isolated, transparent background if possible, game sprite, "
            f"{style_tag}, clean silhouette, no scenery"
        )

    @staticmethod
    def build_animation_frame_prompt(
        subject: str,
        action: str,
        frame_index: int,
        frame_count: int,
        style: str = "pixel_art",
    ) -> str:
        style_tag = PromptOptimizer.STYLE_TAGS.get(style, style)
        return (
            f"{subject}, {action} animation frame {frame_index + 1} of {frame_count}, "
            f"single character pose, centered, same scale, isolated, white or transparent background, "
            f"game sprite animation, {style_tag}, clean silhouette"
        )

    @staticmethod
    def build_pixel_art_prompt(subject: str) -> str:
        return (
            f"{subject}, pure pixel art game asset, 8-bit retro, limited color palette, "
            f"hard pixel edges, no gradients, clean silhouette, classic NES/SNES style"
        )

    @staticmethod
    def build_tile_prompt(subject: str, style: str = "pixel_art") -> str:
        style_tag = PromptOptimizer.STYLE_TAGS.get(style, style)
        return (
            f"single {subject}, one isolated game tile asset for a tileset, "
            f"square orthographic view, centered, flat even lighting, no drop shadow, "
            f"no perspective distortion, fills the entire frame edge to edge, "
            f"tileable/seamless edges, transparent background, {style_tag}, "
            f"clean pixel grid, no text, no watermark, no ruler, no grid lines"
        )

    @staticmethod
    def get_negative_prompt(asset_type: str = "general") -> str:
        extras = {
            "background": ", characters, people, HUD, UI elements",
            "sprite": ", background scenery, multiple objects, multiple poses",
            "sprite_sheet": ", merged frames, uneven spacing, different character scale",
            "tile": (
                ", multiple tiles, full tileset, sprite sheet, grid lines, ruler, "
                "perspective, isometric, drop shadow, background scenery, frame border"
            ),
        }
        return PromptOptimizer.NEGATIVE_BASE + extras.get(asset_type, "")


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
    ) -> Image.Image:
        """Keep aspect ratio and center image on a fixed-size transparent canvas."""
        img = img.convert("RGBA")
        fitted = ImageOps.contain(img, target_size, method=resample)
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
    def remove_background(img: Image.Image, threshold: int = 245) -> Image.Image:
        """Remove background. Use rembg if installed; otherwise fall back to near-white removal."""
        img = img.convert("RGBA")
        try:
            from rembg import remove  # type: ignore

            return remove(img).convert("RGBA")
        except Exception:
            return AssetPostProcessor.remove_near_white_background(img, threshold=threshold)

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
    def compose_grid(
        tiles: list[Image.Image],
        cell_size: tuple[int, int],
        *,
        columns: int,
        margin: int = 0,
        spacing: int = 0,
        background: tuple[int, int, int, int] = (0, 0, 0, 0),
    ) -> Image.Image:
        """Pack tiles into a GameMaker/Tiled-style grid: fixed cell size, optional
        margin (border around the whole sheet) and spacing (gutter between cells)."""
        if not tiles:
            raise ValueError("tiles cannot be empty")
        if columns < 1:
            raise ValueError("columns must be >= 1")

        cell_w, cell_h = cell_size
        rows = math.ceil(len(tiles) / columns)
        sheet_w = margin * 2 + columns * cell_w + (columns - 1) * spacing
        sheet_h = margin * 2 + rows * cell_h + (rows - 1) * spacing
        sheet = Image.new("RGBA", (sheet_w, sheet_h), background)

        for index, tile in enumerate(tiles):
            col = index % columns
            row = index // columns
            x = margin + col * (cell_w + spacing)
            y = margin + row * (cell_h + spacing)
            normalized = AssetPostProcessor.fit_to_canvas(
                tile,
                cell_size,
                resample=Image.Resampling.NEAREST,
            )
            sheet.alpha_composite(normalized, (x, y))
        return sheet

    @staticmethod
    def slice_grid(
        img: Image.Image,
        tile_count: int,
        cell_size: tuple[int, int],
        *,
        columns: int,
        margin: int = 0,
        spacing: int = 0,
    ) -> list[Image.Image]:
        """Inverse of compose_grid: cut a packed tileset image back into individual tiles."""
        cell_w, cell_h = cell_size
        tiles = []
        for index in range(tile_count):
            col = index % columns
            row = index // columns
            x = margin + col * (cell_w + spacing)
            y = margin + row * (cell_h + spacing)
            tiles.append(img.crop((x, y, x + cell_w, y + cell_h)))
        return tiles

    @staticmethod
    def slice_sprite_sheet(img: Image.Image, frames: int, frame_size: tuple[int, int]) -> list[Image.Image]:
        frame_w, frame_h = frame_size
        expected_w = frames * frame_w
        if img.size != (expected_w, frame_h):
            raise ValueError(f"Expected sprite sheet {expected_w}x{frame_h}, got {img.size[0]}x{img.size[1]}")

        return [
            img.crop((index * frame_w, 0, (index + 1) * frame_w, frame_h))
            for index in range(frames)
        ]

    @staticmethod
    def save(img: Image.Image, path: Path, fmt: str = "PNG") -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        img.save(path, fmt)


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
        seed: int = -1,
        filename: str | None = None,
    ) -> GeneratedAsset:
        self._validate_size_key(size_key, BACKGROUND_SIZE_KEYS, "background")
        width, height = ASSET_SIZES[size_key]
        prompt = PromptOptimizer.build_background_prompt(subject, style, time_of_day)
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
        facing: str = "front",
        transparent_bg: bool = True,
        seed: int = -1,
        filename: str | None = None,
    ) -> GeneratedAsset:
        self._validate_size_key(size_key, SPRITE_SIZE_KEYS, "sprite")
        width, height = ASSET_SIZES[size_key]
        prompt = PromptOptimizer.build_sprite_prompt(subject, style, facing)
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
        )

        out_name = self._safe_name(filename or f"sprite_{subject}_{size_key}")
        path = self.out / "sprites" / f"{out_name}.png"
        self.proc.save(img, path)
        return self._asset_metadata("sprite", prompt, result, img, path)

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

        img = self.proc.fit_to_canvas(result.image, (width, height), resample=Image.Resampling.NEAREST)
        img = self.proc.apply_pixel_art_effect(img, block_size=block_size)
        img = self.proc.reduce_palette(img, colors=colors)

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
        img = self.proc.fit_to_canvas(img, (width, height), resample=Image.Resampling.NEAREST)
        img = self.proc.apply_pixel_art_effect(img, block_size=block_size)
        img = self.proc.reduce_palette(img, colors=colors)

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
        """Generate each animation frame, normalize it, then compose a deterministic horizontal sheet."""
        if frames < 1 or frames > 32:
            raise ValueError("frames must be between 1 and 32")
        if frame_size[0] < 16 or frame_size[1] < 16:
            raise ValueError("frame_size must be at least 16x16")

        generated_frames: list[Image.Image] = []
        warnings: list[str] = []
        provider_name = ""
        model = ""
        used_seed = seed

        for index in range(frames):
            frame_seed = seed + index if seed >= 0 else -1
            prompt = PromptOptimizer.build_animation_frame_prompt(subject, action, index, frames, style)
            result = self.gen.generate_with_metadata(
                prompt,
                width=max(frame_size[0], 512),
                height=max(frame_size[1], 512),
                seed=frame_seed,
                negative_prompt=PromptOptimizer.get_negative_prompt("sprite_sheet"),
            )
            provider_name = result.provider
            model = result.model
            if index == 0:
                used_seed = result.seed
            warnings.extend(result.warnings)

            frame = self.proc.remove_background(result.image)
            frame = self.proc.fit_to_canvas(
                frame,
                frame_size,
                resample=Image.Resampling.NEAREST if style == "pixel_art" else Image.Resampling.LANCZOS,
            )
            generated_frames.append(frame)

        sheet = self.proc.compose_sprite_sheet(generated_frames, frame_size)
        out_name = self._safe_name(filename or f"spritesheet_{subject}_{action}_{frames}f")
        path = self.out / "tilesheets" / f"{out_name}.png"
        self.proc.save(sheet, path)

        frame_meta: list[FrameMetadata] = []
        for index, frame in enumerate(generated_frames):
            frame_path: Path | None = None
            if slice_frames:
                frame_path = self.out / "tilesheets" / out_name / f"frame_{index:02d}.png"
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

        prompt_summary = f"{subject}, {action}, {frames} frames, {style}"
        return GeneratedAsset(
            asset_id=str(uuid.uuid4()),
            asset_type="sprite_sheet",
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

    def generate_tileset(
        self,
        tiles: list[str] | None = None,
        preset: str | None = None,
        columns: int = 8,
        cell_key: str = "tile_32",
        style: str = "pixel_art",
        seed: int = -1,
        margin: int = 0,
        spacing: int = 1,
        transparent_bg: bool = True,
        slice_tiles: bool = False,
        filename: str | None = None,
    ) -> GeneratedAsset:
        """Generate a grid-packed tileset: one distinct tile per subject, normalized
        to a fixed cell size, composed into a single sheet ready to import as a
        GameMaker/Tiled tileset (fixed tile_width/tile_height/columns/margin/spacing).

        Also writes a `<name>.json` sidecar next to the PNG describing the grid
        layout and the name/index/x/y of every tile, so the sheet can be wired up
        programmatically instead of clicking through each cell by hand.
        """
        if preset and not tiles:
            if preset not in TILE_PRESETS:
                raise ValueError(f"Unknown preset '{preset}'. Valid presets: {sorted(TILE_PRESETS)}")
            tiles = TILE_PRESETS[preset]
        if not tiles:
            raise ValueError("Provide at least one tile subject via `tiles`, or a `preset` name.")
        if columns < 1:
            raise ValueError("columns must be >= 1")

        self._validate_size_key(cell_key, TILE_SIZE_KEYS, "tile")
        cell_w, cell_h = ASSET_SIZES[cell_key]

        generated_tiles: list[Image.Image] = []
        warnings: list[str] = []
        provider_name = ""
        model = ""
        used_seed = seed

        for index, subject in enumerate(tiles):
            tile_seed = seed + index if seed >= 0 else -1
            prompt = PromptOptimizer.build_tile_prompt(subject, style)
            result = self.gen.generate_with_metadata(
                prompt,
                width=max(cell_w, 512),
                height=max(cell_h, 512),
                seed=tile_seed,
                negative_prompt=PromptOptimizer.get_negative_prompt("tile"),
            )
            provider_name = result.provider
            model = result.model
            if index == 0:
                used_seed = result.seed
            warnings.extend(result.warnings)

            img = result.image
            if transparent_bg:
                img = self.proc.remove_background(img)
            img = self.proc.fit_to_canvas(
                img,
                (cell_w, cell_h),
                resample=Image.Resampling.NEAREST if style == "pixel_art" else Image.Resampling.LANCZOS,
            )
            generated_tiles.append(img)

        sheet = self.proc.compose_grid(
            generated_tiles,
            (cell_w, cell_h),
            columns=columns,
            margin=margin,
            spacing=spacing,
        )

        out_name = self._safe_name(filename or f"tileset_{preset or 'custom'}_{cell_key}")
        path = self.out / "tilesets" / f"{out_name}.png"
        self.proc.save(sheet, path)

        rows = math.ceil(len(generated_tiles) / columns)
        tile_meta: list[FrameMetadata] = []
        for index, (subject, tile) in enumerate(zip(tiles, generated_tiles)):
            col = index % columns
            row = index // columns
            x = margin + col * (cell_w + spacing)
            y = margin + row * (cell_h + spacing)

            tile_path: Path | None = None
            if slice_tiles:
                tile_path = self.out / "tilesets" / out_name / f"{index:03d}_{self._safe_name(subject)}.png"
                self.proc.save(tile, tile_path)

            tile_meta.append(
                FrameMetadata(
                    index=index,
                    x=x,
                    y=y,
                    w=cell_w,
                    h=cell_h,
                    file_path=str(tile_path) if tile_path else None,
                    name=subject,
                )
            )

        meta_path = self.out / "tilesets" / f"{out_name}.json"
        tileset_json = {
            "image": str(path),
            "tile_width": cell_w,
            "tile_height": cell_h,
            "columns": columns,
            "rows": rows,
            "margin": margin,
            "spacing": spacing,
            "tile_count": len(tiles),
            "tiles": [asdict(meta) for meta in tile_meta],
        }
        meta_path.parent.mkdir(parents=True, exist_ok=True)
        meta_path.write_text(json.dumps(tileset_json, indent=2, ensure_ascii=False), encoding="utf-8")

        prompt_summary = f"tileset ({preset or 'custom'}): {', '.join(tiles)} [{style}]"
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
            frames=tile_meta,
            warnings=warnings,
        )

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
    print(studio.generate_tilesheet("running robot character", frames=10, style="pixel_art", seed=42, slice_frames=True).to_dict())
    print(studio.generate_tileset(preset="platformer_basic", columns=8, cell_key="tile_32", style="pixel_art", seed=42, slice_tiles=True).to_dict())