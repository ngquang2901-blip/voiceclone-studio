"""Offline licence keys: <base64url(payload json)>.<base64url(Ed25519 signature)>.

payload = {"sub": "<customer>", "features": ["tts", "clone", "dub", "audiobook"], "exp": <unix seconds or 0>,
           "mid": "<machine id from machine_id(); absent = any machine>"}
The engine ships only the public key (public_key.txt beside this file); keys are issued by keytool.py.
"""
import base64, hashlib, json, os, time
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


def machine_id() -> str:
    """Short, stable id of this computer that the customer sends to the seller (Windows MachineGuid, hashed)."""
    raw = ""
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography", 0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as k:
            raw = winreg.QueryValueEx(k, "MachineGuid")[0]
    except (ImportError, OSError):
        for f in ("/etc/machine-id", "/var/lib/dbus/machine-id"):
            if os.path.exists(f): raw = open(f).read().strip(); break
    raw = raw or str(__import__("uuid").getnode())
    h = hashlib.sha256(("voiceclone:" + raw).encode()).hexdigest()[:16].upper()
    return "-".join(h[i:i + 4] for i in range(0, 16, 4))


def verify(key: str, public_key=None, now=None, mid=None) -> dict:
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
    if payload.get("mid") and payload["mid"] != (mid or machine_id()):
        raise ValueError("key này cấp cho máy khác (mã máy không khớp)")
    return payload
