"""Self-check for the logic that needs no GPU: python selfcheck.py"""
import os, sys, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "engine"))
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
import json, time
import license as lic
from textplan import chunk_text, fit_plan, parse_book, plan_book

# chunking: never over the limit, nothing lost
txt = "Câu một ngắn. " + "Đây là một câu rất dài, có nhiều dấu phẩy, " * 20 + "Hết! Câu cuối?"
ch = chunk_text(txt, 120)
assert all(len(c) <= 120 for c in ch), [len(c) for c in ch]
assert " ".join(ch).split() == txt.split()
assert chunk_text("") == []

# audiobook script
items = parse_book("# Chương 1\nXin chào. [pause 800ms] Tiếp.\n\n[voice:Nam] Tôi là Nam.", "Lan")
says = [(i["say"], i["voice"]) for i in items if "say" in i]
assert says == [("Xin chào.", "Lan"), ("Tiếp.", "Lan"), ("Tôi là Nam.", "Nam")], says
assert items[0] == {"chapter": "Chương 1"} and {"pause_ms": 800} in items

# pause in seconds + plan estimate
it2 = parse_book("# A\nMột hai ba. [pause 0.5s] Bốn.", "Lan")
assert {"pause_ms": 500} in it2, it2
pl = plan_book(it2); assert pl["words"] == 4 and pl["chapters"] == [{"title": "A", "words": 4}] and pl["est_seconds"] > 0.5, pl

# slot fitting
assert fit_plan(2.0, 0, 3)["status"] == "fits"
assert fit_plan(3.6, 0, 3) == {"speed": 1.2, "status": "sped_up"}
assert fit_plan(6.0, 0, 3)["status"] == "overflow"
assert fit_plan(9, 5, None)["status"] == "fits"

# licence: good key, wrong signer, tampered, expired
k = Ed25519PrivateKey.generate(); pub = k.public_key()
def mk(payload, key=k):
    raw = json.dumps(payload).encode(); return lic.b64e(raw) + "." + lic.b64e(key.sign(raw))
good = mk({"sub": "a", "features": ["tts"], "exp": 0})
assert lic.verify(good, pub)["sub"] == "a"
for bad, why in [(mk({"sub": "a"}, Ed25519PrivateKey.generate()), "chữ ký"),
                 (lic.b64e(json.dumps({"sub": "b", "features": ["tts"], "exp": 0}).encode()) + "." + good.split(".")[1], "chữ ký"),
                 (mk({"sub": "a", "exp": time.time() - 1}), "hết hạn"), ("rác", "định dạng")]:
    try: lic.verify(bad, pub); raise AssertionError("accepted " + why)
    except ValueError as e: assert why in str(e), (why, e)
# machine binding: own id passes, another machine's id is refused
me = lic.machine_id(); assert len(me) == 19 and me == lic.machine_id(), me
assert lic.verify(mk({"sub": "a", "exp": 0, "mid": me}), pub)["mid"] == me
try: lic.verify(mk({"sub": "a", "exp": 0, "mid": "0000-0000-0000-0000"}), pub); raise AssertionError("accepted other machine")
except ValueError as e: assert "máy khác" in str(e), e
print("selfcheck OK")
