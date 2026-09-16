"""
AI Game Asset Studio - AI embeddable module.

Scope:
- Build prompts for game assets.
- Call an image provider (currently Pollinations).
- Post-process generated images into predictable game-ready outputs.
- Return metadata that a web/backend team can consume.
"""

from __future__ import annotations

import base64
import io
import json
import math
import os
import random
import re
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import quote

import requests
from PIL import Image, ImageOps, UnidentifiedImageError


POLLINATIONS_BASE_URL = "https://gen.pollinations.ai/image"
POLLINATIONS_TEXT_URL = "https://gen.pollinations.ai/v1/chat/completions"
API_KEY = os.getenv("POLLINATIONS_API_KEY", "")
OUTPUT_DIR = Path("output")

DEFAULT_CHARACTER_CAPTION_INSTRUCTION = (
    "Describe the main character in this image for use as an AI image generation "
    "prompt. In one dense sentence (no intro, no markdown), cover: character name if "
    "recognizable, species/body type, hairstyle and color, outfit and colors, key "
    "accessories or props, facial expression, and any distinctive visual traits. "
    "Only describe the character itself - ignore the background, art style, and "
    "image quality."
)


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


# --------------------------------------------------------------------------
# Character Customizer catalog
#
# The Web team's Character Customizer ships a "Form Output" per generation
# request: a small set of part IDs (base/hair/outfit/shoes/accessory/
# expression) plus an action. AI owns turning those IDs into a prompt that
# reliably produces a game-ready asset — this catalog is that mapping, kept
# in one place so new options are a one-line addition, not a prompt rewrite.
# Every *_id below must exist in its catalog; `CharacterFormOutput.validate()`
# enforces that up front instead of silently mis-generating.
# --------------------------------------------------------------------------

CHARACTER_BASE_CATALOG: dict[str, str] = {
    "base_tall_slim": "tall slender human build, long limbs",
    "base_short_stocky": "short stocky human build, broad frame",
    "base_average_athletic": "average height athletic human build",
    "base_short_slim": "short slim human build, petite frame",
}

HAIR_CATALOG: dict[str, str] = {
    "hair_short_black": "short black hair",
    "hair_long_brown": "long straight brown hair",
    "hair_ponytail_blonde": "blonde hair tied in a ponytail",
    "hair_spiky_red": "spiky red hair",
    "hair_bald": "bald head, no hair",
    "hair_buzzcut_grey": "grey buzzcut hair",
}

OUTFIT_CATALOG: dict[str, str] = {
    "outfit_knight_armor": "silver plate knight armor",
    "outfit_casual_hoodie": "casual hoodie and jeans",
    "outfit_mage_robe": "flowing purple mage robe",
    "outfit_ninja_suit": "dark fitted ninja suit",
    "outfit_explorer_vest": "brown explorer vest with utility pockets",
}

SHOES_CATALOG: dict[str, str] = {
    "shoes_boots_brown": "brown leather boots",
    "shoes_sneakers_white": "white sneakers",
    "shoes_sandals": "simple sandals",
    "shoes_armored_greaves": "armored metal greaves",
}

ACCESSORY_CATALOG: dict[str, str] = {
    "accessory_none": "",
    "accessory_sword": "holding a sword",
    "accessory_shield": "carrying a round shield",
    "accessory_backpack": "wearing a small backpack",
    "accessory_hat": "wearing a wide-brimmed hat",
    "accessory_staff": "holding a wooden staff",
}

EXPRESSION_CATALOG: dict[str, str] = {
    "expr_neutral": "neutral calm expression",
    "expr_happy": "happy smiling expression",
    "expr_angry": "angry determined expression",
    "expr_surprised": "surprised wide-eyed expression",
}

# Action catalog doubles as the animation spec for tilesheet generation:
# frame count + per-frame pose hint, matched to the Web team's Idle/Run/
# Attack preview module.
ACTION_CATALOG: dict[str, dict[str, Any]] = {
    "action_idle": {"label": "idle", "frames": 4, "pose": "idle breathing animation"},
    "action_run": {"label": "running", "frames": 8, "pose": "running cycle animation"},
    "action_attack": {"label": "attacking", "frames": 6, "pose": "attack swing animation"},
}


def _validate_catalog_id(value: str, catalog: dict[str, Any], field_name: str) -> None:
    if value not in catalog:
        raise ValueError(
            f"Invalid {field_name} '{value}'. Valid values: {sorted(catalog)}"
        )


@dataclass
class CharacterFormOutput:
    """Mirrors the Web Character Customizer's Form Output contract. This is the
    single required input from Web -> AI: everything the generator needs to
    reproduce the exact combination the user built in the canvas preview."""

    base_id: str
    hair_id: str
    outfit_id: str
    shoes_id: str
    accessory_id: str = "accessory_none"
    expression_id: str = "expr_neutral"
    action: str = "action_idle"
    facing: str = "front"
    size_key: str = "sprite_medium"
    style: str = "pixel_art"
    seed: int = -1

    def validate(self) -> None:
        _validate_catalog_id(self.base_id, CHARACTER_BASE_CATALOG, "base_id")
        _validate_catalog_id(self.hair_id, HAIR_CATALOG, "hair_id")
        _validate_catalog_id(self.outfit_id, OUTFIT_CATALOG, "outfit_id")
        _validate_catalog_id(self.shoes_id, SHOES_CATALOG, "shoes_id")
        _validate_catalog_id(self.accessory_id, ACCESSORY_CATALOG, "accessory_id")
        _validate_catalog_id(self.expression_id, EXPRESSION_CATALOG, "expression_id")
        _validate_catalog_id(self.action, ACTION_CATALOG, "action")
        if self.facing not in {"front", "side", "back", "three-quarter"}:
            raise ValueError(f"Invalid facing '{self.facing}'")

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CharacterFormOutput":
        known = {f for f in cls.__dataclass_fields__}
        filtered = {k: v for k, v in data.items() if k in known}
        missing = {"base_id", "hair_id", "outfit_id", "shoes_id"} - filtered.keys()
        if missing:
            raise ValueError(f"Form Output missing required field(s): {sorted(missing)}")
        return cls(**filtered)


_CUSTOM_SIZE_RE = re.compile(r"^\s*(\d{1,5})\s*[xX]\s*(\d{1,5})\s*$")


# Bottom-to-top paste order for layer compositing. "accessory_none" is skipped
# (no file needed for "no accessory").
CHARACTER_LAYER_ORDER: list[str] = ["base", "shoes", "outfit", "hair", "accessory"]


class AssetCompositor:
    """Ghép layer: loads pre-generated PNG parts from disk and alpha-composites
    them into one character image. No AI call — this is what makes the Web
    real-time preview (and this endpoint's fast path) instant and deterministic.
    Expects files at ``<asset_dir>/<category>/<part_id>.png``, one per catalog ID.

    Each part is generated independently by AI with no shared skeleton/anchor, so
    naive full-canvas overlay produces misaligned results (hair floating in the
    wrong place, shoes detached from legs, etc). `auto_align` mitigates this with
    a bounding-box heuristic: crop each part to its actual content, rescale it to
    a target fraction of the base body's height, and anchor it to a logical
    position (hair -> top, shoes -> bottom, outfit -> upper-center, accessory ->
    center). This is an approximation, not true rigging — expect it to still need
    manual touch-up for production art."""

    # Per-category (target_height_fraction_of_base, max_width_fraction_of_canvas,
    # vertical_anchor, horizontal_offset_fraction_of_base_width) heuristic.
    # Height scales against the base body's own height (how big the part should
    # look relative to this character). The width cap is a safety ceiling against
    # the full canvas, not the body's own (much narrower) silhouette — a
    # diagonally-held sword or a flared robe legitimately extends past the torso.
    _ALIGN_RULES: dict[str, tuple[float, float, str, float]] = {
        "hair": (0.22, 0.55, "top", 0.0),
        "outfit": (0.58, 0.85, "upper", 0.0),
        "shoes": (0.14, 0.55, "bottom", 0.0),
        # A held weapon/item sits at the character's side, not dead-center over
        # the torso — offset it right by 22% of body width so it doesn't paper
        # over the outfit.
        "accessory": (0.42, 0.70, "center", 0.22),
    }

    @staticmethod
    def _alpha_bbox(img: Image.Image) -> tuple[int, int, int, int] | None:
        return img.getchannel("A").getbbox()

    @staticmethod
    def compose_layers(
        asset_dir: str | Path,
        form: "CharacterFormOutput",
        auto_align: bool = True,
    ) -> Image.Image:
        asset_dir = Path(asset_dir)
        canvas_w, canvas_h = resolve_size(form.size_key, SPRITE_SIZE_KEYS, "sprite")
        result = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))

        part_ids = {
            "base": form.base_id,
            "shoes": form.shoes_id,
            "outfit": form.outfit_id,
            "hair": form.hair_id,
            "accessory": form.accessory_id,
        }

        missing: list[str] = []
        base_bbox: tuple[int, int, int, int] | None = None

        for category in CHARACTER_LAYER_ORDER:
            part_id = part_ids[category]
            if category == "accessory" and part_id == "accessory_none":
                continue
            layer_path = asset_dir / category / f"{part_id}.png"
            if not layer_path.exists():
                missing.append(str(layer_path))
                continue

            layer_img = Image.open(layer_path).convert("RGBA")
            if layer_img.size != (canvas_w, canvas_h):
                layer_img = layer_img.resize((canvas_w, canvas_h), Image.Resampling.LANCZOS)

            if category == "base":
                base_bbox = AssetCompositor._alpha_bbox(layer_img)
                result = Image.alpha_composite(result, layer_img)
                continue

            if not auto_align or category not in AssetCompositor._ALIGN_RULES:
                result = Image.alpha_composite(result, layer_img)
                continue

            bbox = AssetCompositor._alpha_bbox(layer_img)
            if bbox is None:
                continue  # fully transparent layer (e.g. hair_bald) — nothing to place

            bx0, by0, bx1, by1 = base_bbox or (0, 0, canvas_w, canvas_h)
            base_h = max(1, by1 - by0)
            base_w = max(1, bx1 - bx0)
            base_cx = (bx0 + bx1) / 2

            lx0, ly0, lx1, ly1 = bbox
            lw, lh = max(1, lx1 - lx0), max(1, ly1 - ly0)
            cropped = layer_img.crop(bbox)

            target_h_frac, max_w_frac, anchor, x_offset_frac = AssetCompositor._ALIGN_RULES[category]
            scale_by_height = (base_h * target_h_frac) / lh
            scale_by_width = (canvas_w * max_w_frac) / lw
            scale = min(scale_by_height, scale_by_width)
            new_w, new_h = max(1, round(lw * scale)), max(1, round(lh * scale))
            resized = cropped.resize((new_w, new_h), Image.Resampling.LANCZOS)

            px = round(base_cx - new_w / 2 + base_w * x_offset_frac)
            if anchor == "top":
                py = by0
            elif anchor == "bottom":
                py = by1 - new_h
            elif anchor == "upper":
                py = by0 + round(base_h * 0.15)
            else:  # "center"
                py = by0 + round((base_h - new_h) / 2)

            layer_canvas = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))
            layer_canvas.paste(resized, (px, py), resized)
            result = Image.alpha_composite(result, layer_canvas)

        if missing:
            raise FileNotFoundError(
                "Missing character asset layer(s), expected at: " + "; ".join(missing)
            )
        return result


def resolve_size(value: str, allowed_keys: set[str], label: str) -> tuple[int, int]:
    """Resolve a size argument that may be either a preset key (e.g. 'background_hd')
    or a literal 'WIDTHxHEIGHT' string (e.g. '800x600', '1024x768')."""
    match = _CUSTOM_SIZE_RE.match(value)
    if match:
        width, height = int(match.group(1)), int(match.group(2))
        if width < 1 or height < 1:
            raise ValueError(f"Invalid custom {label} size '{value}': width/height must be >= 1")
        return (width, height)

    if value not in allowed_keys:
        raise ValueError(
            f"Invalid {label} size '{value}'. Use one of {sorted(allowed_keys)}, "
            f"or a custom size like '800x600'."
        )
    return ASSET_SIZES[value]


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

    def to_web_payload(self) -> dict[str, Any]:
        """Return {'image': <base64 data URI>, 'metadata': {...}} so a web/frontend
        team can slice frames and render a preview directly from one JSON response,
        without needing filesystem access to `file_path`.

        Works for a single static sprite (1 frame, layout 'single'), a multi-frame
        horizontal sheet like `generate_tilesheet` (layout 'horizontal'), and a
        multi-row grid like `generate_tileset` (layout 'grid').
        """
        mime = f"image/{self.format.lower()}" if self.format else "image/png"
        image_bytes = self.path.read_bytes()
        data_uri = f"data:{mime};base64,{base64.b64encode(image_bytes).decode('ascii')}"

        if self.frames:
            total_frames = len(self.frames)
            frame_width = self.frames[0].w
            frame_height = self.frames[0].h
            # Derive the real grid shape from each frame's (x, y) instead of assuming
            # a single row, so this also works for grid layouts like generate_tileset
            # (multiple rows), not just the always-1-row generate_tilesheet output.
            distinct_rows = sorted({f.y for f in self.frames})
            distinct_cols = sorted({f.x for f in self.frames})
            rows = len(distinct_rows)
            columns = len(distinct_cols) if rows <= 1 else math.ceil(total_frames / rows)
            layout_format = "horizontal" if rows <= 1 else "grid"
        else:
            total_frames = 1
            frame_width = self.width
            frame_height = self.height
            layout_format = "single"
            columns = 1
            rows = 1

        return {
            "image": data_uri,
            "metadata": {
                "total_frames": total_frames,
                "layout_format": layout_format,
                "frame_width": frame_width,
                "frame_height": frame_height,
                "columns": columns,
                "rows": rows,
            },
        }

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


@dataclass
class CaptionResult:
    description: str
    provider: str
    model: str
    warnings: list[str] = field(default_factory=list)


class ImageCaptioner(Protocol):
    name: str
    model: str

    def describe(self, image: Image.Image, *, instruction: str) -> CaptionResult:
        ...


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
    def build_character_prompt(
        form: "CharacterFormOutput",
        frame_pose: str | None = None,
    ) -> str:
        """Compose a prompt from a validated Form Output. `frame_pose` overrides the
        action's base pose text for a specific animation frame (see ACTION_CATALOG)."""
        style_tag = PromptOptimizer.STYLE_TAGS.get(form.style, form.style)
        parts = [
            CHARACTER_BASE_CATALOG[form.base_id],
            HAIR_CATALOG[form.hair_id],
            OUTFIT_CATALOG[form.outfit_id],
            SHOES_CATALOG[form.shoes_id],
            ACCESSORY_CATALOG[form.accessory_id],
            EXPRESSION_CATALOG[form.expression_id],
        ]
        pose = frame_pose or ACTION_CATALOG[form.action]["pose"]
        description = ", ".join(p for p in parts if p)
        return (
            f"{description}, {pose}, {form.facing} facing, full body, "
            f"single centered character, isolated, transparent background, "
            f"game sprite, {style_tag}, flat solid colors, no gradients, "
            f"no blur, sharp clean pixel edges, consistent character design, "
            f"clean silhouette, no scenery"
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
            "character": (
                ", background scenery, multiple characters, multiple poses, "
                "gradient shading, dithering noise, jpeg artifacts, soft edges"
            ),
            "isolated_part": (
                ", person, human, character, body, full figure, torso, arms, legs, "
                "hands, face, head, skull, portrait, bust, npc, model wearing it, "
                "worn, wearing, equipped on a character, mannequin with a face, "
                "holding it, wielding it, scene, background story, environment, "
                "multiple objects, other characters, inventory grid, item frame, ui border"
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
        }
        headers: dict[str, str] = {}
        if self.api_key:
            # Current Pollinations API (gen.pollinations.ai) authenticates via
            # Bearer header, not query params. nologo/enhance/private query params
            # were dropped from the current image API (2026-06-10 changelog) so
            # they're no longer sent here.
            headers["Authorization"] = f"Bearer {self.api_key}"

        last_error: Exception | None = None
        for attempt in range(1, self.retries + 1):
            try:
                response = requests.get(url, params=params, headers=headers, timeout=self.timeout)
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


class PollinationsCaptioner:
    """Vision-capable text provider (Pollinations' OpenAI-compatible chat endpoint).
    Turns a reference image into a reusable text description that can be fed back
    into PromptOptimizer/PollinationsProvider to (re)generate a game-ready asset."""

    name = "pollinations"

    def __init__(
        self,
        api_key: str = API_KEY,
        model: str = "openai",
        base_url: str = POLLINATIONS_TEXT_URL,
        timeout: int = 60,
        retries: int = 3,
    ):
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.retries = retries

    @staticmethod
    def _to_data_uri(image: Image.Image) -> str:
        buf = io.BytesIO()
        image.convert("RGB").save(buf, format="JPEG", quality=92)
        encoded = base64.b64encode(buf.getvalue()).decode("ascii")
        return f"data:image/jpeg;base64,{encoded}"

    def describe(self, image: Image.Image, *, instruction: str) -> CaptionResult:
        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": instruction},
                        {"type": "image_url", "image_url": {"url": self._to_data_uri(image)}},
                    ],
                }
            ],
        }
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        last_error: Exception | None = None
        for attempt in range(1, self.retries + 1):
            try:
                response = requests.post(self.base_url, json=payload, headers=headers, timeout=self.timeout)
                if response.status_code == 402:
                    last_error = RuntimeError(
                        "Pollinations returned 402 Payment Required: the API key has no Pollen "
                        "balance for a vision-capable text model. Get a key at "
                        "https://enter.pollinations.ai and set POLLINATIONS_API_KEY=sk_... "
                        "(free tiers still get a small daily Pollen grant; anonymous/no-key "
                        "requests do not)."
                    )
                    break  # config issue, retrying won't help
                response.raise_for_status()
                data = response.json()
                content = data["choices"][0]["message"]["content"]
                if isinstance(content, list):
                    # Some OpenAI-compatible backends return content as a list of parts.
                    content = " ".join(part.get("text", "") for part in content if isinstance(part, dict))
                content = (content or "").strip()
                if not content:
                    raise RuntimeError("Vision provider returned an empty caption")
                return CaptionResult(description=content, provider=self.name, model=self.model)
            except (requests.RequestException, KeyError, IndexError, ValueError, RuntimeError) as exc:
                last_error = exc
                if attempt < self.retries:
                    time.sleep(2 * attempt)

        # Fail soft: caller falls back to filename-derived subject instead of crashing
        # the whole pipeline just because captioning is unavailable.
        return CaptionResult(
            description="",
            provider=self.name,
            model=self.model,
            warnings=[f"Image captioning failed after {self.retries} attempts: {last_error}"],
        )


class ImageGenerator:
    """Backward-compatible wrapper around the selected provider."""

    def __init__(
        self,
        api_key: str = API_KEY,
        model: str = "flux",
        provider: AIImageProvider | None = None,
        timeout: int = 90,
        retries: int = 3,
    ):
        self.provider = provider or PollinationsProvider(
            api_key=api_key, model=model, timeout=timeout, retries=retries
        )

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
        # BOX (area-average) downscale instead of NEAREST: NEAREST point-samples a
        # single source pixel per block, which on a soft AI-generated image tends to
        # grab a stray anti-aliased pixel and produces the "vỡ hạt" (grainy/broken)
        # look. BOX averages every pixel in the block, so each block's color reflects
        # what's actually there before we snap it to a hard pixel grid.
        small = img.resize((small_w, small_h), Image.Resampling.BOX)
        return small.resize((w, h), Image.Resampling.NEAREST)

    @staticmethod
    def reduce_palette(img: Image.Image, colors: int = 32, dither: bool = False) -> Image.Image:
        if colors < 2 or colors > 256:
            raise ValueError("colors must be between 2 and 256")

        img = img.convert("RGBA")
        alpha = img.getchannel("A")
        rgb = img.convert("RGB")
        dither_mode = Image.Dither.FLOYDSTEINBERG if dither else Image.Dither.NONE
        reduced = rgb.quantize(
            colors=colors,
            method=Image.Quantize.MEDIANCUT,
            dither=dither_mode,
        ).convert("RGBA")
        reduced.putalpha(alpha)
        return reduced

    @staticmethod
    def clean_alpha_edges(img: Image.Image, threshold: int = 128) -> Image.Image:
        """Binarize the alpha channel (fully opaque or fully transparent, no
        in-between). Semi-transparent edge pixels left over from background removal
        or resampling read as a grey/broken outline once composited into a game —
        this snaps every pixel to one state or the other for a clean silhouette."""
        img = img.convert("RGBA")
        alpha = img.getchannel("A").point(lambda a: 255 if a >= threshold else 0)
        cleaned = img.copy()
        cleaned.putalpha(alpha)
        return cleaned

    @staticmethod
    def pixelate_clean(
        img: Image.Image,
        block_size: int = 8,
        colors: int = 32,
        alpha_threshold: int = 128,
        sharpen: bool = True,
    ) -> Image.Image:
        """End-to-end 'fix the blur, fix the broken pixels' pipeline, in the order
        that actually matters:

        1. Unsharp-mask the source AI image (it usually arrives a bit soft) so real
           edges survive the downscale instead of being averaged into mush.
        2. Downscale to the pixel grid with BOX averaging (see apply_pixel_art_effect).
        3. Quantize the SMALL image's palette with dithering off (dithering is what
           produces the speckled/broken look — it scatters noise to fake extra
           colors, which is the opposite of what a clean retro palette wants).
        4. Binarize alpha so edges are crisp instead of a grey halo.
        5. Upscale with NEAREST for hard pixel edges.

        Quantizing the small image (step 3) before the final upscale (step 5) is the
        key fix versus the old pipeline, which quantized *after* upscaling and let
        PIL's default dithering run on a full-size image.
        """
        img = img.convert("RGBA")
        if sharpen:
            from PIL import ImageFilter

            rgb = img.convert("RGB").filter(
                ImageFilter.UnsharpMask(radius=2, percent=120, threshold=3)
            )
            img = Image.merge("RGBA", (*rgb.split(), img.getchannel("A")))

        w, h = img.size
        small_w = max(1, w // block_size)
        small_h = max(1, h // block_size)
        small = img.resize((small_w, small_h), Image.Resampling.BOX)
        small = AssetPostProcessor.reduce_palette(small, colors=colors, dither=False)
        small = AssetPostProcessor.clean_alpha_edges(small, threshold=alpha_threshold)
        return small.resize((w, h), Image.Resampling.NEAREST)

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
        captioner: ImageCaptioner | None = None,
        timeout: int = 90,
        retries: int = 3,
    ):
        self.gen = ImageGenerator(api_key=api_key, model=model, provider=provider, timeout=timeout, retries=retries)
        self.proc = AssetPostProcessor()
        self.captioner = captioner or PollinationsCaptioner(api_key=api_key)
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
        width, height = resolve_size(size_key, BACKGROUND_SIZE_KEYS, "background")
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
        width, height = resolve_size(size_key, SPRITE_SIZE_KEYS, "sprite")
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
            img = self.proc.clean_alpha_edges(img)
        img = self.proc.fit_to_canvas(img, (width, height), resample=Image.Resampling.LANCZOS)
        if style == "pixel_art":
            # Route through the same anti-blur/anti-speckle pipeline used by the
            # explicit `pixel` command, so every pixel-art sprite is game-ready
            # (sharp edges, flat palette, clean silhouette) not just pixel_art asset.
            img = self.proc.pixelate_clean(img, block_size=max(2, min(width, height) // 64), colors=48)

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
        width, height = resolve_size(size_key, PIXEL_SIZE_KEYS, "pixel art")
        prompt = PromptOptimizer.build_pixel_art_prompt(subject)
        result = self.gen.generate_with_metadata(
            prompt,
            width=max(width, 512),
            height=max(height, 512),
            seed=seed,
            negative_prompt=PromptOptimizer.get_negative_prompt("sprite"),
        )

        img = self.proc.fit_to_canvas(result.image, (width, height), resample=Image.Resampling.LANCZOS)
        img = self.proc.pixelate_clean(img, block_size=block_size, colors=colors)

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
        width, height = resolve_size(size_key, PIXEL_SIZE_KEYS, "pixel art")
        source = Path(image_path)
        img = Image.open(source).convert("RGBA")
        img = self.proc.fit_to_canvas(img, (width, height), resample=Image.Resampling.LANCZOS)
        img = self.proc.pixelate_clean(img, block_size=block_size, colors=colors)

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

    def describe_reference_image(
        self,
        image_path: str | Path,
        instruction: str | None = None,
    ) -> CaptionResult:
        """Caption an uploaded HD image (e.g. a Luffy render) into a dense text
        description usable as a generation subject/prompt."""
        source = Path(image_path)
        if not source.exists():
            raise FileNotFoundError(f"Reference image not found: {source}")
        img = Image.open(source).convert("RGB")
        return self.captioner.describe(img, instruction=instruction or DEFAULT_CHARACTER_CAPTION_INSTRUCTION)

    def generate_sprite_from_image(
        self,
        image_path: str | Path,
        size_key: str = "sprite_medium",
        style: str = "pixel_art",
        facing: str = "front",
        transparent_bg: bool = True,
        seed: int = -1,
        filename: str | None = None,
        extra_details: str | None = None,
        instruction: str | None = None,
    ) -> GeneratedAsset:
        """Reference-image -> prompt -> sprite pipeline.

        Upload an HD image of a character (e.g. Luffy) and this will:
          1. Auto-caption the character via a vision model (name/outfit/colors/props).
          2. Feed that description into the normal sprite prompt builder.
          3. Generate a brand-new, clean pixel-art sprite of that character, ready to
             drop straight into GameMaker (transparent bg, isolated, single pose).

        This is different from `convert_image_to_pixel_art`, which only downsamples
        the pixels of the original image locally; this method regenerates the
        character from scratch through the image model, so it can fix pose/background/
        style regardless of what the source photo/render looked like.
        """
        source = Path(image_path)
        caption = self.describe_reference_image(source, instruction=instruction)

        subject = caption.description or source.stem.replace("_", " ").replace("-", " ")
        if extra_details:
            subject = f"{subject}, {extra_details}"

        asset = self.generate_sprite(
            subject=subject,
            size_key=size_key,
            style=style,
            facing=facing,
            transparent_bg=transparent_bg,
            seed=seed,
            filename=filename or f"sprite_from_{source.stem}_{size_key}",
        )

        asset.prompt = (
            f"[reference image: {source.name}] auto-caption: {caption.description!r} "
            f"-> sprite prompt: {asset.prompt}"
        )
        if caption.warnings:
            asset.warnings = caption.warnings + asset.warnings
        return asset

    def generate_character(
        self,
        form: CharacterFormOutput | dict[str, Any],
        filename: str | None = None,
        block_size: int | None = None,
        colors: int = 48,
        save_raw: bool = False,
    ) -> GeneratedAsset:
        """Generate a single-pose character sprite from a Web Character Customizer
        Form Output. Validates every part ID against the catalog before spending an
        API call, then routes through the same anti-blur/anti-speckle pixelate_clean
        pipeline as `generate_sprite`/`generate_pixel_art` so output is game-ready.

        `block_size` controls pixel-art granularity: smaller = more detail retained
        (a full-body character with armor/weapon needs finer blocks than an icon).
        Defaults to canvas_size // 64 if not given. Pass `save_raw=True` to also
        save the pre-pixelation image (`<name>_raw.png`) for A/B comparison when
        debugging whether a bad result comes from generation or post-processing.
        """
        if isinstance(form, dict):
            form = CharacterFormOutput.from_dict(form)
        form.validate()

        width, height = resolve_size(form.size_key, SPRITE_SIZE_KEYS, "sprite")
        prompt = PromptOptimizer.build_character_prompt(form)
        result = self.gen.generate_with_metadata(
            prompt,
            width=max(width, 512),
            height=max(height, 512),
            seed=form.seed,
            negative_prompt=PromptOptimizer.get_negative_prompt("character"),
        )

        img = self.proc.remove_background(result.image)
        img = self.proc.clean_alpha_edges(img)
        img = self.proc.fit_to_canvas(img, (width, height), resample=Image.Resampling.LANCZOS)

        out_name = self._safe_name(
            filename or f"char_{form.base_id}_{form.hair_id}_{form.outfit_id}_{form.size_key}"
        )

        if save_raw:
            raw_path = self.out / "sprites" / f"{out_name}_raw.png"
            self.proc.save(img, raw_path)

        if form.style == "pixel_art":
            effective_block = block_size if block_size is not None else max(2, min(width, height) // 64)
            img = self.proc.pixelate_clean(img, block_size=effective_block, colors=colors)

        path = self.out / "sprites" / f"{out_name}.png"
        self.proc.save(img, path)
        return self._asset_metadata("character", prompt, result, img, path)

    def generate_character_animation(
        self,
        form: CharacterFormOutput | dict[str, Any],
        slice_frames: bool = False,
        filename: str | None = None,
        block_size: int | None = None,
        colors: int = 48,
    ) -> GeneratedAsset:
        """Generate the animation sheet for a Form Output's `action` (idle/run/
        attack, per ACTION_CATALOG), keeping the character's parts identical across
        every frame and sharing one base seed for visual consistency."""
        if isinstance(form, dict):
            form = CharacterFormOutput.from_dict(form)
        form.validate()

        action_spec = ACTION_CATALOG[form.action]
        frames = action_spec["frames"]
        frame_size = ASSET_SIZES[form.size_key] if form.size_key in ASSET_SIZES else resolve_size(
            form.size_key, SPRITE_SIZE_KEYS, "sprite"
        )

        generated_frames: list[Image.Image] = []
        warnings: list[str] = []
        provider_name = ""
        model = ""
        base_seed = form.seed if form.seed >= 0 else random.randint(0, 2_147_483_647 - frames)
        used_seed = base_seed

        for index in range(frames):
            frame_pose = f"{action_spec['pose']}, frame {index + 1} of {frames}"
            prompt = PromptOptimizer.build_character_prompt(form, frame_pose=frame_pose)
            result = self.gen.generate_with_metadata(
                prompt,
                width=max(frame_size[0], 512),
                height=max(frame_size[1], 512),
                seed=base_seed + index,
                negative_prompt=PromptOptimizer.get_negative_prompt("character"),
            )
            provider_name = result.provider
            model = result.model
            warnings.extend(result.warnings)

            frame = self.proc.remove_background(result.image)
            frame = self.proc.clean_alpha_edges(frame)
            frame = self.proc.fit_to_canvas(frame, frame_size, resample=Image.Resampling.LANCZOS)
            if form.style == "pixel_art":
                effective_block = block_size if block_size is not None else max(2, min(frame_size) // 64)
                frame = self.proc.pixelate_clean(frame, block_size=effective_block, colors=colors)
            generated_frames.append(frame)

        sheet = self.proc.compose_sprite_sheet(generated_frames, frame_size)
        out_name = self._safe_name(
            filename or f"char_{form.base_id}_{form.outfit_id}_{action_spec['label']}"
        )
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

        prompt_summary = f"character animation: {form.action} ({frames} frames)"
        return GeneratedAsset(
            asset_id=str(uuid.uuid4()),
            asset_type="character_animation",
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

    def compose_character(
        self,
        form: CharacterFormOutput | dict[str, Any],
        asset_dir: str | Path = "character_assets",
        auto_align: bool = True,
    ) -> Image.Image:
        """Ghép layer only — no AI call. Loads the pre-generated base/hair/outfit/
        shoes/accessory PNGs and alpha-composites them per the Form Output. This is
        the server-side equivalent of Web's real-time canvas preview: same asset
        library, same naming convention, deterministic output. Raises
        FileNotFoundError naming exactly which layer file is missing, so gaps in
        the AI-delivered asset library are obvious immediately rather than
        surfacing as a vague generation failure later.

        `auto_align=True` (default) rescales/repositions each part via a bounding-
        box heuristic since independently-generated parts share no skeleton. Pass
        False for raw full-canvas overlay (e.g. once assets are manually pre-
        aligned to the exact same anchor points by an artist)."""
        if isinstance(form, dict):
            form = CharacterFormOutput.from_dict(form)
        form.validate()
        return AssetCompositor.compose_layers(asset_dir, form, auto_align=auto_align)

    def generate_character_animation_from_layers(
        self,
        form: CharacterFormOutput | dict[str, Any],
        asset_dir: str | Path = "character_assets",
        slice_frames: bool = False,
        filename: str | None = None,
        block_size: int | None = None,
        colors: int = 48,
    ) -> GeneratedAsset:
        """The actual 'nhận lựa chọn custom -> ghép layer -> generate animation'
        endpoint flow: compose the real PNG layers (no AI), caption that composited
        look with the vision model, then generate the action's animation frames
        grounded in that caption instead of pure catalog text — so the animation
        actually matches the specific parts the user picked, not just a generic
        text description of the category."""
        if isinstance(form, dict):
            form = CharacterFormOutput.from_dict(form)
        form.validate()

        composited = AssetCompositor.compose_layers(asset_dir, form)
        caption = self.captioner.describe(
            composited.convert("RGB"), instruction=DEFAULT_CHARACTER_CAPTION_INSTRUCTION
        )

        action_spec = ACTION_CATALOG[form.action]
        frames = action_spec["frames"]
        frame_size = resolve_size(form.size_key, SPRITE_SIZE_KEYS, "sprite")

        generated_frames: list[Image.Image] = []
        warnings: list[str] = list(caption.warnings)
        provider_name = ""
        model = ""
        base_seed = form.seed if form.seed >= 0 else random.randint(0, 2_147_483_647 - frames)

        for index in range(frames):
            frame_pose = f"{action_spec['pose']}, frame {index + 1} of {frames}"
            prompt = (
                f"[reference character: {caption.description}] "
                f"{PromptOptimizer.build_character_prompt(form, frame_pose=frame_pose)}"
            )
            result = self.gen.generate_with_metadata(
                prompt,
                width=max(frame_size[0], 512),
                height=max(frame_size[1], 512),
                seed=base_seed + index,
                negative_prompt=PromptOptimizer.get_negative_prompt("character"),
            )
            provider_name = result.provider
            model = result.model
            warnings.extend(result.warnings)

            frame = self.proc.remove_background(result.image)
            frame = self.proc.clean_alpha_edges(frame)
            frame = self.proc.fit_to_canvas(frame, frame_size, resample=Image.Resampling.LANCZOS)
            if form.style == "pixel_art":
                effective_block = block_size if block_size is not None else max(2, min(frame_size) // 64)
                frame = self.proc.pixelate_clean(frame, block_size=effective_block, colors=colors)
            generated_frames.append(frame)

        sheet = self.proc.compose_sprite_sheet(generated_frames, frame_size)
        out_name = self._safe_name(
            filename or f"charlayer_{form.base_id}_{form.outfit_id}_{action_spec['label']}"
        )
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

        return GeneratedAsset(
            asset_id=str(uuid.uuid4()),
            asset_type="character_animation_from_layers",
            prompt=f"layered character animation: {form.action} ({frames} frames); caption: {caption.description[:160]}",
            provider=provider_name,
            model=model,
            seed=base_seed,
            width=sheet.width,
            height=sheet.height,
            format="png",
            file_path=str(path),
            has_alpha=True,
            frames=frame_meta,
            warnings=warnings,
        )

    def generate_character_asset_library(
        self,
        asset_dir: str | Path = "character_assets",
        size_key: str = "sprite_medium",
        overwrite: bool = False,
        categories: list[str] | None = None,
    ) -> dict[str, list[str]]:
        """One-time batch job: generates the base-body + overlay PNG library from
        the AI-Team checklist (3-4 base bodies, 4-6 options per part category) and
        saves them under ``<asset_dir>/<category>/<id>.png`` — the exact layout
        AssetCompositor/Web's canvas expect. Run this once with a real API key to
        produce the first draft of the asset library; AI-isolated overlays (hair/
        outfit/shoes with no body to anchor proportions to) are approximate, so
        review and align each file before handing the library to Web.

        `categories` restricts the run to a subset (e.g. ["hair", "outfit"]) —
        useful for regenerating just the categories that came out badly without
        re-spending API calls on ones that already look right."""
        asset_dir = Path(asset_dir)
        width, height = resolve_size(size_key, SPRITE_SIZE_KEYS, "sprite")
        style_tag = PromptOptimizer.STYLE_TAGS.get("pixel_art", "pixel art")
        generated: dict[str, list[str]] = {}

        def _generate_one(category: str, part_id: str, descriptor: str, extra: str, negative_category: str) -> str:
            out_path = asset_dir / category / f"{part_id}.png"
            if out_path.exists() and not overwrite:
                return str(out_path)

            if part_id == "hair_bald":
                # "Bald" isn't a hairstyle to isolate — there's nothing to draw, so
                # asking the model for one just gets a bust/neck sketched in to fill
                # the frame. Skip generation and ship an empty transparent layer,
                # same semantics as accessory_none.
                blank = Image.new("RGBA", (width, height), (0, 0, 0, 0))
                self.proc.save(blank, out_path)
                return str(out_path)

            prompt = (
                f"{descriptor}, {extra}, centered, transparent background, "
                f"{style_tag}, flat solid colors, no gradients, sharp clean pixel edges"
            )
            result = self.gen.generate_with_metadata(
                prompt,
                width=max(width, 512),
                height=max(height, 512),
                seed=-1,
                negative_prompt=PromptOptimizer.get_negative_prompt(negative_category),
            )
            img = self.proc.remove_background(result.image)
            img = self.proc.clean_alpha_edges(img)
            img = self.proc.fit_to_canvas(img, (width, height), resample=Image.Resampling.LANCZOS)
            block = max(2, min(width, height) // 64)
            img = self.proc.pixelate_clean(img, block_size=block, colors=48)
            self.proc.save(img, out_path)
            return str(out_path)

        # Base bodies keep the "character" negative prompt (they're SUPPOSED to be
        # a person). Every overlay category uses "isolated_part" — a much stronger
        # negative prompt specifically excluding person/body/face/scene — because
        # a first pass with only positive-side "no body" phrasing still rendered
        # full characters/scenes for hair, outfit, and accessory items.
        base_specs = [
            (
                part_id, descriptor,
                "plain grey mannequin base body, neutral T-pose, no clothes, no hair, "
                "blank featureless face, front facing, full body",
                "character",
            )
            for part_id, descriptor in CHARACTER_BASE_CATALOG.items()
        ]
        hair_specs = [
            (
                part_id, descriptor,
                "wig icon as seen in a character creator / avatar customization menu, "
                "hairstyle item icon, no face, no eyes, no nose, no mouth, no skin, "
                "no neck, no shoulders, no clothing, floating hair shape only on "
                "transparent background",
                "isolated_part",
            )
            for part_id, descriptor in HAIR_CATALOG.items()
        ]
        # Per-item override for outfits that kept rendering a full standing figure
        # under the generic "flat lay" framing after 2 rounds of retries — a
        # different photography style (hanging on a rack) for just these stubborn
        # IDs, rather than risking a global prompt change that could regress the
        # outfits already working (vest, armor, robe).
        _outfit_overrides = {
            "outfit_casual_hoodie": (
                "clothing item hanging on a wooden clothes hanger, retail clothing "
                "store photography, empty hoodie and pants on a hanger, no person, "
                "no body, no head, no arms, no legs inside the clothes, not worn"
            ),
            "outfit_ninja_suit": (
                "clothing item hanging on a wooden clothes hanger, retail clothing "
                "store photography, empty ninja suit on a hanger, no person, no body, "
                "no head, no arms, no legs inside the clothes, not worn"
            ),
        }
        outfit_specs = [
            (
                part_id, descriptor,
                _outfit_overrides.get(
                    part_id,
                    "flat lay clothing photography, the garment laid out flat and "
                    "empty, sleeves and pant legs lying flat with nothing inside "
                    "them, RPG inventory equipment icon style, no person, no body, "
                    "no head, no arms, no legs, no hands, not worn, not being worn "
                    "by anyone",
                ),
                "isolated_part",
            )
            for part_id, descriptor in OUTFIT_CATALOG.items()
        ]
        shoes_specs = [
            (
                part_id, descriptor,
                "RPG inventory equipment icon of a pair of shoes, item icon as shown "
                "in a game inventory screen, no feet, no legs, no person",
                "isolated_part",
            )
            for part_id, descriptor in SHOES_CATALOG.items()
        ]
        def _strip_action_verb(text: str) -> str:
            """ACCESSORY_CATALOG descriptors are written for the full-character
            prompt ('wearing a wide-brimmed hat', 'holding a sword') — reused
            verbatim here, that verb fights directly against the 'no person, not
            worn' isolation instruction. Strip it so the asset-library prompt gets
            just the noun phrase ('a wide-brimmed hat')."""
            for prefix in ("wearing ", "holding ", "carrying "):
                if text.startswith(prefix):
                    return text[len(prefix):]
            return text

        accessory_specs = [
            (
                part_id, _strip_action_verb(descriptor),
                "RPG inventory item icon, single loot/equipment icon as shown in a "
                "game inventory screen, the object lying by itself, not held, not worn, "
                "no hands, no person, no character, no scene, no background story",
                "isolated_part",
            )
            for part_id, descriptor in ACCESSORY_CATALOG.items()
            if part_id != "accessory_none"
        ]

        all_specs = {
            "base": base_specs,
            "hair": hair_specs,
            "outfit": outfit_specs,
            "shoes": shoes_specs,
            "accessory": accessory_specs,
        }
        selected = categories if categories is not None else list(all_specs)

        for category in selected:
            if category not in all_specs:
                raise ValueError(f"Unknown category '{category}'. Valid: {sorted(all_specs)}")
            generated[category] = [
                _generate_one(category, part_id, descriptor, extra, negative_category)
                for part_id, descriptor, extra, negative_category in all_specs[category]
            ]

        return generated

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
        # Pick ONE base seed for the whole sheet (once, before the loop) so every frame
        # shares the same visual identity. Each frame then only offsets by +index from
        # that base -> consistent character/style across frames.
        base_seed = seed if seed >= 0 else random.randint(0, 2_147_483_647 - frames)
        used_seed = base_seed

        for index in range(frames):
            frame_seed = base_seed + index
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
            warnings.extend(result.warnings)

            frame = self.proc.remove_background(result.image)
            frame = self.proc.clean_alpha_edges(frame)
            frame = self.proc.fit_to_canvas(frame, frame_size, resample=Image.Resampling.LANCZOS)
            if style == "pixel_art":
                frame = self.proc.pixelate_clean(
                    frame, block_size=max(2, min(frame_size) // 64), colors=48
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

        cell_w, cell_h = resolve_size(cell_key, TILE_SIZE_KEYS, "tile")

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
                img = self.proc.clean_alpha_edges(img)
            img = self.proc.fit_to_canvas(img, (cell_w, cell_h), resample=Image.Resampling.LANCZOS)
            if style == "pixel_art":
                img = self.proc.pixelate_clean(img, block_size=max(2, min(cell_w, cell_h) // 16), colors=32)
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