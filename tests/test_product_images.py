"""Tests for the product photo lookup (seeded, OBF/OFF by UPC, OFF by name)."""

from __future__ import annotations

from app.product_images.service import clean_upc, lookup_image, parse_upc_from_raw


def test_clean_upc():
    assert clean_upc("030772018460") == "030772018460"
    assert clean_upc(" 078-000-082100 ") == "078000082100"
    assert clean_upc("abc") is None
    assert clean_upc(None) is None


def test_parse_upc_from_raw():
    assert parse_upc_from_raw("IVORY BW OR 030772018460 6.97 X") == "030772018460"
    assert parse_upc_from_raw("NO CODE HERE") is None


def test_seeded_hit_needs_no_network():
    def _boom(url: str):
        raise AssertionError("seeded hit must not call the network")

    result = lookup_image(upc="030772018460", fetch=_boom)
    assert result["status"] == "ok"
    assert result["source"] == "seeded"
    assert "openbeautyfacts.org" in result["image_url"]


def test_obf_hit_by_upc():
    def _fetch(url: str):
        if "openbeautyfacts" in url:
            return {
                "status": 1,
                "product": {
                    "product_name": "Gentle Body Wash",
                    "image_front_url": "https://example.invalid/wash.jpg",
                },
            }
        return {"status": 0}

    result = lookup_image(upc="030772018460", name="Ivory Body Wash", fetch=_fetch)
    # Seeded mapping wins for this UPC; use a different UPC for the live path.
    assert result["source"] == "seeded"


def test_live_path_hit_by_upc():
    def _fetch(url: str):
        if "openbeautyfacts" in url and "999999999999" in url:
            return {
                "status": 1,
                "product": {
                    "product_name": "Test Soap",
                    "image_front_url": "https://example.invalid/soap.jpg",
                },
            }
        return {"status": 0}

    result = lookup_image(upc="999999999999", fetch=_fetch)
    assert result["status"] == "ok"
    assert result["source"] == "open_beauty_facts"
    assert result["image_url"] == "https://example.invalid/soap.jpg"


def test_miss_is_not_found_not_error():
    def _fetch(url: str):
        return {"status": 0}

    result = lookup_image(upc="078000082100", name="Dr Pepper", fetch=_fetch)
    assert result["status"] == "not_found"
    assert result["image_url"] is None


def test_fetcher_failure_is_a_miss():
    def _fetch(url: str):
        raise OSError("network down")

    result = lookup_image(upc="078000082100", fetch=_fetch)
    assert result["status"] == "not_found"


def test_endpoint(client):
    response = client.get("/api/products/image", params={"upc": "030772018460"})
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["image_url"].startswith("https://")


def test_endpoint_miss(client):
    response = client.get(
        "/api/products/image", params={"upc": "078000082100", "name": "zzznomatch"}
    )
    assert response.status_code == 200
    assert response.json()["status"] == "not_found"
