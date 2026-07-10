"""
Quick CLI for AI Game Asset Studio.

Examples:
  python cli.py background "dark dungeon cave" --size background_sd --style pixel_art
  python cli.py background "dark dungeon cave" --theme fantasy --view-angle side_scroll
  python cli.py sprite "knight warrior" --size sprite_medium --view-angle front --transparent
  python cli.py character-pack "knight warrior" --actions idle walk attack --base-char ./hero.png
  python cli.py prop "gold sword" --item-type weapon --size sprite_small
  python cli.py pixel "gold coin" --size sprite_small --block 4
  python cli.py pixel-from-image "./input.png" --size sprite_small --block 4
  python cli.py tile-sheet "forest terrain" --tiles grass dirt water stone --columns 2
  python cli.py animation "walking cat" --frames 10 --frame-width 64 --frame-height 64 --slice
"""

from __future__ import annotations

import argparse
import json
import os

from asset_generator import (
    BACKGROUND_SIZE_KEYS,
    ENVIRONMENT_THEMES,
    ITEM_TYPES,
    PIXEL_SIZE_KEYS,
    SPRITE_SIZE_KEYS,
    GameAssetStudio,
    VIEW_ANGLES,
)


STYLE_CHOICES = ["pixel_art", "cartoon", "realistic", "chibi"]


def print_asset(asset) -> None:
    print(f"\nAsset saved: {asset.file_path}")
    print(json.dumps(asset.to_dict(), ensure_ascii=False, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="game-asset",
        description="AI Game Asset Studio - generate embeddable game assets",
    )
    parser.add_argument("--model", default="flux", help="Image model/provider model name")
    sub = parser.add_subparsers(dest="command", required=True)

    p_bg = sub.add_parser("background", help="Generate a game background")
    p_bg.add_argument("subject", help="Scene description, e.g. 'forest with river'")
    p_bg.add_argument("--size", default="background_hd", choices=sorted(BACKGROUND_SIZE_KEYS))
    p_bg.add_argument("--style", default="pixel_art", choices=STYLE_CHOICES)
    p_bg.add_argument("--time", default="day", choices=["day", "night", "dusk", "dawn"])
    p_bg.add_argument("--theme", default="fantasy", choices=sorted(ENVIRONMENT_THEMES))
    p_bg.add_argument("--view-angle", default="side_scroll", choices=sorted(VIEW_ANGLES))
    p_bg.add_argument("--seed", type=int, default=-1)
    p_bg.add_argument("--out", default="output")

    p_sp = sub.add_parser("sprite", help="Generate a character/item sprite")
    p_sp.add_argument("subject", help="Sprite description, e.g. 'cute dragon'")
    p_sp.add_argument("--size", default="sprite_medium", choices=sorted(SPRITE_SIZE_KEYS))
    p_sp.add_argument("--style", default="pixel_art", choices=STYLE_CHOICES)
    p_sp.add_argument("--view-angle", "--facing", dest="view_angle", default="front", choices=sorted(VIEW_ANGLES))
    p_sp.add_argument("--transparent", action="store_true")
    p_sp.add_argument("--seed", type=int, default=-1)
    p_sp.add_argument("--out", default="output")

    p_pack = sub.add_parser("character-pack", help="Generate a base character pack with views and animations")
    p_pack.add_argument("subject", help="Character description, e.g. 'robot knight'")
    p_pack.add_argument("--base-char", default=None, help="Optional user-provided base character image")
    p_pack.add_argument("--actions", nargs="+", default=["idle", "walk", "attack"], help="Actions, e.g. idle walk attack turn")
    p_pack.add_argument("--frames", type=int, default=6)
    p_pack.add_argument("--size", default="sprite_medium", choices=sorted(SPRITE_SIZE_KEYS))
    p_pack.add_argument("--style", default="pixel_art", choices=STYLE_CHOICES)
    p_pack.add_argument("--frame-width", type=int, default=64)
    p_pack.add_argument("--frame-height", type=int, default=64)
    p_pack.add_argument("--seed", type=int, default=-1)
    p_pack.add_argument("--out", default="output")

    p_prop = sub.add_parser("prop", help="Generate a standalone item/prop asset")
    p_prop.add_argument("subject", help="Prop description, e.g. 'gold sword'")
    p_prop.add_argument("--item-type", default="collectible", choices=sorted(ITEM_TYPES))
    p_prop.add_argument("--size", default="sprite_medium", choices=sorted(SPRITE_SIZE_KEYS))
    p_prop.add_argument("--style", default="pixel_art", choices=STYLE_CHOICES)
    p_prop.add_argument("--view-angle", default="front", choices=sorted(VIEW_ANGLES))
    p_prop.add_argument("--seed", type=int, default=-1)
    p_prop.add_argument("--out", default="output")

    p_px = sub.add_parser("pixel", help="Generate a text-to-pixel-art asset")
    p_px.add_argument("subject", help="Description, e.g. 'wooden shield'")
    p_px.add_argument("--size", default="sprite_medium", choices=sorted(PIXEL_SIZE_KEYS))
    p_px.add_argument("--block", type=int, default=8, help="Pixel block size, e.g. 4-16")
    p_px.add_argument("--colors", type=int, default=32, help="Palette size, 2-256")
    p_px.add_argument("--seed", type=int, default=-1)
    p_px.add_argument("--out", default="output")

    p_px_img = sub.add_parser("pixel-from-image", help="Convert an existing image to pixel art")
    p_px_img.add_argument("image_path", help="Input PNG/JPG/WebP path")
    p_px_img.add_argument("--size", default="sprite_medium", choices=sorted(PIXEL_SIZE_KEYS))
    p_px_img.add_argument("--block", type=int, default=8, help="Pixel block size, e.g. 4-16")
    p_px_img.add_argument("--colors", type=int, default=32, help="Palette size, 2-256")
    p_px_img.add_argument("--out", default="output")

    p_tile = sub.add_parser("tileset", aliases=["tile-sheet"], help="Generate a map/environment tileset")
    p_tile.add_argument("subject", help="Tile set theme, e.g. 'forest terrain'")
    p_tile.add_argument("--tiles", nargs="+", default=None, help="Tile names, e.g. grass dirt water stone")
    p_tile.add_argument("--columns", type=int, default=4)
    p_tile.add_argument("--style", default="pixel_art", choices=STYLE_CHOICES)
    p_tile.add_argument("--tile-width", type=int, default=64)
    p_tile.add_argument("--tile-height", type=int, default=64)
    p_tile.add_argument("--seed", type=int, default=-1)
    p_tile.add_argument("--no-slice", action="store_true", help="Do not save each tile separately")
    p_tile.add_argument("--out", default="output")

    p_ts = sub.add_parser("animation", aliases=["tilesheet"], help="Generate a horizontal sprite animation sheet")
    p_ts.add_argument("subject", help="Character/animation description, e.g. 'running warrior'")
    p_ts.add_argument("--frames", type=int, default=10)
    p_ts.add_argument("--action", default="running")
    p_ts.add_argument("--style", default="pixel_art", choices=STYLE_CHOICES)
    p_ts.add_argument("--frame-width", type=int, default=64)
    p_ts.add_argument("--frame-height", type=int, default=64)
    p_ts.add_argument("--seed", type=int, default=-1)
    p_ts.add_argument("--slice", action="store_true", help="Also save each frame separately")
    p_ts.add_argument("--out", default="output")

    args = parser.parse_args()
    studio = GameAssetStudio(
        api_key=os.getenv("POLLINATIONS_API_KEY", ""),
        model=args.model,
        output_dir=args.out,
    )

    if args.command == "background":
        asset = studio.generate_background(
            subject=args.subject,
            size_key=args.size,
            style=args.style,
            time_of_day=args.time,
            theme=args.theme,
            view_angle=args.view_angle,
            seed=args.seed,
        )
    elif args.command == "sprite":
        asset = studio.generate_sprite(
            subject=args.subject,
            size_key=args.size,
            style=args.style,
            view_angle=args.view_angle,
            transparent_bg=args.transparent,
            seed=args.seed,
        )
    elif args.command == "character-pack":
        pack = studio.generate_character_pack(
            subject=args.subject,
            base_image_path=args.base_char,
            actions=args.actions,
            frames=args.frames,
            size_key=args.size,
            frame_size=(args.frame_width, args.frame_height),
            style=args.style,
            seed=args.seed,
        )
        print("\nCharacter pack generated:")
        print(json.dumps({
            "base": pack["base"].to_dict(),
            "views": {k: v.to_dict() for k, v in pack["views"].items()},
            "animations": {k: v.to_dict() for k, v in pack["animations"].items()},
            "manifest_path": pack["manifest_path"],
        }, ensure_ascii=False, indent=2))
        return
    elif args.command == "prop":
        asset = studio.generate_prop(
            subject=args.subject,
            item_type=args.item_type,
            size_key=args.size,
            style=args.style,
            view_angle=args.view_angle,
            seed=args.seed,
        )
    elif args.command == "pixel":
        asset = studio.generate_pixel_art(
            subject=args.subject,
            size_key=args.size,
            block_size=args.block,
            colors=args.colors,
            seed=args.seed,
        )
    elif args.command == "pixel-from-image":
        asset = studio.convert_image_to_pixel_art(
            image_path=args.image_path,
            size_key=args.size,
            block_size=args.block,
            colors=args.colors,
        )
    elif args.command in {"tileset", "tile-sheet"}:
        asset = studio.generate_tileset(
            subject=args.subject,
            tiles=args.tiles,                     # <-- now passed
            columns=args.columns,
            style=args.style,
            seed=args.seed,
            slice_tiles=not args.no_slice,
            tile_size=(args.tile_width, args.tile_height),
        )
    elif args.command in {"animation", "tilesheet"}:
        asset = studio.generate_animation_sheet(
            subject=args.subject,
            frames=args.frames,
            style=args.style,
            seed=args.seed,
            slice_frames=args.slice,
            frame_size=(args.frame_width, args.frame_height),
            action=args.action,
        )
    else:
        parser.error(f"Unknown command: {args.command}")
        return

    print_asset(asset)


if __name__ == "__main__":
    main()
