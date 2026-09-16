"""Smoke test for api.py — no API key needed.

Run: python test_api.py
"""
from PIL import Image
from fastapi.testclient import TestClient

import asset_generator as ag
from asset_generator import GameAssetStudio, ProviderResult, CaptionResult
from api import create_app


ag.AssetPostProcessor.remove_background = staticmethod(
    ag.AssetPostProcessor.remove_near_white_background
)


class FakeProvider:
    name = "fake"
    model = "fake-model"

    def generate(self, prompt, *, width, height, seed=-1, negative_prompt=None):
        img = Image.new("RGBA", (width, height), (120, 200, 80, 255))
        return ProviderResult(
            image=img, provider=self.name, model=self.model, seed=seed if seed >= 0 else 1
        )


class FakeCaptioner:
    name = "fake-vision"
    model = "fake-vision-model"

    def describe(self, img, instruction=None):
        return CaptionResult(
            description="knight in dark armor holding a sword", provider=self.name, model=self.model
        )


def _build_fake_asset_library(asset_dir):
    """Minimal on-disk layer library so /character/compose and
    /character/animate-from-layers have files to read."""
    for category, part_id in [
        ("base", "base_tall_slim"),
        ("hair", "hair_short_black"),
        ("outfit", "outfit_knight_armor"),
        ("shoes", "shoes_boots_brown"),
        ("accessory", "accessory_sword"),
    ]:
        p = asset_dir / category / f"{part_id}.png"
        p.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGBA", (128, 128), (10, 10, 10, 200)).save(p)


def main():
    studio = GameAssetStudio(
        api_key="", model="fake", output_dir="/tmp/api_smoke_out",
        provider=FakeProvider(), captioner=FakeCaptioner(),
    )
    client = TestClient(create_app(studio=studio))

    r = client.get("/health")
    assert r.status_code == 200 and r.json()["status"] == "ok"
    print("OK  GET /health")

    r = client.get("/catalog")
    assert r.status_code == 200
    body = r.json()
    assert "base_tall_slim" in body["base"]
    assert body["action"]["action_idle"]["frames"] == 4
    print("OK  GET /catalog ->", list(body.keys()))

    good_form = {
        "base_id": "base_tall_slim",
        "hair_id": "hair_short_black",
        "outfit_id": "outfit_knight_armor",
        "shoes_id": "shoes_boots_brown",
        "accessory_id": "accessory_sword",
        "expression_id": "expr_happy",
        "action": "action_idle",
        "seed": 42,
    }

    r = client.post("/character", json=good_form)
    assert r.status_code == 200, r.text
    payload = r.json()
    assert payload["metadata"]["layout_format"] == "single"
    print("OK  POST /character ->", payload["metadata"])

    r = client.post("/character", json=good_form, params={"animate": True, "slice_frames": False})
    assert r.status_code == 200, r.text
    anim_payload = r.json()
    assert anim_payload["metadata"]["total_frames"] == 4
    print("OK  POST /character?animate=true ->", anim_payload["metadata"])

    bad_form = dict(good_form, base_id="not_a_real_id")
    r = client.post("/character", json=bad_form)
    assert r.status_code == 422, r.text
    print("OK  POST /character with invalid base_id -> 422:", r.json()["detail"])

    incomplete_form = {"base_id": "base_tall_slim"}
    r = client.post("/character", json=incomplete_form)
    assert r.status_code == 422, r.text
    print("OK  POST /character with missing fields -> 422 (pydantic)")

    from pathlib import Path

    asset_dir = Path("/tmp/api_test_char_assets")
    _build_fake_asset_library(asset_dir)

    r = client.post("/character/compose", json=good_form, params={"asset_dir": str(asset_dir)})
    assert r.status_code == 200, r.text
    print("OK  POST /character/compose ->", r.json()["metadata"])

    r = client.post(
        "/character/compose",
        json=dict(good_form, base_id="base_short_stocky"),
        params={"asset_dir": str(asset_dir)},
    )
    assert r.status_code == 409, r.text
    print("OK  POST /character/compose with missing asset -> 409:", r.json()["detail"][:70])

    r = client.post("/character/animate-from-layers", json=good_form, params={"asset_dir": str(asset_dir)})
    assert r.status_code == 200, r.text
    print("OK  POST /character/animate-from-layers ->", r.json()["metadata"])

    r = client.get("/catalog")
    body = r.json()
    assert body["layer_order"] == ["base", "shoes", "outfit", "hair", "accessory"]
    print("OK  GET /catalog layer_order ->", body["layer_order"])

    print("\nAll API smoke tests passed.")


if __name__ == "__main__":
    main()