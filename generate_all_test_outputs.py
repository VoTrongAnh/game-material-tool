import os
import sys
import time
from pathlib import Path

# Force UTF-8 stdout for Windows console
if sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

from asset_generator import (
    GameAssetStudio,
    CharacterFormOutput,
    API_KEY,
)

def main():
    print(f"=== BẮT ĐẦU XUẤT OUTPUT CÁC TEST CASE ===")
    print(f"API Key present: {bool(API_KEY)}")
    output_dir = Path("output")
    studio = GameAssetStudio(api_key=API_KEY, output_dir=output_dir)

    test_cases = []

    # 1. Background
    print("\n[1/7] Test Case: Background (Enchanted Cavern, 1280x720 side_scroll)")
    t0 = time.time()
    bg_asset = studio.generate_background(
        subject="enchanted crystal cavern with glowing blue mushrooms",
        size_key="background_sd",
        style="pixel_art",
        time_of_day="night",
        view_angle="side_scroll",
        seed=101,
        filename="bg_crystal_cavern_test",
    )
    print(f" -> Output: {bg_asset.file_path} ({time.time() - t0:.1f}s)")
    test_cases.append(("Background", bg_asset.file_path))

    # 2. Standalone Sprite
    print("\n[2/7] Test Case: Single Sprite (Cyberpunk Cat, 128x128)")
    t0 = time.time()
    sprite_asset = studio.generate_sprite(
        subject="cyberpunk cat warrior holding neon blade",
        size_key="sprite_medium",
        style="pixel_art",
        facing="front",
        transparent_bg=True,
        seed=202,
        filename="sprite_cyberpunk_cat_test",
    )
    print(f" -> Output: {sprite_asset.file_path} ({time.time() - t0:.1f}s)")
    test_cases.append(("Sprite", sprite_asset.file_path))

    # 3. Pixel Art Prop / Item
    print("\n[3/7] Test Case: Pixel Art Item (Golden Key, 64x64)")
    t0 = time.time()
    pixel_asset = studio.generate_pixel_art(
        subject="golden ancient treasure key with ruby gem",
        size_key="sprite_small",
        block_size=2,
        colors=16,
        seed=303,
        filename="pixel_golden_key_test",
        transparent_bg=True,
    )
    print(f" -> Output: {pixel_asset.file_path} ({time.time() - t0:.1f}s)")
    test_cases.append(("Pixel Art Item", pixel_asset.file_path))

    # 4. Character Customizer Form
    print("\n[4/7] Test Case: Character Customizer Form (Knight Armor, 128x128)")
    t0 = time.time()
    char_form = CharacterFormOutput(
        base_id="base_tall_slim",
        hair_id="hair_short_black",
        outfit_id="outfit_knight_armor",
        shoes_id="shoes_boots_brown",
        accessory_id="accessory_sword",
        action="action_idle",
        size_key="sprite_medium",
        seed=404,
    )
    char_asset = studio.generate_character(char_form, filename="char_custom_knight_test")
    print(f" -> Output: {char_asset.file_path} ({time.time() - t0:.1f}s)")
    test_cases.append(("Character", char_asset.file_path))

    # 5. Character Animation Sheet (4 frames Idle)
    print("\n[5/7] Test Case: Character Animation Sheet (Knight Idle 4 frames, 512x128)")
    t0 = time.time()
    anim_asset = studio.generate_character_animation(char_form, filename="char_knight_idle_4f_test")
    print(f" -> Output: {anim_asset.file_path} ({time.time() - t0:.1f}s)")
    test_cases.append(("Character Animation", anim_asset.file_path))

    # 6. Tileset (4 tiles: 2 seamless terrain + 2 props with unified palette)
    print("\n[6/7] Test Case: Tileset (4 tiles: grass, brick wall, chest, crate with unified palette)")
    t0 = time.time()
    tileset_asset = studio.generate_tileset(
        tiles=[
            "lush green grass ground tile",
            "dungeon stone brick wall tile",
            "iron treasure chest tile",
            "wooden supply crate tile",
        ],
        columns=4,
        cell_key="tile_48",
        style="pixel_art",
        seed=505,
        filename="tileset_adventure_48_test",
    )
    print(f" -> Output: {tileset_asset.file_path} ({time.time() - t0:.1f}s)")
    test_cases.append(("Tileset", tileset_asset.file_path))

    # 7. Generic Tilesheet (Cute Blue Slime Jump 4 frames)
    print("\n[7/7] Test Case: Generic Action Tilesheet (Cute Slime Jump 4 frames, 256x64)")
    t0 = time.time()
    sheet_asset = studio.generate_tilesheet(
        subject="cute blue slime monster",
        frames=4,
        action="jump",
        frame_size=(64, 64),
        style="pixel_art",
        seed=606,
        skip_caption=True,
        filename="tilesheet_cute_slime_jump_4f_test",
    )
    print(f" -> Output: {sheet_asset.file_path} ({time.time() - t0:.1f}s)")
    test_cases.append(("Tilesheet Animation", sheet_asset.file_path))

    print("\n=== HOÀN TẤT TẤT CẢ TEST CASES ===")
    for name, path in test_cases:
        p = Path(path)
        sz = p.stat().st_size if p.exists() else 0
        print(f"✔ [{name}] -> {path} ({sz:,} bytes)")

if __name__ == "__main__":
    main()
