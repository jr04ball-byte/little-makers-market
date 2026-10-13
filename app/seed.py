"""Create demo markets from the sample drawings (runs the real AI + 3D pipeline).

    python -m app.seed            # adds demo shops if the database has none
    python -m app.seed --force    # adds them again
"""
from __future__ import annotations

import sys
import time

from fastapi.testclient import TestClient

from . import config, db
from .main import app

FAMILY = {
    "shop": {"name": "The Maple Street Makers", "kind": "family", "owner_name": "Dad",
             "blurb": "Original art by Mia, Leo and Ava — turned into squishy 3D plushies, stickers and prints for the people who love them."},
    "makers": [
        {"nickname": "Mia", "age": 7, "emoji": "🦄", "goal_name": "new bike", "goal_cents": 12000, "payout_email": "parent-mia@example.com"},
        {"nickname": "Leo", "age": 5, "emoji": "🚀", "goal_name": "telescope", "goal_cents": 6000, "payout_email": "parent-leo@example.com"},
        {"nickname": "Ava", "age": 9, "emoji": "🌻", "goal_name": "art camp", "goal_cents": 20000, "payout_email": "parent-ava@example.com",
         "save_pct": 40, "spend_pct": 30, "give_pct": 30},
    ],
    "art": [
        ("purple-dragon", 0, ["Sparky", "He melts the snow so everybody can play outside in winter"]),
        ("space-rocket", 1, ["Zoomy", "It can fly to the moon and back before bedtime"]),
        ("rainbow-cat", 2, ["Rainbow Biscuit", "She turns grumpy days into rainbow days with one purr"]),
        ("robot-friend", 1, ["Bolt", "He fixes broken toys with his magic red hand"]),
    ],
}

FUNDRAISER = {
    "shop": {"name": "Grace Church Kids Art Sale", "kind": "fundraiser", "owner_name": "Pastor Jo",
             "cause_name": "Youth Choir Trip", "cause_pct": 50, "cause_email": "treasurer@example.org", "goal_cents": 150000,
             "blurb": "Our Sunday school kids drew these. Half of every sale sends the youth choir to the regional festival."},
    "makers": [
        {"nickname": "Noah", "age": 8, "emoji": "🦖", "family_name": "Noah's family", "payout_email": "noah-family@example.com"},
        {"nickname": "Grace", "age": 6, "emoji": "🐢", "family_name": "Grace's family", "payout_email": "grace-family@example.com"},
        {"nickname": "Sam", "age": 10, "emoji": "👾", "family_name": "Sam's family", "payout_email": "sam-family@example.com"},
    ],
    "art": [
        ("happy-dinosaur", 0, ["Spot", "He gives the best dino hugs in the whole church"]),
        ("sun-turtle", 1, ["Sunny", "She carries the sunshine on her back to rainy places"]),
        ("silly-monster", 2, ["Chompers", "He only eats broccoli and is very proud of it"]),
    ],
}


def build(c: TestClient, spec: dict) -> str:
    shop = c.post("/api/shops", json=spec["shop"]).json()
    makers = [c.post(f"/api/shops/{shop['slug']}/makers", json=m).json() for m in spec["makers"]]
    for name, mi, answers in spec["art"]:
        t = time.time()
        with open(config.ROOT / "samples" / "drawings" / f"{name}.png", "rb") as f:
            r = c.post("/api/creations", data={"shop": shop["slug"], "maker_id": makers[mi]["id"]},
                       files={"photo": (f"{name}.png", f, "image/png")})
        r.raise_for_status()
        cr = r.json()
        qs = cr["analysis"].get("questions") or ["What's its name?", "What's its superpower?"]
        cr = c.post(f"/api/creations/{cr['id']}/answers", json={"answers": dict(zip(qs, answers))}).json()
        c.post(f"/api/creations/{cr['id']}/publish")
        print(f"  {cr['title']}  ({time.time() - t:.0f}s)", flush=True)
    return shop["slug"]


def main():
    db.init()
    if db.rows("SELECT id FROM shops") and "--force" not in sys.argv:
        print("Demo data already exists (use --force to add again).")
        return
    c = TestClient(app)
    for spec in (FAMILY, FUNDRAISER):
        print("Building", spec["shop"]["name"])
        slug = build(c, spec)
        print(f"  -> {config.PUBLIC_URL}/shop/{slug}")


if __name__ == "__main__":
    main()
