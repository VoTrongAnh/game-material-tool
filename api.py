"""
HTTP API for the AI Game Asset Studio Character Customizer pipeline.

This is the AI <-> Web integration boundary described in the team plan: Web
posts a Form Output (base/hair/outfit/shoes/accessory/expression/action),
AI validates it against the catalog and returns a game-ready asset as a
base64 payload. GET /catalog is the single source of truth for valid part
IDs and canvas sizes, so Web's customizer options and AI's generator can
never silently drift out of sync.

Run:
    export POLLINATIONS_API_KEY=sk_...
    uvicorn api:app --host 0.0.0.0 --port 8000

Endpoints:
    GET  /health              -> liveness check
    GET  /catalog              -> all valid part IDs + action frame counts + size presets
    POST /character            -> single-pose sprite from a Form Output
    POST /character?animate=true  -> idle/run/attack animation sheet instead
"""

from __future__ import annotations

import base64
import io
import os
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel, Field

from asset_generator import (
    ACCESSORY_CATALOG,
    ACTION_CATALOG,
    BACKGROUND_SIZE_KEYS,
    CHARACTER_BASE_CATALOG,
    CHARACTER_LAYER_ORDER,
    EXPRESSION_CATALOG,
    HAIR_CATALOG,
    OUTFIT_CATALOG,
    PIXEL_SIZE_KEYS,
    SHOES_CATALOG,
    SPRITE_SIZE_KEYS,
    TILE_SIZE_KEYS,
    CharacterFormOutput,
    GameAssetStudio,
)


class CharacterFormRequest(BaseModel):
    """Mirrors CharacterFormOutput. This is the exact JSON shape Web's Form
    Output packaging step (see README, step 4) should POST to /character."""

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
    block_size: Optional[int] = Field(
        default=None,
        description="Pixel-art block size override. Default: canvas_size // 64.",
    )
    colors: int = 48


def create_app(studio: GameAssetStudio | None = None) -> FastAPI:
    """Factory so tests can inject a studio wired to a fake image provider
    instead of hitting Pollinations for real."""

    app = FastAPI(
        title="AI Game Asset Studio - Character API",
        description="Web -> AI Form Output boundary for the Character Customizer pipeline.",
        version="0.2.0",
    )
    state: dict[str, GameAssetStudio | None] = {"studio": studio}

    def get_studio() -> GameAssetStudio:
        if state["studio"] is None:
            state["studio"] = GameAssetStudio(
                api_key=os.getenv("POLLINATIONS_API_KEY", ""),
                model=os.getenv("ASSET_MODEL", "flux"),
                output_dir=os.getenv("ASSET_OUTPUT_DIR", "output"),
            )
        return state["studio"]

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok"}

    @app.get("/catalog")
    def catalog() -> dict:
        """Source of truth for every valid Form Output field. Web should build
        the customizer's option lists from this response (or CI-diff against
        it) instead of hardcoding IDs on the Web side."""
        return {
            "base": CHARACTER_BASE_CATALOG,
            "hair": HAIR_CATALOG,
            "outfit": OUTFIT_CATALOG,
            "shoes": SHOES_CATALOG,
            "accessory": ACCESSORY_CATALOG,
            "expression": EXPRESSION_CATALOG,
            "action": {k: {"label": v["label"], "frames": v["frames"]} for k, v in ACTION_CATALOG.items()},
            "facing": ["front", "side", "back", "three-quarter"],
            "sprite_size_keys": sorted(SPRITE_SIZE_KEYS),
            "background_size_keys": sorted(BACKGROUND_SIZE_KEYS),
            "tile_size_keys": sorted(TILE_SIZE_KEYS),
            "pixel_size_keys": sorted(PIXEL_SIZE_KEYS),
            "layer_order": CHARACTER_LAYER_ORDER,
            "asset_naming_convention": "<asset_dir>/<category>/<part_id>.png, e.g. character_assets/hair/hair_short_black.png",
        }

    @app.post("/character/compose")
    def compose_character(
        payload: CharacterFormRequest,
        asset_dir: str = os.getenv("CHARACTER_ASSET_DIR", "character_assets"),
        studio: GameAssetStudio = Depends(get_studio),
    ) -> dict:
        """Ghép layer only — no AI call, instant. Composites the base/hair/outfit/
        shoes/accessory PNGs from the asset library per the Form Output. Returns a
        GeneratedAsset-shaped web payload (image + metadata) even though no
        generation happened, so Web can use the same response handling as
        /character."""
        data = payload.model_dump(exclude={"block_size", "colors"})
        try:
            form = CharacterFormOutput(**data)
            form.validate()
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        try:
            img = studio.compose_character(form, asset_dir=asset_dir)
        except FileNotFoundError as exc:
            # Missing asset file(s) -> tell the caller exactly which ones, so a
            # gap in the AI-delivered library is obvious instead of a vague 500.
            raise HTTPException(status_code=409, detail=str(exc)) from exc

        buf = io.BytesIO()
        img.save(buf, format="PNG")
        data_uri = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")
        return {
            "image": data_uri,
            "metadata": {
                "total_frames": 1,
                "layout_format": "single",
                "frame_width": img.width,
                "frame_height": img.height,
                "columns": 1,
                "rows": 1,
            },
        }

    @app.post("/character/animate-from-layers")
    def animate_from_layers(
        payload: CharacterFormRequest,
        slice_frames: bool = False,
        asset_dir: str = os.getenv("CHARACTER_ASSET_DIR", "character_assets"),
        studio: GameAssetStudio = Depends(get_studio),
    ) -> dict:
        """Full 'ghép layer -> generate animation' flow: composite the real PNG
        parts, caption that composited look, then generate the action's animation
        sheet grounded in the caption instead of pure catalog text."""
        data = payload.model_dump(exclude={"block_size", "colors"})
        try:
            form = CharacterFormOutput(**data)
            form.validate()
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        try:
            asset = studio.generate_character_animation_from_layers(
                form,
                asset_dir=asset_dir,
                slice_frames=slice_frames,
                block_size=payload.block_size,
                colors=payload.colors,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=502, detail=f"generation failed: {exc}") from exc

        return asset.to_web_payload()

    @app.post("/character")
    def generate_character(
        payload: CharacterFormRequest,
        animate: bool = False,
        slice_frames: bool = False,
        studio: GameAssetStudio = Depends(get_studio),
    ) -> dict:
        data = payload.model_dump(exclude={"block_size", "colors"})
        try:
            form = CharacterFormOutput(**data)
            form.validate()
        except ValueError as exc:
            # Bad/unknown part ID from Web -> reject before any API call, with
            # the exact catalog mismatch so Web can fix the customizer option.
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        try:
            if animate:
                asset = studio.generate_character_animation(
                    form,
                    slice_frames=slice_frames,
                    block_size=payload.block_size,
                    colors=payload.colors,
                )
            else:
                asset = studio.generate_character(
                    form,
                    block_size=payload.block_size,
                    colors=payload.colors,
                )
        except Exception as exc:  # noqa: BLE001 - surface generation failures to the caller
            raise HTTPException(status_code=502, detail=f"generation failed: {exc}") from exc

        return asset.to_web_payload()

    return app


app = create_app()