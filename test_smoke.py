"""Smoke test for the Character Customizer pipeline — no API key needed.

Run: python test_smoke.py
"""
from PIL import Image
import asset_generator as ag
from asset_generator import GameAssetStudio, CharacterFormOutput, ProviderResult


# Skip rembg (downloads a ~1GB model on first run) for this quick check.
ag.AssetPostProcessor.remove_background = staticmethod(
    ag.AssetPostProcessor.remove_near_white_background
)


class FakeProvider:
    """Returns a solid-color image instantly instead of calling Pollinations."""

    name = "fake"
    model = "fake-model"

    def generate(self, prompt, *, width, height, seed=-1, negative_prompt=None):
        img = Image.new("RGBA", (width, height), (120, 200, 80, 255))
        return ProviderResult(
            image=img, provider=self.name, model=self.model, seed=seed if seed >= 0 else 1
        )


def main():
    studio = GameAssetStudio(api_key="", model="fake", output_dir="/tmp/smoke_out", provider=FakeProvider())

    form = CharacterFormOutput(
        base_id="base_tall_slim",
        hair_id="hair_short_black",
        outfit_id="outfit_knight_armor",
        shoes_id="shoes_boots_brown",
        accessory_id="accessory_sword",
        expression_id="expr_happy",
        action="action_idle",
        seed=42,
    )

    asset = studio.generate_character(form)
    assert asset.width == 128 and asset.height == 128
    print("OK  generate_character ->", asset.file_path)

    anim = studio.generate_character_animation(form, slice_frames=True)
    assert len(anim.frames) == 4  # action_idle = 4 frames
    print("OK  generate_character_animation ->", anim.file_path, f"({len(anim.frames)} frames)")

    try:
        bad = CharacterFormOutput(
            base_id="not_a_real_id", hair_id="hair_short_black",
            outfit_id="outfit_knight_armor", shoes_id="shoes_boots_brown",
        )
        studio.generate_character(bad)
        raise AssertionError("expected ValueError for invalid base_id")
    except ValueError as e:
        print("OK  invalid ID rejected ->", e)

    try:
        CharacterFormOutput.from_dict({"base_id": "base_tall_slim"})
        raise AssertionError("expected ValueError for missing fields")
    except ValueError as e:
        print("OK  missing required field rejected ->", e)

    payload = asset.to_web_payload()
    assert payload["metadata"]["layout_format"] == "single"
    print("OK  to_web_payload ->", payload["metadata"])

    print("\nAll smoke tests passed.")


if __name__ == "__main__":
    main()