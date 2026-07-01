"""
CLI nhanh cho AI Game Asset Studio
Dùng khi test / demo không cần code Python trực tiếp.

Ví dụ dùng:
  python cli.py background "dark dungeon cave" --size background_sd --style pixel_art
  python cli.py sprite "knight warrior" --size sprite_medium --transparent
  python cli.py pixel "gold coin" --size sprite_small --block 4
  python cli.py tilesheet "walking cat" --frames 10 --slice
"""

import argparse
import os
from asset_generator import GameAssetStudio, ASSET_SIZES

def main():
    parser = argparse.ArgumentParser(
        prog="game-asset",
        description="🎮 AI Game Asset Studio — sinh asset từ Pollinations.ai"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # ── background ──────────────────────────────────────────────────
    p_bg = sub.add_parser("background", help="Sinh background")
    p_bg.add_argument("subject", help="Mô tả scene, vd: 'forest with river'")
    p_bg.add_argument("--size",    default="background_hd", choices=list(ASSET_SIZES))
    p_bg.add_argument("--style",   default="pixel_art",
                      choices=["pixel_art","cartoon","realistic","chibi"])
    p_bg.add_argument("--time",    default="day",
                      choices=["day","night","dusk","dawn"])
    p_bg.add_argument("--seed",    type=int, default=-1)
    p_bg.add_argument("--out",     default="output")

    # ── sprite ──────────────────────────────────────────────────────
    p_sp = sub.add_parser("sprite", help="Sinh sprite nhân vật / vật phẩm")
    p_sp.add_argument("subject", help="Mô tả sprite, vd: 'cute dragon'")
    p_sp.add_argument("--size",        default="sprite_medium", choices=list(ASSET_SIZES))
    p_sp.add_argument("--style",       default="pixel_art",
                      choices=["pixel_art","cartoon","realistic","chibi"])
    p_sp.add_argument("--facing",      default="front",
                      choices=["front","side","back","three-quarter"])
    p_sp.add_argument("--transparent", action="store_true")
    p_sp.add_argument("--seed",        type=int, default=-1)
    p_sp.add_argument("--out",         default="output")

    # ── pixel art ───────────────────────────────────────────────────
    p_px = sub.add_parser("pixel", help="Sinh pixel art / 8-bit")
    p_px.add_argument("subject", help="Mô tả, vd: 'wooden shield'")
    p_px.add_argument("--size",   default="sprite_medium", choices=list(ASSET_SIZES))
    p_px.add_argument("--block",  type=int, default=8, help="Block size (4-16)")
    p_px.add_argument("--colors", type=int, default=32, help="Số màu (8-64)")
    p_px.add_argument("--seed",   type=int, default=-1)
    p_px.add_argument("--out",    default="output")

    # ── tilesheet ───────────────────────────────────────────────────
    p_ts = sub.add_parser("tilesheet", help="Sinh tilesheet animation")
    p_ts.add_argument("subject", help="Mô tả animation, vd: 'running warrior'")
    p_ts.add_argument("--frames", type=int, default=10)
    p_ts.add_argument("--style",  default="pixel_art",
                      choices=["pixel_art","cartoon","realistic","chibi"])
    p_ts.add_argument("--seed",   type=int, default=-1)
    p_ts.add_argument("--slice",  action="store_true", help="Cắt frame lẻ ra")
    p_ts.add_argument("--out",    default="output")

    args = parser.parse_args()

    studio = GameAssetStudio(
        api_key=os.getenv("POLLINATIONS_API_KEY", ""),
        output_dir=args.out,
    )

    if args.command == "background":
        path = studio.generate_background(
            subject=args.subject, size_key=args.size,
            style=args.style, time_of_day=args.time, seed=args.seed,
        )
    elif args.command == "sprite":
        path = studio.generate_sprite(
            subject=args.subject, size_key=args.size,
            style=args.style, facing=args.facing,
            transparent_bg=args.transparent, seed=args.seed,
        )
    elif args.command == "pixel":
        path = studio.generate_pixel_art(
            subject=args.subject, size_key=args.size,
            block_size=args.block, colors=args.colors, seed=args.seed,
        )
    elif args.command == "tilesheet":
        path = studio.generate_tilesheet(
            subject=args.subject, frames=args.frames,
            style=args.style, seed=args.seed, slice_frames=args.slice,
        )

    print(f"\n🎉 Asset đã lưu: {path}")

if __name__ == "__main__":
    main()
