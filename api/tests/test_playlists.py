"""Listener playlists: per profile, ordered, and only showing what the profile may hear."""

from app.models import AudioAsset

from .conftest import make_asset
from .test_household import onboard, parent


def test_playlists_are_per_profile_ordered_and_age_filtered(client, db):
    make_asset(db, "a" * 16, ready_to_publish=True, status="published", title="Crow", audience_age_range="4-8")
    make_asset(db, "b" * 16, ready_to_publish=True, status="published", title="Monkey", audience_age_range="4-8")
    make_asset(db, "c" * 16, ready_to_publish=True, status="published", title="Battle", audience_age_range="10-14")
    make_asset(db, "d" * 16, ready_to_publish=True, title="Draft")
    db.get(AudioAsset, "c" * 16).audience_age_range = "10-14"  # ready_to_publish sets 4-8
    db.commit()
    parent(client, db)
    profiles = onboard(client)
    mom = {"X-Profile-Id": str(profiles["mom"]["id"])}
    anu = {"X-Profile-Id": str(profiles["Anu"]["id"])}

    created = client.post("/api/me/playlists", json={"name": "  Car   trip "}, headers=mom)
    assert created.status_code == 201 and created.json()["name"] == "Car trip"
    playlist_id = created.json()["id"]
    url = f"/api/me/playlists/{playlist_id}"
    for asset_id in ("a" * 16, "c" * 16, "b" * 16, "a" * 16):  # adding twice is harmless
        client.post(f"{url}/items", json={"assetId": asset_id}, headers=mom)
    assert client.post(f"{url}/items", json={"assetId": "d" * 16}, headers=mom).status_code == 404  # unpublished
    detail = client.get(url, headers=mom).json()
    assert [s["title"] for s in detail["stories"]] == ["Crow", "Battle", "Monkey"] and detail["count"] == 3

    reordered = client.post(f"{url}/order", json={"assetIds": ["b" * 16, "a" * 16, "c" * 16]}, headers=mom).json()
    assert [s["title"] for s in reordered["stories"]] == ["Monkey", "Crow", "Battle"]
    removed = client.delete(f"{url}/items/{'a' * 16}", headers=mom).json()
    assert [s["title"] for s in removed["stories"]] == ["Monkey", "Battle"]
    assert client.post(url, json={"name": "Long drive"}, headers=mom).json()["name"] == "Long drive"

    # Another profile can't see or change it; a child's own playlist hides stories beyond their age band.
    assert client.get(url, headers=anu).status_code == 404
    kid_list = client.post("/api/me/playlists", json={"name": "Bedtime"}, headers=anu).json()["id"]
    assert client.post(f"/api/me/playlists/{kid_list}/items", json={"assetId": "c" * 16}, headers=anu).status_code == 404
    assert [p["name"] for p in client.get("/api/me/playlists", headers=mom).json()["items"]] == ["Long drive"]

    db.get(AudioAsset, "b" * 16).status = "archived"  # unpublished later: hidden, not lost
    db.commit()
    assert [s["title"] for s in client.get(url, headers=mom).json()["stories"]] == ["Battle"]
    assert client.delete(url, headers=mom).json() == {"ok": True}
    assert client.get(url, headers=mom).status_code == 404
