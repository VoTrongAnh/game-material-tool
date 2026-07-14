"""
Quick CLI for AI Game Asset Studio.

Examples:
  python cli.py background "dark dungeon cave" --size background_sd --style pixel_art
  python cli.py sprite "knight warrior" --size sprite_medium --transparent
  python cli.py pixel "gold coin" --size sprite_small --block 4
  python cli.py pixel-from-image "./input.png" --size sprite_small --block 4
  python cli.py tilesheet "walking cat" --frames 10 --frame-width 64 --frame-height 64 --slice
  python cli.py tileset --preset platformer_basic --cell-size tile_32 --columns 8 --slice
  python cli.py tileset "grass ground tile" "water tile" "lava tile" --cell-size tile_16 --columns 4
"""

from __future__ import annotations

import argparse
import json
import os

from asset_generator import (
    BACKGROUND_SIZE_KEYS,
    PIXEL_SIZE_KEYS,
    SPRITE_SIZE_KEYS,
    TILE_PRESETS,
    TILE_SIZE_KEYS,
    GameAssetStudio,
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
    p_bg.add_argument("--seed", type=int, default=-1)
    p_bg.add_argument("--out", default="output")

    p_sp = sub.add_parser("sprite", help="Generate a character/item sprite")
    p_sp.add_argument("subject", help="Sprite description, e.g. 'cute dragon'")
    p_sp.add_argument("--size", default="sprite_medium", choices=sorted(SPRITE_SIZE_KEYS))
    p_sp.add_argument("--style", default="pixel_art", choices=STYLE_CHOICES)
    p_sp.add_argument("--facing", default="front", choices=["front", "side", "back", "three-quarter"])
    p_sp.add_argument("--transparent", action="store_true")
    p_sp.add_argument("--seed", type=int, default=-1)
    p_sp.add_argument("--out", default="output")

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

    p_ts = sub.add_parser("tilesheet", help="Generate a horizontal sprite animation sheet")
    p_ts.add_argument("subject", help="Character/animation description, e.g. 'running warrior'")
    p_ts.add_argument("--frames", type=int, default=10)
    p_ts.add_argument("--action", default="running")
    p_ts.add_argument("--style", default="pixel_art", choices=STYLE_CHOICES)
    p_ts.add_argument("--frame-width", type=int, default=64)
    p_ts.add_argument("--frame-height", type=int, default=64)
    p_ts.add_argument("--seed", type=int, default=-1)
    p_ts.add_argument("--slice", action="store_true", help="Also save each frame separately")
    p_ts.add_argument("--out", default="output")

    p_tset = sub.add_parser(
        "tileset",
        help="Generate a grid-packed tileset (GameMaker/Tiled-ready sheet + JSON layout)",
    )
    p_tset.add_argument(
        "tiles",
        nargs="*",
        help="One tile subject per grid cell, e.g. \"grass ground tile\" \"water tile\". "
        "Omit if using --preset.",
    )
    p_tset.add_argument(
        "--preset",
        choices=sorted(TILE_PRESETS),
        help="Use a built-in tile list instead of typing subjects manually.",
    )
    p_tset.add_argument("--columns", type=int, default=8, help="Number of tiles per row")
    p_tset.add_argument("--cell-size", dest="cell_size", default="tile_32", choices=sorted(TILE_SIZE_KEYS))
    p_tset.add_argument("--style", default="pixel_art", choices=STYLE_CHOICES)
    p_tset.add_argument("--margin", type=int, default=0, help="Border padding around the whole sheet, in px")
    p_tset.add_argument("--spacing", type=int, default=1, help="Gutter between tiles, in px")
    p_tset.add_argument("--no-transparent", dest="transparent", action="store_false", default=True)
    p_tset.add_argument("--slice", action="store_true", help="Also save each tile as its own PNG")
    p_tset.add_argument("--seed", type=int, default=-1)
    p_tset.add_argument("--out", default="output")

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
            seed=args.seed,
        )
    elif args.command == "sprite":
        asset = studio.generate_sprite(
            subject=args.subject,
            size_key=args.size,
            style=args.style,
            facing=args.facing,
            transparent_bg=args.transparent,
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
    elif args.command == "tilesheet":
        asset = studio.generate_tilesheet(
            subject=args.subject,
            frames=args.frames,
            style=args.style,
            seed=args.seed,
            slice_frames=args.slice,
            frame_size=(args.frame_width, args.frame_height),
            action=args.action,
        )
    elif args.command == "tileset":
        if not args.tiles and not args.preset:
            parser.error("tileset requires either tile subjects or --preset")
        asset = studio.generate_tileset(
            tiles=args.tiles or None,
            preset=args.preset,
            columns=args.columns,
            cell_key=args.cell_size,
            style=args.style,
            seed=args.seed,
            margin=args.margin,
            spacing=args.spacing,
            transparent_bg=args.transparent,
            slice_tiles=args.slice,
        )
    else:
        parser.error(f"Unknown command: {args.command}")
        return

    print_asset(asset)


if __name__ == "__main__":
    main()