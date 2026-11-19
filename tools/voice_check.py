"""Speak one line per voice and check it: words (round-trip ASR) and pitch vs the reference. Run with the engine venv python."""
import json, os, sys, urllib.request, uuid
import librosa, numpy as np

B = "http://127.0.0.1:3910"; OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "test-out", "voices")
os.makedirs(OUT, exist_ok=True)
LINES = {"vi": "Xin chào, đây là giọng được nhập từ VoiceStudio sang VoiceClone Studio.",
         "en": "Hello, this voice was imported from VoiceStudio into VoiceClone Studio."}


def f0(path):
    y, sr = librosa.load(path, sr=16000)
    f, voiced, _ = librosa.pyin(y, fmin=60, fmax=450, sr=sr)
    return float(np.nanmedian(f[voiced])) if voiced.any() else float("nan")


def asr(path):
    bnd = uuid.uuid4().hex
    body = f'--{bnd}\r\nContent-Disposition: form-data; name="file"; filename="a.wav"\r\n\r\n'.encode() + open(path, "rb").read() + f"\r\n--{bnd}--\r\n".encode()
    return json.load(urllib.request.urlopen(urllib.request.Request(B + "/v1/audio/transcriptions", body, {"content-type": f"multipart/form-data; boundary={bnd}"}), timeout=600))


rows = []
for v in json.load(urllib.request.urlopen(B + "/voices"))["voices"]:
    if len(sys.argv) > 1 and v["id"] not in sys.argv[1:]: continue
    lang = v["language"] if v["language"] in LINES else "en"
    r = urllib.request.urlopen(urllib.request.Request(B + "/speech", json.dumps({"text": LINES[lang], "voice": v["id"], "language": lang}).encode(),
                                                      {"content-type": "application/json"}), timeout=600)
    path = os.path.join(OUT, f"{v['name'].replace(' ', '_')}.wav"); open(path, "wb").write(r.read())
    ref = urllib.request.urlopen(f"{B}/voices/{v['id']}/sample").read(); rp = path[:-4] + ".ref.wav"; open(rp, "wb").write(ref)
    a, b = f0(rp), f0(path); t = asr(path)["text"]
    rows.append((v["name"], lang, r.headers["x-audio-seconds"], r.headers["x-gen-time"], round(a), round(b), round(abs(b - a) / a * 100), t))
    print(f"{v['name']:36} {lang} {r.headers['x-audio-seconds']:>5}s/{r.headers['x-gen-time']:>5}s  F0 mẫu {a:5.0f} Hz  ra {b:5.0f} Hz ({abs(b - a) / a * 100:4.0f}%)  | {t}", flush=True)
json.dump(rows, open(os.path.join(OUT, "check.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
