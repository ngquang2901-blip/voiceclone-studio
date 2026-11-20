"""Vietnamese pronunciation probe: speak tricky sentences, transcribe them back with Whisper, score per word.

python tools/vi_probe.py [--voices id,id] [--qualities balanced,quality] [--reps 2]
"""
import argparse, json, os, re, sys, time, unicodedata, urllib.request, uuid

API = os.environ.get("VC_API", "http://127.0.0.1:3910")
SENTENCES = [
    "Giọng nói này được tạo trên đám mây, nhưng nghe rất giống người thật.",
    "Anh ấy mua một cái bánh mì và hai ly cà phê sữa đá.",
    "Trời hôm nay mưa to, đường phố ngập nước, xe cộ đi lại khó khăn.",
    "Cô giáo dặn học sinh phải chăm chỉ ôn bài trước kỳ thi cuối năm.",
    "Những chiếc lá vàng rơi xuống mặt hồ yên tĩnh vào buổi chiều thu.",
]


def post(path, body=None, files=None):
    if files:
        b = uuid.uuid4().hex; parts = []
        for k, (name, data) in files.items():
            parts += [f"--{b}\r\nContent-Disposition: form-data; name=\"{k}\"; filename=\"{name}\"\r\n\r\n".encode(), data, b"\r\n"]
        for k, v in (body or {}).items():
            parts += [f"--{b}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n".encode()]
        data, ct = b"".join(parts) + f"--{b}--\r\n".encode(), f"multipart/form-data; boundary={b}"
    else:
        data, ct = json.dumps(body).encode(), "application/json"
    req = urllib.request.Request(API + path, data=data, headers={"content-type": ct})
    with urllib.request.urlopen(req, timeout=600) as r: return r.read(), dict(r.headers)


def words(s):
    s = unicodedata.normalize("NFC", s.lower())
    return re.findall(r"\w+", s)


def score(ref, hyp):
    """Word-level edit distance -> (errors, ref length, list of (ref word, heard) substitutions)."""
    r, h = words(ref), words(hyp)
    d = [[i + j if not i * j else 0 for j in range(len(h) + 1)] for i in range(len(r) + 1)]
    for i in range(1, len(r) + 1):
        for j in range(1, len(h) + 1):
            d[i][j] = min(d[i - 1][j] + 1, d[i][j - 1] + 1, d[i - 1][j - 1] + (r[i - 1] != h[j - 1]))
    subs, i, j = [], len(r), len(h)
    while i and j:
        if d[i][j] == d[i - 1][j - 1] + (r[i - 1] != h[j - 1]):
            if r[i - 1] != h[j - 1]: subs.append((r[i - 1], h[j - 1]))
            i, j = i - 1, j - 1
        elif d[i][j] == d[i - 1][j] + 1: subs.append((r[i - 1], "∅")); i -= 1
        else: j -= 1
    return d[-1][-1], len(r), subs[::-1]


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--voices", default="4e52cbc79d,a747202e64"); ap.add_argument("--qualities", default="balanced,quality")
    ap.add_argument("--reps", type=int, default=2); ap.add_argument("--extra", default="{}", help="extra JSON fields for /speech")
    ap.add_argument("--lang", default="vi", help="language sent to /speech; 'auto' sends none")
    a = ap.parse_args(); extra = json.loads(a.extra)
    for v in a.voices.split(","):
        for q in a.qualities.split(","):
            err = n = 0; t0 = time.time(); bad = []
            for s in SENTENCES:
                for _ in range(a.reps):
                    wav, _h = post("/speech", {"text": s, "voice": v, "language": None if a.lang == "auto" else a.lang, "quality": q, **extra})
                    out, _h = post("/v1/audio/transcriptions", {"language": "vi"}, {"file": ("a.wav", wav)})
                    e, k, subs = score(s, json.loads(out)["text"]); err += e; n += k; bad += subs
            print(f"voice {v} lang {a.lang} quality {q:8s} WER {100 * err / n:5.1f}%  ({time.time() - t0:.0f}s)  sai: {bad}", flush=True)
