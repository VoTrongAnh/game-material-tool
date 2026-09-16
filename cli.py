"""
Quick CLI for AI Game Asset Studio.

Examples:
  python cli.py background "dark dungeon cave" --size background_sd --style pixel_art
  python cli.py sprite "knight warrior" --size sprite_medium --transparent
  python cli.py pixel "gold coin" --size sprite_small --block 4
  python cli.py pixel-from-image "./input.png" --size sprite_small --block 4
  python cli.py sprite-from-image "./luffy_hd.png" --size sprite_medium --extra "holding a sword"
  python cli.py tilesheet "walking cat" --frames 10 --frame-width 64 --frame-height 64 --slice
  python cli.py tileset --preset platformer_basic --cell-size tile_32 --columns 8 --slice
  python cli.py tileset "grass ground tile" "water tile" "lava tile" --cell-size tile_16 --columns 4
  python cli.py character --base base_tall_slim --hair hair_short_black --outfit outfit_knight_armor --shoes shoes_boots_brown
  python cli.py character --form-file form_output.json --animate --slice
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

try:
    from dotenv import load_dotenv

    load_dotenv()  # đọc file .env trong thư mục hiện tại trước khi import asset_generator,
    # vì asset_generator đọc os.getenv("POLLINATIONS_API_KEY") ngay lúc import module
except ImportError:
    pass  # chưa cài python-dotenv -> vẫn dùng biến môi trường set tay như bình thường

from asset_generator import (
    ACCESSORY_CATALOG,
    ACTION_CATALOG,
    BACKGROUND_SIZE_KEYS,
    CHARACTER_BASE_CATALOG,
    EXPRESSION_CATALOG,
    HAIR_CATALOG,
    OUTFIT_CATALOG,
    PIXEL_SIZE_KEYS,
    SHOES_CATALOG,
    SPRITE_SIZE_KEYS,
    TILE_PRESETS,
    TILE_SIZE_KEYS,
    CharacterFormOutput,
    GameAssetStudio,
    resolve_size,
)


STYLE_CHOICES = ["pixel_art", "cartoon", "realistic", "chibi"]


def size_type(allowed_keys, label):
    """argparse type: accepts a preset key OR a custom 'WIDTHxHEIGHT' string
    (e.g. '800x600'), validated up front so bad input fails before any API call."""

    def _parse(value: str) -> str:
        try:
            resolve_size(value, allowed_keys, label)
        except ValueError as exc:
            raise argparse.ArgumentTypeError(str(exc)) from exc
        return value

    return _parse


def print_asset(asset) -> None:
    print(f"\nAsset saved: {asset.file_path}")
    print(json.dumps(asset.to_dict(), ensure_ascii=False, indent=2))


def print_web_payload(asset) -> None:
    """Print {'image': base64 data URI, 'metadata': {...}} for a web frontend to
    consume directly - no file path, no filesystem access needed on their side."""
    print(json.dumps(asset.to_web_payload(), ensure_ascii=False, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="game-asset",
        description="AI Game Asset Studio - generate embeddable game assets",
    )
    parser.add_argument("--model", default="flux", help="Image model/provider model name")
    parser.add_argument(
        "--timeout", type=int, default=90,
        help="HTTP timeout (seconds) per image-generation request. Raise this if you're seeing "
        "ReadTimeout/handshake-timeout errors on a slow or restricted network.",
    )
    parser.add_argument(
        "--retries", type=int, default=3,
        help="Retry attempts per image-generation request before giving up.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_bg = sub.add_parser("background", help="Generate a game background")
    p_bg.add_argument("subject", help="Scene description, e.g. 'forest with river'")
    p_bg.add_argument(
        "--size",
        default="background_hd",
        type=size_type(BACKGROUND_SIZE_KEYS, "background"),
        help=f"Preset ({sorted(BACKGROUND_SIZE_KEYS)}) or custom 'WIDTHxHEIGHT', e.g. 800x600",
    )
    p_bg.add_argument("--style", default="pixel_art", choices=STYLE_CHOICES)
    p_bg.add_argument("--time", default="day", choices=["day", "night", "dusk", "dawn"])
    p_bg.add_argument("--seed", type=int, default=-1)
    p_bg.add_argument("--out", default="output")

    p_sp = sub.add_parser("sprite", help="Generate a character/item sprite")
    p_sp.add_argument("subject", help="Sprite description, e.g. 'cute dragon'")
    p_sp.add_argument(
        "--size",
        default="sprite_medium",
        type=size_type(SPRITE_SIZE_KEYS, "sprite"),
        help=f"Preset ({sorted(SPRITE_SIZE_KEYS)}) or custom 'WIDTHxHEIGHT', e.g. 96x96",
    )
    p_sp.add_argument("--style", default="pixel_art", choices=STYLE_CHOICES)
    p_sp.add_argument("--facing", default="front", choices=["front", "side", "back", "three-quarter"])
    p_sp.add_argument("--transparent", action="store_true")
    p_sp.add_argument("--seed", type=int, default=-1)
    p_sp.add_argument("--out", default="output")

    p_px = sub.add_parser("pixel", help="Generate a text-to-pixel-art asset")
    p_px.add_argument("subject", help="Description, e.g. 'wooden shield'")
    p_px.add_argument(
        "--size",
        default="sprite_medium",
        type=size_type(PIXEL_SIZE_KEYS, "pixel art"),
        help=f"Preset ({sorted(PIXEL_SIZE_KEYS)}) or custom 'WIDTHxHEIGHT', e.g. 100x100",
    )
    p_px.add_argument("--block", type=int, default=8, help="Pixel block size, e.g. 4-16")
    p_px.add_argument("--colors", type=int, default=32, help="Palette size, 2-256")
    p_px.add_argument("--seed", type=int, default=-1)
    p_px.add_argument("--out", default="output")

    p_px_img = sub.add_parser("pixel-from-image", help="Convert an existing image to pixel art")
    p_px_img.add_argument("image_path", help="Input PNG/JPG/WebP path")
    p_px_img.add_argument(
        "--size",
        default="sprite_medium",
        type=size_type(PIXEL_SIZE_KEYS, "pixel art"),
        help=f"Preset ({sorted(PIXEL_SIZE_KEYS)}) or custom 'WIDTHxHEIGHT', e.g. 100x100",
    )
    p_px_img.add_argument("--block", type=int, default=8, help="Pixel block size, e.g. 4-16")
    p_px_img.add_argument("--colors", type=int, default=32, help="Palette size, 2-256")
    p_px_img.add_argument("--out", default="output")

    p_sp_img = sub.add_parser(
        "sprite-from-image",
        help="Auto-describe a reference image (e.g. an HD Luffy render) then generate a brand-new pixel-art sprite of that character",
    )
    p_sp_img.add_argument("image_path", help="Input HD PNG/JPG/WebP reference image, e.g. './luffy_hd.png'")
    p_sp_img.add_argument(
        "--size",
        default="sprite_medium",
        type=size_type(SPRITE_SIZE_KEYS, "sprite"),
        help=f"Preset ({sorted(SPRITE_SIZE_KEYS)}) or custom 'WIDTHxHEIGHT', e.g. 96x96",
    )
    p_sp_img.add_argument("--style", default="pixel_art", choices=STYLE_CHOICES)
    p_sp_img.add_argument("--facing", default="front", choices=["front", "side", "back", "three-quarter"])
    p_sp_img.add_argument("--no-transparent", dest="transparent", action="store_false", default=True)
    p_sp_img.add_argument(
        "--extra",
        dest="extra_details",
        default=None,
        help="Extra detail to append to the auto-generated character description, e.g. 'holding a sword'",
    )
    p_sp_img.add_argument("--seed", type=int, default=-1)
    p_sp_img.add_argument("--out", default="output")
    p_sp_img.add_argument(
        "--web-json",
        action="store_true",
        help="Print {'image': base64 data URI, 'metadata': {...}} instead of the normal "
        "asset JSON, ready for a web frontend to preview/slice without filesystem access.",
    )

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
    p_ts.add_argument(
        "--web-json",
        action="store_true",
        help="Print {'image': base64 data URI, 'metadata': {...}} instead of the normal "
        "asset JSON, ready for a web frontend to preview/slice without filesystem access.",
    )

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
    p_tset.add_argument(
        "--cell-size",
        dest="cell_size",
        default="tile_32",
        type=size_type(TILE_SIZE_KEYS, "tile"),
        help=f"Preset ({sorted(TILE_SIZE_KEYS)}) or custom 'WIDTHxHEIGHT', e.g. 40x40",
    )
    p_tset.add_argument("--style", default="pixel_art", choices=STYLE_CHOICES)
    p_tset.add_argument("--margin", type=int, default=0, help="Border padding around the whole sheet, in px")
    p_tset.add_argument("--spacing", type=int, default=1, help="Gutter between tiles, in px")
    p_tset.add_argument("--no-transparent", dest="transparent", action="store_false", default=True)
    p_tset.add_argument("--slice", action="store_true", help="Also save each tile as its own PNG")
    p_tset.add_argument("--seed", type=int, default=-1)
    p_tset.add_argument("--out", default="output")
    p_tset.add_argument(
        "--web-json",
        action="store_true",
        help="Print {'image': base64 data URI, 'metadata': {...}} instead of the normal "
        "asset JSON, ready for a web frontend to preview/slice without filesystem access.",
    )

    p_char = sub.add_parser(
        "character",
        help="Generate a character sprite (or its idle/run/attack animation) from a "
        "Web Character Customizer Form Output",
    )
    p_char.add_argument(
        "--form-file",
        default=None,
        help="Path to a Form Output JSON file, e.g. exported by the Web Character "
        "Customizer ({base_id, hair_id, outfit_id, shoes_id, accessory_id, "
        "expression_id, action, facing, size_key, style, seed}). Overrides individual flags below.",
    )
    p_char.add_argument("--base", dest="base_id", choices=sorted(CHARACTER_BASE_CATALOG), default=None)
    p_char.add_argument("--hair", dest="hair_id", choices=sorted(HAIR_CATALOG), default=None)
    p_char.add_argument("--outfit", dest="outfit_id", choices=sorted(OUTFIT_CATALOG), default=None)
    p_char.add_argument("--shoes", dest="shoes_id", choices=sorted(SHOES_CATALOG), default=None)
    p_char.add_argument(
        "--accessory", dest="accessory_id", choices=sorted(ACCESSORY_CATALOG), default="accessory_none"
    )
    p_char.add_argument(
        "--expression", dest="expression_id", choices=sorted(EXPRESSION_CATALOG), default="expr_neutral"
    )
    p_char.add_argument("--action", choices=sorted(ACTION_CATALOG), default="action_idle")
    p_char.add_argument("--facing", default="front", choices=["front", "side", "back", "three-quarter"])
    p_char.add_argument(
        "--size",
        dest="size_key",
        default="sprite_medium",
        choices=sorted(SPRITE_SIZE_KEYS),
        help="Sprite size preset (Form Output size_key)",
    )
    p_char.add_argument("--style", default="pixel_art", choices=STYLE_CHOICES)
    p_char.add_argument("--seed", type=int, default=-1)
    p_char.add_argument("--out", default="output")
    p_char.add_argument(
        "--block",
        type=int,
        default=None,
        help="Pixel block size for pixel_art style. Smaller = more detail retained "
        "(default: canvas_size // 64). Lower this if the result looks too blocky/low-detail.",
    )
    p_char.add_argument("--colors", type=int, default=48, help="Palette size, 2-256")
    p_char.add_argument(
        "--raw",
        dest="save_raw",
        action="store_true",
        help="Also save the pre-pixelation image (<name>_raw.png) to check whether a "
        "bad result comes from the AI generation itself or from the pixel-art post-processing.",
    )
    p_char.add_argument(
        "--animate",
        action="store_true",
        help="Generate the action's animation sheet (idle/run/attack) instead of a single pose",
    )
    p_char.add_argument("--slice", action="store_true", help="With --animate, also save each frame separately")
    p_char.add_argument(
        "--from-layers",
        action="store_true",
        help="Ground the animation in the composited PNG layers (base/hair/outfit/shoes/"
        "accessory from --asset-dir), captioning the actual composited look instead of "
        "relying on catalog text alone. Only affects --animate.",
    )
    p_char.add_argument(
        "--asset-dir",
        default="character_assets",
        help="Folder containing the layer PNG library (<asset-dir>/<category>/<id>.png), "
        "used with --from-layers or the character-compose command.",
    )
    p_char.add_argument(
        "--web-json",
        action="store_true",
        help="Print {'image': base64 data URI, 'metadata': {...}} instead of the normal "
        "asset JSON, ready for a web frontend to preview/slice without filesystem access.",
    )

    p_compose = sub.add_parser(
        "character-compose",
        help="Ghép layer only (no AI call): composite the base/hair/outfit/shoes/accessory "
        "PNGs from an asset library into one character image, per a Form Output",
    )
    p_compose.add_argument("--form-file", default=None)
    p_compose.add_argument("--base", dest="base_id", choices=sorted(CHARACTER_BASE_CATALOG), default=None)
    p_compose.add_argument("--hair", dest="hair_id", choices=sorted(HAIR_CATALOG), default=None)
    p_compose.add_argument("--outfit", dest="outfit_id", choices=sorted(OUTFIT_CATALOG), default=None)
    p_compose.add_argument("--shoes", dest="shoes_id", choices=sorted(SHOES_CATALOG), default=None)
    p_compose.add_argument(
        "--accessory", dest="accessory_id", choices=sorted(ACCESSORY_CATALOG), default="accessory_none"
    )
    p_compose.add_argument(
        "--size", dest="size_key", default="sprite_medium", choices=sorted(SPRITE_SIZE_KEYS)
    )
    p_compose.add_argument("--asset-dir", default="character_assets")
    p_compose.add_argument("--out", default="output")
    p_compose.add_argument("--filename", default=None)
    p_compose.add_argument(
        "--no-auto-align",
        dest="auto_align",
        action="store_false",
        default=True,
        help="Disable the bounding-box auto-align heuristic and overlay parts at raw "
        "full-canvas size/position (use once assets are manually pre-aligned).",
    )

    p_assets = sub.add_parser(
        "character-assets",
        help="One-time batch job: generate the base-body + overlay PNG asset library "
        "(needs a real API key) into <asset-dir>/<category>/<id>.png",
    )
    p_assets.add_argument("--asset-dir", default="character_assets")
    p_assets.add_argument("--size", dest="size_key", default="sprite_medium", choices=sorted(SPRITE_SIZE_KEYS))
    p_assets.add_argument(
        "--overwrite", action="store_true", help="Regenerate files that already exist in --asset-dir"
    )
    p_assets.add_argument(
        "--categories",
        nargs="+",
        choices=["base", "hair", "outfit", "shoes", "accessory"],
        default=None,
        help="Only (re)generate these categories, e.g. --categories hair outfit accessory --overwrite. "
        "Default: all 5.",
    )

    args = parser.parse_args()
    studio = GameAssetStudio(
        api_key=os.getenv("POLLINATIONS_API_KEY", ""),
        model=args.model,
        output_dir=getattr(args, "out", "output"),
        timeout=args.timeout,
        retries=args.retries,
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
    elif args.command == "sprite-from-image":
        asset = studio.generate_sprite_from_image(
            image_path=args.image_path,
            size_key=args.size,
            style=args.style,
            facing=args.facing,
            transparent_bg=args.transparent,
            extra_details=args.extra_details,
            seed=args.seed,
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
    elif args.command == "character":
        if args.form_file:
            with open(args.form_file, "r", encoding="utf-8") as fh:
                form = CharacterFormOutput.from_dict(json.load(fh))
        else:
            required = {"base_id": args.base_id, "hair_id": args.hair_id, "outfit_id": args.outfit_id, "shoes_id": args.shoes_id}
            missing = [name for name, value in required.items() if value is None]
            if missing:
                parser.error(
                    f"character requires --form-file, or all of {sorted(required)} "
                    f"(missing: {missing})"
                )
            form = CharacterFormOutput(
                base_id=args.base_id,
                hair_id=args.hair_id,
                outfit_id=args.outfit_id,
                shoes_id=args.shoes_id,
                accessory_id=args.accessory_id,
                expression_id=args.expression_id,
                action=args.action,
                facing=args.facing,
                size_key=args.size_key,
                style=args.style,
                seed=args.seed,
            )
        if args.animate:
            if args.from_layers:
                asset = studio.generate_character_animation_from_layers(
                    form,
                    asset_dir=args.asset_dir,
                    slice_frames=args.slice,
                    block_size=args.block,
                    colors=args.colors,
                )
            else:
                asset = studio.generate_character_animation(
                    form, slice_frames=args.slice, block_size=args.block, colors=args.colors
                )
        else:
            asset = studio.generate_character(
                form, block_size=args.block, colors=args.colors, save_raw=args.save_raw
            )
    elif args.command == "character-compose":
        if args.form_file:
            with open(args.form_file, "r", encoding="utf-8") as fh:
                form = CharacterFormOutput.from_dict(json.load(fh))
        else:
            required = {"base_id": args.base_id, "hair_id": args.hair_id, "outfit_id": args.outfit_id, "shoes_id": args.shoes_id}
            missing = [name for name, value in required.items() if value is None]
            if missing:
                parser.error(
                    f"character-compose requires --form-file, or all of {sorted(required)} "
                    f"(missing: {missing})"
                )
            form = CharacterFormOutput(
                base_id=args.base_id,
                hair_id=args.hair_id,
                outfit_id=args.outfit_id,
                shoes_id=args.shoes_id,
                accessory_id=args.accessory_id,
                size_key=args.size_key,
            )
        try:
            img = studio.compose_character(form, asset_dir=args.asset_dir, auto_align=args.auto_align)
        except FileNotFoundError as exc:
            parser.error(str(exc))
            return
        out_name = studio._safe_name(
            args.filename or f"compose_{form.base_id}_{form.hair_id}_{form.outfit_id}"
        )
        path = Path(args.out) / "sprites" / f"{out_name}.png"
        studio.proc.save(img, path)
        print(f"\nComposed (no AI call): {path}")
        return
    elif args.command == "character-assets":
        result = studio.generate_character_asset_library(
            asset_dir=args.asset_dir, size_key=args.size_key, overwrite=args.overwrite,
            categories=args.categories,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        total = sum(len(v) for v in result.values())
        print(f"\n{total} asset file(s) under {args.asset_dir}/")
        return
    else:
        parser.error(f"Unknown command: {args.command}")
        return

    if getattr(args, "web_json", False):
        print_web_payload(asset)
    else:
        print_asset(asset)


if __name__ == "__main__":
    main()