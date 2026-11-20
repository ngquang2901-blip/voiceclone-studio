"""Phát license key (chỉ chạy trên máy người bán).

    python keytool.py init                       # tạo cặp khoá; khoá bí mật nằm ở ~/.voiceclone-keys (KHÔNG nằm trong project)
    python keytool.py issue khach@x.com --machine ABCD-1234-EF56-7890 --days 30 [--features tts,clone,dub,audiobook]
    (mã máy: khách xem trong app, Cài đặt → License; --any-machine = key dùng được mọi máy)
"""
import argparse, json, os, sys, time
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "engine"))
from license import ALL_FEATURES, PUBLIC_KEY_FILE, b64e  # noqa: E402

PRIVATE = os.path.join(os.path.expanduser("~"), ".voiceclone-keys", "private.pem")


def init():
    if os.path.exists(PRIVATE):
        sys.exit(f"Đã có khoá ở {PRIVATE}; xoá tay nếu thật sự muốn tạo lại (mọi key cũ sẽ mất hiệu lực).")
    k = Ed25519PrivateKey.generate()
    os.makedirs(os.path.dirname(PRIVATE), exist_ok=True)
    open(PRIVATE, "wb").write(k.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    pub = k.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    open(PUBLIC_KEY_FILE, "w", encoding="ascii").write(b64e(pub) + "\n")
    print(f"Khoá bí mật: {PRIVATE}\nKhoá công khai: {PUBLIC_KEY_FILE}")


def issue(sub, days, features, mid=None):
    k = serialization.load_pem_private_key(open(PRIVATE, "rb").read(), None)
    bad = set(features) - set(ALL_FEATURES)
    if bad: sys.exit(f"tính năng không có: {bad}")
    payload = {"sub": sub, "features": features, "exp": int(time.time() + days * 86400) if days else 0, "iat": int(time.time())}
    if mid: payload["mid"] = mid.strip().upper()
    raw = json.dumps(payload, separators=(",", ":")).encode()
    print(b64e(raw) + "." + b64e(k.sign(raw)))


if __name__ == "__main__":
    ap = argparse.ArgumentParser(); sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init")
    p = sub.add_parser("issue"); p.add_argument("sub"); p.add_argument("--days", type=int, default=30)
    p.add_argument("--features", default=",".join(ALL_FEATURES))
    m = p.add_mutually_exclusive_group(required=True)
    m.add_argument("--machine", help="mã máy của khách"); m.add_argument("--any-machine", action="store_true")
    a = ap.parse_args()
    init() if a.cmd == "init" else issue(a.sub, a.days, [f for f in a.features.split(",") if f], a.machine)
