"""Does cleaning cut words? Transcribe original vs cleaned reference and score both against the stored ref_text."""
import json, os, sys, tempfile
import soundfile as sf
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "engine"))
from audioclean import clean  # noqa: E402
from vi_probe import post, score  # noqa: E402

V = os.path.join(os.environ["APPDATA"], "VoiceCloneStudio", "voices")
for vid in sorted(os.listdir(V)):
    d = os.path.join(V, vid); src = os.path.join(d, "ref_orig.wav") if os.path.exists(os.path.join(d, "ref_orig.wav")) else os.path.join(d, "ref.wav")
    meta = json.load(open(os.path.join(d, "voice.json"), encoding="utf-8")); x, sr = sf.read(src, dtype="float32")
    res = []
    for tag, y in (("gốc", x), ("sạch", clean(x, sr, peak=0.9))):
        p = os.path.join(tempfile.gettempdir(), f"cv_{vid}_{tag}.wav"); sf.write(p, y, sr)
        txt = json.loads(post("/v1/audio/transcriptions", {"language": meta["language"]}, {"file": ("a.wav", open(p, "rb").read())})[0])["text"]
        e, n, subs = score(meta["ref_text"], txt); res.append(f"{tag} {100 * e / n:4.1f}% {subs[:3]}")
    print(vid, meta["name"][:26].ljust(26), " | ".join(res), flush=True)
