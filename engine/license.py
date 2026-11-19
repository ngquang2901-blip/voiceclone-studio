"""Offline licence keys: <base64url(payload json)>.<base64url(Ed25519 signature)>.

payload = {"sub": "<customer>", "features": ["tts", "clone", "dub", "audiobook"], "exp": <unix seconds or 0>}
The engine ships only the public key (public_key.txt beside this file); keys are issued by keytool.py.
"""
import base64, json, os, time
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.exceptions import InvalidSignature

ALL_FEATURES = ("tts", "clone", "dub", "audiobook")
PUBLIC_KEY_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "public_key.txt")


def b64e(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def b64d(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def load_public_key(path=PUBLIC_KEY_FILE):
    return Ed25519PublicKey.from_public_bytes(b64d(open(path, encoding="ascii").read().strip()))


def verify(key: str, public_key=None, now=None) -> dict:
    """Returns the payload of a valid key; raises ValueError with a reason a person can read."""
    try:
        body, sig = key.strip().split(".")
        raw = b64d(body)
        (public_key or load_public_key()).verify(b64d(sig), raw)
        payload = json.loads(raw)
    except InvalidSignature:
        raise ValueError("key không hợp lệ (chữ ký sai)")
    except Exception:
        raise ValueError("key sai định dạng")
    exp = payload.get("exp") or 0
    if exp and (now or time.time()) > exp:
        raise ValueError("key đã hết hạn")
    # shortcut: key not bound to a machine (can be shared), add a machine id claim before selling widely.
    return payload
