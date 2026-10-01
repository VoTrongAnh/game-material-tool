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
    API_KEY,
)

def main():
    print("================================================================")
    print("🎮 GAME CONCEPT: CHÚ MÈO HIỆP SĨ & KHU RỪNG NẤM TÍM (PURPLE MUSHROOM FOREST)")
    print("================================================================")
    print(f"API Key: {'Có sẵn' if API_KEY else 'Không có'}")
    
    studio = GameAssetStudio(api_key=API_KEY, output_dir=Path("output"))
    generated_list = []

    # Định nghĩa mô tả chuẩn cho nhân vật chính chú mèo hiệp sĩ để giữ nhất quán 100%
    CAT_KNIGHT_SUBJECT = (
        "chibi black cat knight hero with black fur, wearing dark obsidian armor "
        "with royal purple trim and glowing red cape, holding a silver sword, "
        "cute cat ears and feline tail"
    )

    PRINCESS_SUBJECT = (
        "cute chibi royal princess wearing an elegant lavender purple and white royal gown "
        "with red gemstone brooch, golden tiara, gentle smiling face"
    )

    # -------------------------------------------------------------------------
    # 1. Background: Khu rừng nấm tím (Side-scrolling platformer)
    # -------------------------------------------------------------------------
    print("\n[1/7] Sinh Background: Khu rừng nấm tím huyền ảo (1280x720)...")
    t0 = time.time()
    bg = studio.generate_background(
        subject=(
            "mystical 2D platformer forest filled with giant glowing purple mushrooms, "
            "vibrant red bioluminescent toadstools, dark twisted trees, glowing violet spores"
        ),
        size_key="background_sd",
        style="pixel_art",
        time_of_day="night",
        view_angle="side_scroll",
        seed=777,
        filename="concept_bg_purple_mushroom_forest",
    )
    print(f" -> Xong: {bg.file_path} ({time.time() - t0:.1f}s)")
    generated_list.append(("Background Rừng Nấm Tím", bg.file_path))

    # -------------------------------------------------------------------------
    # 2. Main Character: Chú mèo hiệp sĩ (Đen - Đỏ - Tím)
    # -------------------------------------------------------------------------
    print("\n[2/7] Sinh Sprite Nhân vật chính: Chú mèo hiệp sĩ Đen - Đỏ - Tím (128x128)...")
    t0 = time.time()
    cat_hero = studio.generate_sprite(
        subject=CAT_KNIGHT_SUBJECT,
        size_key="sprite_medium",
        style="pixel_art",
        facing="front",
        transparent_bg=True,
        seed=888,
        filename="concept_sprite_cat_knight",
    )
    print(f" -> Xong: {cat_hero.file_path} ({time.time() - t0:.1f}s)")
    generated_list.append(("Sprite Chú Mèo Hiệp Sĩ", cat_hero.file_path))

    # -------------------------------------------------------------------------
    # 3. Main Character Animation: Idle (4 frames)
    # -------------------------------------------------------------------------
    print("\n[3/7] Sinh Animation Chú Mèo Hiệp Sĩ: Idle 4 frames...")
    t0 = time.time()
    anim_idle = studio.generate_tilesheet(
        subject=CAT_KNIGHT_SUBJECT,
        frames=4,
        action="idle",
        frame_size=(64, 64),
        style="pixel_art",
        seed=888,
        skip_caption=True,
        filename="concept_cat_knight_idle_4f",
    )
    print(f" -> Xong: {anim_idle.file_path} ({time.time() - t0:.1f}s)")
    generated_list.append(("Animation Idle (Mèo Hiệp Sĩ)", anim_idle.file_path))

    # -------------------------------------------------------------------------
    # 4. Main Character Animation: Run (4 frames)
    # -------------------------------------------------------------------------
    print("\n[4/7] Sinh Animation Chú Mèo Hiệp Sĩ: Running cycle 4 frames...")
    t0 = time.time()
    anim_run = studio.generate_tilesheet(
        subject=CAT_KNIGHT_SUBJECT,
        frames=4,
        action="running",
        frame_size=(64, 64),
        style="pixel_art",
        seed=888,
        skip_caption=True,
        filename="concept_cat_knight_run_4f",
    )
    print(f" -> Xong: {anim_run.file_path} ({time.time() - t0:.1f}s)")
    generated_list.append(("Animation Run (Mèo Hiệp Sĩ)", anim_run.file_path))

    # -------------------------------------------------------------------------
    # 5. Main Character Animation: Attack (4 frames)
    # -------------------------------------------------------------------------
    print("\n[5/7] Sinh Animation Chú Mèo Hiệp Sĩ: Attack strike 4 frames...")
    t0 = time.time()
    anim_atk = studio.generate_tilesheet(
        subject=CAT_KNIGHT_SUBJECT,
        frames=4,
        action="attacking",
        frame_size=(64, 64),
        style="pixel_art",
        seed=888,
        skip_caption=True,
        filename="concept_cat_knight_attack_4f",
    )
    print(f" -> Xong: {anim_atk.file_path} ({time.time() - t0:.1f}s)")
    generated_list.append(("Animation Attack (Mèo Hiệp Sĩ)", anim_atk.file_path))

    # -------------------------------------------------------------------------
    # 6. Secondary Character: Công chúa (Princess NPC)
    # -------------------------------------------------------------------------
    print("\n[6/7] Sinh Nhân vật phụ: Công chúa (128x128)...")
    t0 = time.time()
    princess = studio.generate_sprite(
        subject=PRINCESS_SUBJECT,
        size_key="sprite_medium",
        style="pixel_art",
        facing="front",
        transparent_bg=True,
        seed=999,
        filename="concept_sprite_princess",
    )
    print(f" -> Xong: {princess.file_path} ({time.time() - t0:.1f}s)")
    generated_list.append(("Sprite Công Chúa (NPC)", princess.file_path))

    # -------------------------------------------------------------------------
    # 7. Tileset & Items: Rừng nấm tím + Vật phẩm (Nấm đỏ, Nấm tím, Con cá)
    # -------------------------------------------------------------------------
    print("\n[7/7] Sinh Tileset Rừng Nấm & Vật phẩm (Nấm tím, Nấm đỏ, Cá ma thuật) (48x48)...")
    t0 = time.time()
    tileset = studio.generate_tileset(
        tiles=[
            "purple mossy forest ground floor tile",
            "giant purple mushroom cap platform tile",
            "twisted dark wood tree trunk wall tile",
            "glowing purple magic mushroom prop",
            "vibrant red spotted toadstool mushroom prop",
            "magical glowing blue and golden fish food item",
        ],
        columns=6,
        cell_key="tile_48",
        style="pixel_art",
        seed=1001,
        filename="concept_tileset_mushroom_forest_items_48",
    )
    print(f" -> Xong: {tileset.file_path} ({time.time() - t0:.1f}s)")
    generated_list.append(("Tileset & Vật phẩm Rừng Nấm", tileset.file_path))

    print("\n================================================================")
    print("🎉 HOÀN THÀNH TẤT CẢ TÀI NGUYÊN CONCEPT GAME!")
    print("================================================================")
    for name, path in generated_list:
        p = Path(path)
        sz = p.stat().st_size if p.exists() else 0
        print(f"✔ [{name}] -> {path} ({sz:,} bytes)")

if __name__ == "__main__":
    main()
