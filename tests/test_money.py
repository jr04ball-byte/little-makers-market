"""The money split: PayPal fee first, then the cause share, then the kid's save/spend/give jars."""
import time

from app import db, money

db.init()


def _shop(kind="family", cause_pct=0):
    sid = db.new_id("shop")
    db.insert("shops", {"id": sid, "slug": sid, "kind": kind, "name": "Test", "cause_name": "Choir",
                        "cause_pct": cause_pct, "created": time.time()})
    mid = db.new_id("mkr")
    db.insert("makers", {"id": mid, "shop_id": sid, "nickname": "Mia", "save_pct": 50, "spend_pct": 30,
                         "give_pct": 20, "goal_name": "bike", "goal_cents": 10000, "created": time.time()})
    cid = db.new_id("art")
    db.insert("creations", {"id": cid, "shop_id": sid, "maker_id": mid, "status": "published", "title": "Sparky",
                            "created": time.time()})
    return sid, mid, cid


def _order(sid, cid, cents):
    oid = db.new_id("ord")
    db.insert("orders", {"id": oid, "shop_id": sid, "status": "COMPLETED", "total_cents": cents, "created": time.time(),
                         "items": [{"creation_id": cid, "unit_cents": cents, "quantity": 1}]})
    return db.row("SELECT * FROM orders WHERE id = ?", oid)


def test_family_sale_splits_net_into_jars():
    sid, mid, cid = _shop()
    money.split_order(_order(sid, cid, 1400), gross=1400, net=1315)  # $0.85 PayPal fee
    m = money.maker_with_balance(db.row("SELECT * FROM makers WHERE id = ?", mid))
    assert m["buckets"] == {"save": 658, "spend": 394, "give": 263}
    assert m["earned_cents"] == 1315


def test_fundraiser_sends_cause_share_first():
    sid, mid, cid = _shop("fundraiser", 50)
    o = _order(sid, cid, 2000)
    money.split_order(o, gross=2000, net=1899)
    assert money.shop_stats(sid)["cause_cents"] == 950
    m = money.maker_with_balance(db.row("SELECT * FROM makers WHERE id = ?", mid))
    assert m["earned_cents"] == 949
    line = money.celebrations_for(o)[0]["line"]
    assert "Mia" in line and "$9.49" in line and "fundraiser" in line


def test_refund_reverses_ledger_once():
    sid, mid, cid = _shop()
    o = _order(sid, cid, 1000)
    money.split_order(o, gross=1000, net=1000)
    money.reverse_ledger(o)
    money.reverse_ledger(o)  # idempotent
    assert money.maker_with_balance(db.row("SELECT * FROM makers WHERE id = ?", mid))["earned_cents"] == 0
