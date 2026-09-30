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


def _load_dotenv_if_present() -> None:
    for env_path in (Path(".env"), Path(__file__).resolve().parent / ".env"):
        if env_path.is_file():
            try:
                for raw_line in env_path.read_text(encoding="utf-8").splitlines():
                    line = raw_line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    k, v = line.split("=", 1)
                    k = k.strip()
                    v = v.strip().strip('"').strip("'")
                    if k and k not in os.environ:
                        os.environ[k] = v
            except OSError:
                pass


_load_dotenv_if_present()

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
    "action_idle": {
        "label": "idle",
        "frames": 4,
        "pose": "idle breathing animation",
        "frame_poses": [
            "upright neutral idle stance, arms relaxed at sides, balanced posture",
            "idle breathing inhale pose, chest slightly raised, alert expression",
            "upright neutral idle stance, weapon or hands steady, clean silhouette",
            "idle breathing exhale pose, knees slightly softened, relaxed shoulders",
        ],
    },
    "action_run": {
        "label": "running",
        "frames": 8,
        "pose": "running cycle animation",
        "frame_poses": [
            "run cycle contact pose, left leg extended forward, right leg back, right arm forward",
            "run cycle down pose, front left knee bent absorbing impact, torso leaning slightly forward",
            "run cycle passing pose, legs crossing directly under torso, arms close to waist",
            "run cycle push-off pose, left leg pushing off behind, right knee driving high forward",
            "run cycle contact pose, right leg extended forward, left leg back, left arm forward",
            "run cycle down pose, front right knee bent absorbing impact, torso leaning slightly forward",
            "run cycle passing pose, legs crossing directly under torso, balanced mid-stride",
            "run cycle push-off pose, right leg pushing off behind, left knee driving high forward",
        ],
    },
    "action_attack": {
        "label": "attacking",
        "frames": 6,
        "pose": "attack swing animation",
        "frame_poses": [
            "combat ready guard stance, weapon poised at side",
            "attack wind-up pose, drawing weapon back over shoulder to strike",
            "fast forward swing motion, torso rotating into the attack",
            "full extension attack impact pose, lunging forward with weapon extended",
            "attack follow-through pose, weapon at end of swing arc, wide stance",
            "recovery pose, returning smoothly to combat guard stance",
        ],
    },
}

# Explicit per-frame pose sequences for generic `generate_tilesheet` actions so
# AI models draw distinct keyframe silhouettes instead of repeating one pose.
GENERIC_ACTION_FRAME_POSES: dict[str, list[str]] = {
    "idle": ACTION_CATALOG["action_idle"]["frame_poses"],
    "run": ACTION_CATALOG["action_run"]["frame_poses"],
    "running": ACTION_CATALOG["action_run"]["frame_poses"],
    "walk": [
        "walk cycle contact pose, left heel touching ground forward, right foot back, opposite arm swing",
        "walk cycle recoil pose, weight shifting onto front left leg, knees slightly bent",
        "walk cycle passing pose, right leg lifting and passing beside standing left leg",
        "walk cycle high-point pose, body upright at peak height, right leg reaching forward",
        "walk cycle contact pose, right heel touching ground forward, left foot back, opposite arm swing",
        "walk cycle recoil pose, weight shifting onto front right leg, knees slightly bent",
        "walk cycle passing pose, left leg lifting and passing beside standing right leg",
        "walk cycle high-point pose, body upright at peak height, left leg reaching forward",
    ],
    "walking": [
        "walk cycle contact pose, left heel touching ground forward, right foot back, opposite arm swing",
        "walk cycle recoil pose, weight shifting onto front left leg, knees slightly bent",
        "walk cycle passing pose, right leg lifting and passing beside standing left leg",
        "walk cycle high-point pose, body upright at peak height, right leg reaching forward",
        "walk cycle contact pose, right heel touching ground forward, left foot back, opposite arm swing",
        "walk cycle recoil pose, weight shifting onto front right leg, knees slightly bent",
        "walk cycle passing pose, left leg lifting and passing beside standing right leg",
        "walk cycle high-point pose, body upright at peak height, left leg reaching forward",
    ],
    "attack": ACTION_CATALOG["action_attack"]["frame_poses"],
    "attacking": ACTION_CATALOG["action_attack"]["frame_poses"],
    "jump": [
        "jump crouch preparation pose, knees bent low, arms swung back",
        "jump launch upward pose, legs fully extended pushing off ground, arms reaching up",
        "mid-air apex pose, knees tucked slightly in flight, balanced airborne silhouette",
        "landing impact absorption pose, knees bent on touchdown, arms out for balance",
    ],
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
    _ALIGN_RULES: dict[str, tuple[float, float, str, float]] = {
        "hair": (0.24, 0.55, "top", 0.0),
        "outfit": (0.56, 0.82, "upper", 0.0),
        "shoes": (0.15, 0.52, "bottom", 0.0),
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
        "low quality, cropped, deformed, noisy, checkerboard pattern, transparency grid"
    )

    # Keywords that identify standalone props/decor tiles (which need transparent
    # backgrounds) versus full-bleed terrain/floor/wall/liquid tiles (which must
    # fill the entire square cell edge-to-edge for Tiled/GameMaker map painting).
    _PROP_TILE_KEYWORDS = (
        "tree", "canopy", "bush", "shrub", "rock boulder", "boulder", "crate",
        "chest", "torch", "sign", "ladder", "spike", "coin", "flower", "door",
        "gate", "stairs", "rubble", "barrel", "skull", "stalactite", "stalagmite",
        "crystal", "mushroom", "pool", "vein",
    )
    _TERRAIN_TILE_KEYWORDS = (
        "ground", "dirt", "grass", "stone", "wall", "floor", "water", "lava",
        "brick", "plank", "cave floor", "cave wall", "fill",
    )

    @staticmethod
    def is_seamless_terrain_tile(subject: str) -> bool:
        lower = subject.lower()
        if any(k in lower for k in PromptOptimizer._PROP_TILE_KEYWORDS):
            return False
        return any(k in lower for k in PromptOptimizer._TERRAIN_TILE_KEYWORDS)

    @staticmethod
    def build_background_prompt(
        subject: str,
        style: str = "pixel_art",
        time_of_day: str = "day",
        view_angle: str = "side_scroll",
    ) -> str:
        style_tag = PromptOptimizer.STYLE_TAGS.get(style, style)
        view_specs = {
            "side_scroll": (
                "2D side-scrolling platformer game background, flat horizontal walkable "
                "ground floor along the bottom edge, layered parallax background scenery, "
                "orthographic 2D side view"
            ),
            "top_down": (
                "90-degree overhead bird's-eye top-down 2D RPG game map background, "
                "flat playable ground surface, orthographic overhead projection"
            ),
            "front": (
                "2D front-facing game stage background, clear flat foreground floor for "
                "characters to stand on, balanced stage composition"
            ),
        }
        view_clause = view_specs.get(view_angle, view_specs["side_scroll"])
        return (
            f"{subject}, {time_of_day} lighting, {view_clause}, "
            f"no characters, no HUD, {style_tag}, wide shot, clean composition"
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
            f"isolated on solid white background, no drop shadow, game sprite, "
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
        action_key = action.strip().lower()
        pose_list = GENERIC_ACTION_FRAME_POSES.get(action_key)
        if pose_list:
            pose_desc = pose_list[frame_index % len(pose_list)]
        else:
            pose_desc = f"{action} animation frame {frame_index + 1} of {frame_count}"

        return (
            f"{subject}, {pose_desc}, full body, single character pose, centered, "
            f"same scale, isolated on solid white background, no shadow, "
            f"game sprite animation, {style_tag}, clean silhouette"
        )

    @staticmethod
    def build_key_pose_prompt(
        subject: str,
        pose: str,
        style: str = "pixel_art",
    ) -> str:
        style_tag = PromptOptimizer.STYLE_TAGS.get(style, style)
        pose_descriptions = {
            "idle": "upright neutral idle stance, balanced posture, ready expression",
            "walk_contact": "walking stride pose, left foot forward, right foot back, arms swinging",
            "walk_passing": "walking mid-step passing pose, one knee lifted passing the standing leg",
            "attack_windup": "combat wind-up pose, drawing weapon or fist back to prepare a strike",
            "attack_impact": "dynamic forward attack strike pose, lunging forward at full extension",
            "jump": "mid-air jump pose, knees tucked upward, dynamic airborne silhouette",
            "hurt": "hit recoil hurt pose, leaning back in shock, defensive posture",
            "death": "defeated fallen pose lying flat on the ground",
        }
        pose_text = pose_descriptions.get(pose, f"{pose} pose")
        return (
            f"single solitary {subject}, {pose_text}, one character only, full body, centered, "
            f"isolated on solid white background, "
            f"no shadow, game sprite, {style_tag}, clean silhouette"
        )

    @staticmethod
    def build_pixel_art_prompt(subject: str) -> str:
        return (
            f"single {subject}, pure pixel art game asset, 8-bit retro, "
            f"centered, full object visible, isolated on solid white background, "
            f"limited color palette, hard pixel edges, no gradients, clean silhouette, classic NES style"
        )

    @staticmethod
    def build_tile_prompt(subject: str, style: str = "pixel_art") -> str:
        style_tag = PromptOptimizer.STYLE_TAGS.get(style, style)
        if PromptOptimizer.is_seamless_terrain_tile(subject):
            return (
                f"seamless repeatable 2D game tile texture of {subject}, "
                f"fills the entire square frame edge to edge, "
                f"flat orthographic view, even lighting, tileable edges, "
                f"no border, no background margin, {style_tag}, clean pixel grid"
            )
        return (
            f"single {subject}, isolated game tile prop for a tileset, "
            f"square orthographic view, centered on solid white background, "
            f"flat even lighting, no drop shadow, {style_tag}, "
            f"clean pixel grid, no text, no grid lines"
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
            f"single centered character, isolated on solid white background, "
            f"game sprite, {style_tag}, flat solid colors, no gradients, "
            f"no blur, sharp clean pixel edges, consistent character design, "
            f"clean silhouette, no scenery"
        )

    @staticmethod
    def get_negative_prompt(asset_type: str = "general") -> str:
        extras = {
            "background": ", characters, people, player sprite, HUD, UI elements, text overlay",
            "sprite": ", background scenery, ground shadow, drop shadow, multiple objects, multiple poses, frame border",
            "sprite_sheet": ", background scenery, ground shadow, merged characters, multiple characters in one frame, cropped feet",
            "tile": (
                ", multiple tiles, full tileset grid, grid lines, ruler, "
                "3D perspective, isometric, drop shadow, frame border"
            ),
            "character": (
                ", background scenery, ground shadow, multiple characters, multiple poses, "
                "gradient shading, dithering noise, jpeg artifacts, soft blurry edges, cropped feet"
            ),
            "isolated_part": (
                ", background scenery, inventory grid, item frame, ui border, "
                "drop shadow, multiple items"
            ),
        }
        return PromptOptimizer.NEGATIVE_BASE + extras.get(asset_type, "")


class PollinationsProvider:
    """Pollinations image provider adapter."""

    name = "pollinations"
    recommended_delay = 2.0
    _last_free_call_ts: float = 0.0

    def __init__(
        self,
        api_key: str = API_KEY,
        model: str = "flux",
        base_url: str = POLLINATIONS_BASE_URL,
        timeout: int = 90,
        retries: int = 5,
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
        use_free_endpoint = not bool(self.api_key) and "gen.pollinations.ai" in self.base_url
        active_base = "https://image.pollinations.ai/prompt" if use_free_endpoint else self.base_url

        full_prompt = prompt
        if negative_prompt and not use_free_endpoint:
            full_prompt = f"{prompt}. Avoid: {negative_prompt}"

        encoded_prompt = quote(full_prompt, safe="")

        params: dict[str, Any] = {
            "width": width,
            "height": height,
            "seed": actual_seed,
        }
        if not use_free_endpoint:
            params["model"] = self.model
            params["private"] = str(self.private).lower()
            params["enhance"] = str(self.enhance).lower()
            params["nologo"] = str(self.nologo).lower()

        headers: dict[str, str] = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        last_error: Exception | None = None
        for attempt in range(1, self.retries + 1):
            try:
                if use_free_endpoint:
                    elapsed = time.time() - PollinationsProvider._last_free_call_ts
                    if elapsed < 16.0:
                        time.sleep(16.0 - elapsed)
                    PollinationsProvider._last_free_call_ts = time.time()

                url = f"{active_base}/{encoded_prompt}"
                response = requests.get(url, params=params, headers=headers, timeout=self.timeout)
                if response.status_code in (401, 403) and not use_free_endpoint:
                    active_base = "https://image.pollinations.ai/prompt"
                    use_free_endpoint = True
                    encoded_prompt = quote(prompt, safe="")
                    params = {"width": width, "height": height, "seed": actual_seed}
                    url = f"{active_base}/{encoded_prompt}"
                    PollinationsProvider._last_free_call_ts = time.time()
                    response = requests.get(url, params=params, timeout=self.timeout)

                if response.status_code in (402, 429, 500, 502, 503, 504):
                    last_error = RuntimeError(f"HTTP {response.status_code}: {response.text[:160]}")
                    retry_after = response.headers.get("Retry-After")
                    default_wait = 15 if use_free_endpoint else (6 * attempt)
                    try:
                        wait = int(retry_after) if retry_after else default_wait
                    except ValueError:
                        wait = default_wait
                    time.sleep(wait + random.uniform(1.0, 2.5))
                    continue

                response.raise_for_status()

                content_type = response.headers.get("content-type", "")
                if "image" not in content_type.lower():
                    preview = response.text[:200]
                    raise RuntimeError(f"Provider did not return an image. Content-Type={content_type}. Body={preview!r}")

                image = Image.open(io.BytesIO(response.content)).convert("RGBA")
                warnings: list[str] = []
                if use_free_endpoint and image.width >= 256 and image.height >= 256:
                    # Only strip the free-tier bottom-right watermark region when the
                    # image is an isolated sprite on a solid near-white background.
                    c_tl = image.getpixel((4, 4))[:3]
                    c_tr = image.getpixel((image.width - 5, 4))[:3]
                    c_bl = image.getpixel((4, image.height - 5))[:3]
                    if all(min(c) >= 230 for c in (c_tl, c_tr, c_bl)):
                        from PIL import ImageDraw

                        draw = ImageDraw.Draw(image)
                        wm_w = min(200, image.width // 2)
                        wm_h = min(46, image.height // 6)
                        draw.rectangle(
                            [image.width - wm_w, image.height - wm_h, image.width, image.height],
                            fill=image.getpixel((4, 4)),
                        )

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
                    content = " ".join(part.get("text", "") for part in content if isinstance(part, dict))
                content = (content or "").strip()
                if not content:
                    raise RuntimeError("Vision provider returned an empty caption")
                return CaptionResult(description=content, provider=self.name, model=self.model)
            except (requests.RequestException, KeyError, IndexError, ValueError, RuntimeError) as exc:
                last_error = exc
                if attempt < self.retries:
                    time.sleep(2 * attempt)

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
        retries: int = 5,
    ):
        self.provider = provider or PollinationsProvider(
            api_key=api_key, model=model, timeout=timeout, retries=retries
        )

    @property
    def recommended_delay(self) -> float:
        return getattr(self.provider, "recommended_delay", 0.0)

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

    _rembg_session: Any = None
    _rembg_unavailable: bool = False

    @staticmethod
    def _zero_transparent_rgb(img: Image.Image) -> Image.Image:
        """Zero out RGB values on fully transparent pixels (alpha == 0) so hidden
        white background pixels (255, 255, 255, 0) never bleed white/grey halos into
        adjacent character edges during BOX or LANCZOS downscaling."""
        img = img.convert("RGBA")
        r, g, b, a = img.split()
        mask = a.point(lambda v: 255 if v > 0 else 0)
        zero = Image.new("L", img.size, 0)
        return Image.merge(
            "RGBA",
            (
                Image.composite(r, zero, mask),
                Image.composite(g, zero, mask),
                Image.composite(b, zero, mask),
                a,
            ),
        )

    @staticmethod
    def fit_to_canvas(
        img: Image.Image,
        target_size: tuple[int, int],
        *,
        resample: Image.Resampling = Image.Resampling.LANCZOS,
        background: tuple[int, int, int, int] = (0, 0, 0, 0),
    ) -> Image.Image:
        """Keep aspect ratio and center image on a fixed-size transparent canvas."""
        img = AssetPostProcessor._zero_transparent_rgb(img)
        fitted = ImageOps.contain(img, target_size, method=resample)
        canvas = Image.new("RGBA", target_size, background)
        x = (target_size[0] - fitted.width) // 2
        y = (target_size[1] - fitted.height) // 2
        canvas.alpha_composite(fitted, (x, y))
        return canvas

    @staticmethod
    def trim_and_fit_sprite(
        img: Image.Image,
        target_size: tuple[int, int],
        *,
        fill_ratio: float = 0.90,
        anchor: str = "bottom",
        resample: Image.Resampling = Image.Resampling.LANCZOS,
    ) -> Image.Image:
        """Auto-crop transparent margins around a sprite so its hitbox is tight and
        consistent, scale it to `fill_ratio` of the target canvas, and align it:
        - `anchor='bottom'`: place feet right on a consistent ground baseline near
          the bottom edge (essential for platformer/top-down characters so they don't
          float above the ground or jitter between animation frames).
        - `anchor='center'`: center both axes (ideal for items, coins, chests, icons).
        """
        img = AssetPostProcessor._zero_transparent_rgb(img)
        bbox = img.getchannel("A").getbbox()
        if not bbox:
            return Image.new("RGBA", target_size, (0, 0, 0, 0))

        # If the image is completely opaque edge-to-edge (e.g. synthetic test images),
        # fall back to standard fit_to_canvas.
        if bbox == (0, 0, img.width, img.height) and img.getextrema()[3][0] == 255:
            return AssetPostProcessor.fit_to_canvas(img, target_size, resample=resample)

        cropped = img.crop(bbox)
        cw, ch = target_size
        usable_w = max(1, round(cw * fill_ratio))
        usable_h = max(1, round(ch * fill_ratio))
        fitted = ImageOps.contain(cropped, (usable_w, usable_h), method=resample)

        canvas = Image.new("RGBA", target_size, (0, 0, 0, 0))
        x = (cw - fitted.width) // 2
        if anchor == "bottom":
            bottom_pad = max(1, round(ch * 0.03)) if ch >= 32 else 0
            y = max(0, ch - bottom_pad - fitted.height)
        else:
            y = (ch - fitted.height) // 2

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

        img = AssetPostProcessor._zero_transparent_rgb(img)
        if block_size == 1:
            return img
        w, h = img.size
        small_w = max(1, w // block_size)
        small_h = max(1, h // block_size)
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
        return AssetPostProcessor._zero_transparent_rgb(reduced)

    @staticmethod
    def unify_frames_palette(frames: list[Image.Image], colors: int = 48) -> list[Image.Image]:
        """Quantize all frames in an animation sheet against a single shared master
        palette so character colors never flicker from frame to frame."""
        if not frames or len(frames) <= 1:
            return frames
        colors = max(2, min(256, colors))
        fw, fh = frames[0].size
        strip = Image.new("RGB", (fw * len(frames), fh), (0, 0, 0))
        for idx, frame in enumerate(frames):
            strip.paste(frame.convert("RGB"), (idx * fw, 0))

        master_palette_img = strip.quantize(
            colors=colors,
            method=Image.Quantize.MEDIANCUT,
            dither=Image.Dither.NONE,
        )
        unified: list[Image.Image] = []
        for frame in frames:
            rgba = frame.convert("RGBA")
            alpha = rgba.getchannel("A")
            quantized_rgb = rgba.convert("RGB").quantize(
                palette=master_palette_img,
                dither=Image.Dither.NONE,
            ).convert("RGBA")
            quantized_rgb.putalpha(alpha)
            unified.append(AssetPostProcessor._zero_transparent_rgb(quantized_rgb))
        return unified

    @staticmethod
    def clean_alpha_edges(img: Image.Image, threshold: int = 128) -> Image.Image:
        """Binarize the alpha channel (fully opaque or fully transparent, no
        in-between) and zero RGB on transparent pixels to prevent white edge halos."""
        img = img.convert("RGBA")
        alpha = img.getchannel("A").point(lambda a: 255 if a >= threshold else 0)
        cleaned = img.copy()
        cleaned.putalpha(alpha)
        return AssetPostProcessor._zero_transparent_rgb(cleaned)

    @staticmethod
    def defringe_alpha(img: Image.Image, white_cutoff: int = 232) -> Image.Image:
        """Remove 1-pixel bright/white background fringe clinging to the outer edge
        of a cutout sprite before downscaling."""
        img = AssetPostProcessor.clean_alpha_edges(img, threshold=140)
        w, h = img.size
        if w < 64 or h < 64:
            return img
        px = img.load()
        if px is None:
            return img

        to_clear: list[tuple[int, int]] = []
        for y in range(1, h - 1):
            for x in range(1, w - 1):
                r, g, b, a = px[x, y]
                if a == 0:
                    continue
                # Check if on silhouette boundary (at least one transparent neighbor)
                if (
                    px[x - 1, y][3] == 0
                    or px[x + 1, y][3] == 0
                    or px[x, y - 1][3] == 0
                    or px[x, y + 1][3] == 0
                ):
                    if r >= white_cutoff and g >= white_cutoff and b >= white_cutoff:
                        to_clear.append((x, y))

        for x, y in to_clear:
            px[x, y] = (0, 0, 0, 0)
        return img

    @staticmethod
    def pixelate_clean(
        img: Image.Image,
        block_size: int = 8,
        colors: int = 32,
        alpha_threshold: int = 128,
        sharpen: bool = True,
    ) -> Image.Image:
        """End-to-end 'fix the blur, fix the broken pixels' pipeline:
        1. Zero transparent RGB so background never bleeds into sprite edges.
        2. Unsharp-mask the source image so edges survive downscaling.
        3. Downscale to the pixel grid with BOX averaging (if block_size > 1).
        4. Quantize the palette with dithering off.
        5. Binarize alpha so edges are crisp instead of a grey halo.
        6. Upscale with NEAREST for hard pixel edges.
        """
        if block_size < 1:
            raise ValueError("block_size must be >= 1")

        img = AssetPostProcessor._zero_transparent_rgb(img)
        if sharpen:
            from PIL import ImageFilter

            rgb = img.convert("RGB").filter(
                ImageFilter.UnsharpMask(radius=1.8, percent=130, threshold=3)
            )
            img = Image.merge("RGBA", (*rgb.split(), img.getchannel("A")))

        w, h = img.size
        if block_size > 1:
            small_w = max(1, w // block_size)
            small_h = max(1, h // block_size)
            small = img.resize((small_w, small_h), Image.Resampling.BOX)
            small = AssetPostProcessor.clean_alpha_edges(small, threshold=alpha_threshold)
            small = AssetPostProcessor.reduce_palette(small, colors=colors, dither=False)
            return small.resize((w, h), Image.Resampling.NEAREST)

        cleaned = AssetPostProcessor.clean_alpha_edges(img, threshold=alpha_threshold)
        return AssetPostProcessor.reduce_palette(cleaned, colors=colors, dither=False)

    @staticmethod
    def remove_background(img: Image.Image, threshold: int = 240) -> Image.Image:
        """Remove background using a cached rembg session if available, followed by
        border flood-fill and edge defringing to strip any remaining white corners."""
        img = img.convert("RGBA")
        if not AssetPostProcessor._rembg_unavailable:
            try:
                from rembg import new_session, remove  # type: ignore

                if AssetPostProcessor._rembg_session is None:
                    AssetPostProcessor._rembg_session = new_session("u2net")
                cutout = remove(img, session=AssetPostProcessor._rembg_session).convert("RGBA")
                return AssetPostProcessor.defringe_alpha(cutout)
            except Exception:
                AssetPostProcessor._rembg_unavailable = True

        cutout = AssetPostProcessor.remove_near_white_background(img, threshold=threshold)
        return AssetPostProcessor.defringe_alpha(cutout)

    @staticmethod
    def remove_near_white_background(img: Image.Image, threshold: int = 240) -> Image.Image:
        """Border-connected flood-fill removal of near-white / neutral light backgrounds.
        Unlike global thresholding, this only removes light background pixels reachable
        from the outer border of the image — preserving white eyes, white beards, white
        clothing, and bright weapon highlights inside the character silhouette."""
        from collections import deque

        img = img.convert("RGBA")
        w, h = img.size
        px = img.load()
        if px is None or w == 0 or h == 0:
            return img

        # Effective threshold allows slightly off-white AI backgrounds (#DCDCDC..#FFFFFF)
        eff_threshold = min(threshold, 225)

        def _is_bg_color(r: int, g: int, b: int, a: int) -> bool:
            if a == 0:
                return True
            if r >= threshold and g >= threshold and b >= threshold:
                return True
            # Also catch neutral light grey/off-white backgrounds near the edges
            min_c = min(r, g, b)
            max_c = max(r, g, b)
            return min_c >= eff_threshold and (max_c - min_c) <= 28

        visited = bytearray(w * h)
        queue: deque[tuple[int, int]] = deque()

        # Seed BFS from all 4 borders
        for x in range(w):
            for y in (0, h - 1):
                r, g, b, a = px[x, y]
                if _is_bg_color(r, g, b, a):
                    idx = y * w + x
                    if not visited[idx]:
                        visited[idx] = 1
                        queue.append((x, y))
        for y in range(1, h - 1):
            for x in (0, w - 1):
                r, g, b, a = px[x, y]
                if _is_bg_color(r, g, b, a):
                    idx = y * w + x
                    if not visited[idx]:
                        visited[idx] = 1
                        queue.append((x, y))

        while queue:
            cx, cy = queue.popleft()
            px[cx, cy] = (0, 0, 0, 0)
            for nx, ny in ((cx - 1, cy), (cx + 1, cy), (cx, cy - 1), (cx, cy + 1)):
                if 0 <= nx < w and 0 <= ny < h:
                    nidx = ny * w + nx
                    if not visited[nidx]:
                        r, g, b, a = px[nx, ny]
                        if _is_bg_color(r, g, b, a):
                            visited[nidx] = 1
                            queue.append((nx, ny))

        return img

    @staticmethod
    def compose_sprite_sheet(frames: list[Image.Image], frame_size: tuple[int, int]) -> Image.Image:
        if not frames:
            raise ValueError("frames cannot be empty")

        frame_w, frame_h = frame_size
        sheet = Image.new("RGBA", (frame_w * len(frames), frame_h), (0, 0, 0, 0))
        for index, frame in enumerate(frames):
            normalized = (
                frame
                if frame.size == frame_size
                else AssetPostProcessor.fit_to_canvas(
                    frame,
                    frame_size,
                    resample=Image.Resampling.NEAREST,
                )
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
            normalized = (
                tile
                if tile.size == cell_size
                else AssetPostProcessor.fit_to_canvas(
                    tile,
                    cell_size,
                    resample=Image.Resampling.NEAREST,
                )
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
        retries: int = 6,
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
        view_angle: str = "side_scroll",
    ) -> GeneratedAsset:
        width, height = resolve_size(size_key, BACKGROUND_SIZE_KEYS, "background")
        prompt = PromptOptimizer.build_background_prompt(subject, style, time_of_day, view_angle=view_angle)
        result = self.gen.generate_with_metadata(
            prompt,
            width=width,
            height=height,
            seed=seed,
            negative_prompt=PromptOptimizer.get_negative_prompt("background"),
        )
        img = self.proc.cover_to_canvas(result.image, (width, height))
        if style == "pixel_art":
            bg_block = 2 if min(width, height) >= 512 else 1
            img = self.proc.pixelate_clean(img, block_size=bg_block, colors=64)

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
        resample = Image.Resampling.BOX if style == "pixel_art" else Image.Resampling.LANCZOS
        if transparent_bg:
            img = self.proc.remove_background(img)
            img = self.proc.clean_alpha_edges(img)
            img = self.proc.trim_and_fit_sprite(
                img, (width, height), fill_ratio=0.90, anchor="bottom", resample=resample
            )
        else:
            img = self.proc.fit_to_canvas(img, (width, height), resample=resample)

        if style == "pixel_art":
            # Keep 1:1 pixel resolution on small sprites (<128px) and crisp 2x2 pixel grid on >=128px
            eff_block = 1 if min(width, height) < 128 else 2
            img = self.proc.pixelate_clean(img, block_size=eff_block, colors=48)

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
        transparent_bg: bool = True,
    ) -> GeneratedAsset:
        width, height = resolve_size(size_key, PIXEL_SIZE_KEYS, "pixel art")
        prompt = PromptOptimizer.build_pixel_art_prompt(subject)
        gen_w, gen_h = max(width, 512), max(height, 512)
        result = self.gen.generate_with_metadata(
            prompt,
            width=gen_w,
            height=gen_h,
            seed=seed,
            negative_prompt=PromptOptimizer.get_negative_prompt("sprite"),
        )

        img = result.image
        is_sprite_canvas = size_key != "background_sq" and min(width, height) <= 256
        if transparent_bg and is_sprite_canvas:
            img = self.proc.remove_background(img)
            img = self.proc.clean_alpha_edges(img)
            img = self.proc.trim_and_fit_sprite(
                img, (width, height), fill_ratio=0.88, anchor="center", resample=Image.Resampling.BOX
            )
        else:
            img = self.proc.fit_to_canvas(img, (width, height), resample=Image.Resampling.BOX)

        # Ensure small canvases (32x32, 64x64, 128x128) keep a readable pixel grid
        # (at least 32x32 effective cells) rather than collapsing into an 8x8 blob.
        max_reasonable_block = max(1, min(width, height) // 32)
        effective_block = min(block_size, max_reasonable_block) if is_sprite_canvas else block_size
        img = self.proc.pixelate_clean(img, block_size=max(1, effective_block), colors=colors)

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
        transparent_bg: bool = False,
    ) -> GeneratedAsset:
        """Deterministic local image-to-pixel pipeline for uploaded HD assets."""
        width, height = resolve_size(size_key, PIXEL_SIZE_KEYS, "pixel art")
        source = Path(image_path)
        img = Image.open(source).convert("RGBA")
        if transparent_bg:
            img = self.proc.remove_background(img)
            img = self.proc.clean_alpha_edges(img)
            img = self.proc.trim_and_fit_sprite(
                img, (width, height), fill_ratio=0.90, anchor="center", resample=Image.Resampling.BOX
            )
        else:
            img = self.proc.fit_to_canvas(img, (width, height), resample=Image.Resampling.BOX)

        max_reasonable_block = max(1, min(width, height) // 32) if min(width, height) <= 128 else block_size
        effective_block = min(block_size, max_reasonable_block)
        img = self.proc.pixelate_clean(img, block_size=max(1, effective_block), colors=colors)

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

    def _resolve_character_identity(
        self,
        subject: str,
        style: str = "pixel_art",
        seed: int = -1,
        reference_image: str | Path | None = None,
    ) -> str:
        """Anchor character visual identity into a dense description before multi-frame
        generation so every frame in a sprite sheet / pose sheet shares the same design."""
        if reference_image:
            caption = self.describe_reference_image(reference_image)
            if caption.description:
                return f"{subject} ({caption.description})"
        return subject

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
        """Reference-image -> prompt -> sprite pipeline."""
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
        Form Output."""
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

        resample = Image.Resampling.BOX if form.style == "pixel_art" else Image.Resampling.LANCZOS
        img = self.proc.remove_background(result.image)
        img = self.proc.clean_alpha_edges(img)
        img = self.proc.trim_and_fit_sprite(
            img, (width, height), fill_ratio=0.90, anchor="bottom", resample=resample
        )

        out_name = self._safe_name(
            filename or f"char_{form.base_id}_{form.hair_id}_{form.outfit_id}_{form.size_key}"
        )

        if save_raw:
            raw_path = self.out / "sprites" / f"{out_name}_raw.png"
            self.proc.save(img, raw_path)

        if form.style == "pixel_art":
            effective_block = block_size if block_size is not None else (1 if min(width, height) < 128 else 2)
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
        every frame, aligning all frames to a shared ground baseline, and unifying
        the color palette across the whole sheet."""
        if isinstance(form, dict):
            form = CharacterFormOutput.from_dict(form)
        form.validate()

        action_spec = ACTION_CATALOG[form.action]
        frames = action_spec["frames"]
        pose_seq = action_spec.get("frame_poses", [])
        frame_size = ASSET_SIZES[form.size_key] if form.size_key in ASSET_SIZES else resolve_size(
            form.size_key, SPRITE_SIZE_KEYS, "sprite"
        )

        generated_frames: list[Image.Image] = []
        warnings: list[str] = []
        provider_name = ""
        model = ""
        base_seed = form.seed if form.seed >= 0 else random.randint(0, 2_147_483_647 - frames)
        used_seed = base_seed
        resample = Image.Resampling.BOX if form.style == "pixel_art" else Image.Resampling.LANCZOS

        for index in range(frames):
            if pose_seq:
                frame_pose = pose_seq[index % len(pose_seq)]
            else:
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
            frame = self.proc.trim_and_fit_sprite(
                frame, frame_size, fill_ratio=0.88, anchor="bottom", resample=resample
            )
            if form.style == "pixel_art":
                effective_block = block_size if block_size is not None else (1 if min(frame_size) < 128 else 2)
                frame = self.proc.pixelate_clean(frame, block_size=effective_block, colors=colors)
            generated_frames.append(frame)

        if form.style == "pixel_art":
            generated_frames = self.proc.unify_frames_palette(generated_frames, colors=colors)

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
        """Ghép layer only — no AI call."""
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
        """Compose PNG layers, caption the composited character, and generate an
        animation sheet with consistent ground baseline and unified palette."""
        if isinstance(form, dict):
            form = CharacterFormOutput.from_dict(form)
        form.validate()

        composited = AssetCompositor.compose_layers(asset_dir, form)
        caption = self.captioner.describe(
            composited.convert("RGB"), instruction=DEFAULT_CHARACTER_CAPTION_INSTRUCTION
        )

        action_spec = ACTION_CATALOG[form.action]
        frames = action_spec["frames"]
        pose_seq = action_spec.get("frame_poses", [])
        frame_size = resolve_size(form.size_key, SPRITE_SIZE_KEYS, "sprite")

        generated_frames: list[Image.Image] = []
        warnings: list[str] = list(caption.warnings)
        provider_name = ""
        model = ""
        base_seed = form.seed if form.seed >= 0 else random.randint(0, 2_147_483_647 - frames)
        resample = Image.Resampling.BOX if form.style == "pixel_art" else Image.Resampling.LANCZOS

        for index in range(frames):
            if pose_seq:
                frame_pose = pose_seq[index % len(pose_seq)]
            else:
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
            frame = self.proc.trim_and_fit_sprite(
                frame, frame_size, fill_ratio=0.88, anchor="bottom", resample=resample
            )
            if form.style == "pixel_art":
                effective_block = block_size if block_size is not None else (1 if min(frame_size) < 128 else 2)
                frame = self.proc.pixelate_clean(frame, block_size=effective_block, colors=colors)
            generated_frames.append(frame)

        if form.style == "pixel_art":
            generated_frames = self.proc.unify_frames_palette(generated_frames, colors=colors)

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
        """One-time batch job: generates the base-body + overlay PNG library."""
        asset_dir = Path(asset_dir)
        width, height = resolve_size(size_key, SPRITE_SIZE_KEYS, "sprite")
        style_tag = PromptOptimizer.STYLE_TAGS.get("pixel_art", "pixel art")
        generated: dict[str, list[str]] = {}

        def _generate_one(category: str, part_id: str, descriptor: str, extra: str, negative_category: str) -> str:
            out_path = asset_dir / category / f"{part_id}.png"
            if out_path.exists() and not overwrite:
                return str(out_path)

            if part_id == "hair_bald":
                blank = Image.new("RGBA", (width, height), (0, 0, 0, 0))
                self.proc.save(blank, out_path)
                return str(out_path)

            prompt = (
                f"{descriptor}, {extra}, centered on a solid pure white background, "
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
            anchor = "bottom" if category == "base" else "center"
            img = self.proc.trim_and_fit_sprite(
                img, (width, height), fill_ratio=0.90, anchor=anchor, resample=Image.Resampling.BOX
            )
            block = 1 if min(width, height) < 128 else 2
            img = self.proc.pixelate_clean(img, block_size=block, colors=48)
            self.proc.save(img, out_path)
            return str(out_path)

        base_specs = [
            (
                part_id, descriptor,
                "plain grey mannequin base body, neutral standing pose, no clothes, no hair, "
                "blank featureless face, front view, full body from head to feet",
                "character",
            )
            for part_id, descriptor in CHARACTER_BASE_CATALOG.items()
        ]
        hair_specs = [
            (
                part_id, descriptor,
                "2D game avatar hairstyle wig icon, standalone floating hair shape only, "
                "empty underneath, studio product icon",
                "isolated_part",
            )
            for part_id, descriptor in HAIR_CATALOG.items()
        ]
        _outfit_overrides = {
            "outfit_casual_hoodie": (
                "2D RPG inventory equipment icon of an empty hoodie and jeans laid out flat, "
                "standalone garment item icon, empty collar and sleeves"
            ),
            "outfit_ninja_suit": (
                "2D RPG inventory equipment icon of an empty folded ninja tunic and pants, "
                "standalone garment item icon, empty collar and sleeves"
            ),
        }
        outfit_specs = [
            (
                part_id, descriptor,
                _outfit_overrides.get(
                    part_id,
                    "2D RPG inventory equipment icon of a standalone garment laid out flat, "
                    "empty collar and sleeves, product flat-lay icon",
                ),
                "isolated_part",
            )
            for part_id, descriptor in OUTFIT_CATALOG.items()
        ]
        shoes_specs = [
            (
                part_id, descriptor,
                "2D RPG inventory equipment icon of a standalone pair of shoes side by side, "
                "product icon",
                "isolated_part",
            )
            for part_id, descriptor in SHOES_CATALOG.items()
        ]

        def _strip_action_verb(text: str) -> str:
            for prefix in ("wearing ", "holding ", "carrying "):
                if text.startswith(prefix):
                    return text[len(prefix):]
            return text

        accessory_specs = [
            (
                part_id, _strip_action_verb(descriptor),
                "2D RPG inventory item icon, single standalone object, product icon",
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
        reference_image: str | Path | None = None,
        skip_caption: bool = False,
    ) -> GeneratedAsset:
        """Generate each animation frame with explicit anatomical pose prompts,
        auto-trim and align every frame to a common ground baseline, unify the
        sheet palette, and compose a horizontal sprite sheet."""
        if frames < 1 or frames > 32:
            raise ValueError("frames must be between 1 and 32")
        if frame_size[0] < 16 or frame_size[1] < 16:
            raise ValueError("frame_size must be at least 16x16")

        generated_frames: list[Image.Image] = []
        warnings: list[str] = []
        provider_name = ""
        model = ""
        base_seed = seed if seed >= 0 else random.randint(0, 2_147_483_647 - frames)
        used_seed = base_seed

        character_identity = (
            subject
            if skip_caption
            else self._resolve_character_identity(subject, style, base_seed, reference_image)
        )
        resample = Image.Resampling.BOX if style == "pixel_art" else Image.Resampling.LANCZOS

        for index in range(frames):
            frame_seed = base_seed + index
            prompt = PromptOptimizer.build_animation_frame_prompt(
                character_identity, action, index, frames, style
            )
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
            frame = self.proc.trim_and_fit_sprite(
                frame, frame_size, fill_ratio=0.88, anchor="bottom", resample=resample
            )
            if style == "pixel_art":
                eff_block = 1 if min(frame_size) < 128 else 2
                frame = self.proc.pixelate_clean(frame, block_size=eff_block, colors=48)
            generated_frames.append(frame)

        if style == "pixel_art":
            generated_frames = self.proc.unify_frames_palette(generated_frames, colors=48)

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

    def generate_pose_sheet(
        self,
        subject: str,
        style: str = "pixel_art",
        seed: int = -1,
        slice_frames: bool = False,
        filename: str | None = None,
        frame_size: tuple[int, int] = (64, 64),
        reference_image: str | Path | None = None,
        skip_caption: bool = False,
    ) -> GeneratedAsset:
        """Generate a sheet of 8 distinct game character key poses (idle, walk,
        attack, jump, hurt, death) with baseline alignment and unified palette."""
        if frame_size[0] < 16 or frame_size[1] < 16:
            raise ValueError("frame_size must be at least 16x16")

        poses = [
            "idle",
            "walk_contact",
            "walk_passing",
            "attack_windup",
            "attack_impact",
            "jump",
            "hurt",
            "death",
        ]
        base_seed = seed if seed >= 0 else random.randint(0, 2_147_483_647 - len(poses))
        used_seed = base_seed
        character_identity = (
            subject
            if skip_caption
            else self._resolve_character_identity(subject, style, base_seed, reference_image)
        )
        resample = Image.Resampling.BOX if style == "pixel_art" else Image.Resampling.LANCZOS

        generated_frames: list[Image.Image] = []
        warnings: list[str] = []
        provider_name = ""
        model = ""

        for index, pose in enumerate(poses):
            frame_seed = base_seed + index
            prompt = PromptOptimizer.build_key_pose_prompt(character_identity, pose, style)
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
            frame = self.proc.trim_and_fit_sprite(
                frame, frame_size, fill_ratio=0.88, anchor="bottom", resample=resample
            )
            if style == "pixel_art":
                eff_block = 1 if min(frame_size) < 128 else 2
                frame = self.proc.pixelate_clean(frame, block_size=eff_block, colors=48)
            generated_frames.append(frame)

        if style == "pixel_art":
            generated_frames = self.proc.unify_frames_palette(generated_frames, colors=48)

        sheet = self.proc.compose_sprite_sheet(generated_frames, frame_size)
        out_name = self._safe_name(filename or f"posesheet_{subject}_{len(poses)}poses")
        path = self.out / "tilesheets" / f"{out_name}.png"
        self.proc.save(sheet, path)

        frame_meta: list[FrameMetadata] = []
        for index, (frame, pose) in enumerate(zip(generated_frames, poses)):
            frame_path = None
            if slice_frames:
                frame_path = self.out / "tilesheets" / out_name / f"{pose}_{index:02d}.png"
                self.proc.save(frame, frame_path)
            frame_meta.append(
                FrameMetadata(
                    index=index,
                    x=index * frame_size[0],
                    y=0,
                    w=frame_size[0],
                    h=frame_size[1],
                    file_path=str(frame_path) if frame_path else None,
                    name=pose,
                )
            )

        return GeneratedAsset(
            asset_id=str(uuid.uuid4()),
            asset_type="sprite_sheet",
            prompt=f"{subject}, key poses, {len(poses)} frames, {style}",
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
        """Generate a grid-packed tileset: full-bleed seamless square textures for
        terrain/floor/wall/liquid tiles, and transparent isolated cutouts for props."""
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
        resample = Image.Resampling.BOX if style == "pixel_art" else Image.Resampling.LANCZOS

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
            is_terrain = PromptOptimizer.is_seamless_terrain_tile(subject)
            if is_terrain or not transparent_bg:
                # Terrain/floor/wall/liquid tiles must fill 100% of the square cell
                # edge-to-edge so students can paint seamless platforms and maps.
                img = self.proc.cover_to_canvas(img, (cell_w, cell_h), resample=resample)
            else:
                img = self.proc.remove_background(img)
                img = self.proc.clean_alpha_edges(img)
                img = self.proc.trim_and_fit_sprite(
                    img, (cell_w, cell_h), fill_ratio=0.90, anchor="bottom", resample=resample
                )

            if style == "pixel_art":
                # Keep 1:1 pixel resolution for tiles (16x16..64x64)
                img = self.proc.pixelate_clean(img, block_size=1, colors=32)
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