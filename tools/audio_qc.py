"""Artifact report for voices: clipping, clicks/crackle, breaths, noise floor — on the reference and on generated speech.

python tools/audio_qc.py ref                      # every voice's ref.wav
python tools/audio_qc.py gen [--voices a,b] [--tag before]   # speak SENTENCES with each voice through the engine
python tools/audio_qc.py file a.wav b.wav ...
Numbers are per minute of audio so long and short files compare.
"""
import argparse, json, os, sys, urllib.request

import numpy as np
import soundfile as sf

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "engine"))
from audioclean import report  # noqa: E402  same detector the engine cleans with

API = os.environ.get("VC_API", "http://127.0.0.1:3910")
VOICES = os.path.join(os.environ.get("VC_DATA") or os.path.join(os.environ["APPDATA"], "VoiceCloneStudio"), "voices")
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "test-out", "qc")
SENTENCES = {
    "vi": ["Trời hôm nay mưa to, đường phố ngập nước, xe cộ đi lại khó khăn. Mọi người nên ở nhà và giữ ấm cơ thể.",
           "Cô giáo dặn học sinh phải chăm chỉ ôn bài trước kỳ thi cuối năm, vì kết quả sẽ quyết định việc lên lớp."],
    "en": ["The rain kept falling all night, and by morning the streets were flooded. Everyone stayed inside, waiting.",
           "She opened the old letter slowly, read the first line twice, and then smiled for the first time that week."],
}


def analyse(a, sr):
    return report(a, sr)


def load(path):
    a, sr = sf.read(path, dtype="float32", always_2d=True)
    return a.mean(1), sr


def post(path, body):
    req = urllib.request.Request(API + path, data=json.dumps(body).encode(), headers={"content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=900) as r: return r.read()


def voices():
    with urllib.request.urlopen(API + "/voices") as r: return json.load(r)["voices"]


def show(name, m):
    print(f"{name[:34]:34s} {m['dur_s']:6.1f}s peak {m['peak']:.2f} clip {m['clipped']:4d}  click/min {m['clicks_per_min']:6.1f}"
          f"  thở/min {m['breaths_per_min']:5.1f}  ồn nền {m['noise_floor_db']} dB  {m['breaths'][:4]}", flush=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("mode", choices=["ref", "gen", "file"]); ap.add_argument("files", nargs="*")
    ap.add_argument("--voices", default=""); ap.add_argument("--tag", default="now")
    a = ap.parse_args(); rows = {}
    if a.mode == "file":
        for p in a.files: rows[p] = analyse(*load(p)); show(os.path.basename(p), rows[p])
    else:
        vs = [v for v in voices() if not a.voices or v["id"] in a.voices.split(",")]
        for v in vs:
            if a.mode == "ref":
                rows[v["id"]] = m = analyse(*load(os.path.join(VOICES, v["id"], "ref.wav"))); show(v["name"], m)
            else:
                os.makedirs(os.path.join(OUT, a.tag), exist_ok=True); parts = []
                for lang in ("vi", "en"):
                    for i, s in enumerate(SENTENCES[lang]):
                        p = os.path.join(OUT, a.tag, f"{v['id']}_{lang}{i}.wav")
                        open(p, "wb").write(post("/speech", {"text": s, "voice": v["id"], "language": lang}))
                        parts.append(load(p)[0])
                rows[v["id"]] = m = analyse(np.concatenate(parts), 24000); show(v["name"], m)
        json.dump(rows, open(os.path.join(OUT, f"{a.mode}-{a.tag}.json"), "w"), indent=1) if os.makedirs(OUT, exist_ok=True) is None else None
