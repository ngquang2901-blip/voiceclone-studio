"""Re-clean the references of voices made before audioclean existed (run with the app closed).

python tools/clean_voices.py [--dry-run]
Keeps the untouched reference as ref_orig.wav (never overwritten) and drops the cached prompt so it is rebuilt.
"""
import argparse, os, shutil, sys
import soundfile as sf
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "engine"))
from audioclean import clean, ref_problem, report  # noqa: E402

VOICES = os.path.join(os.environ.get("VC_DATA") or os.path.join(os.environ["APPDATA"], "VoiceCloneStudio"), "voices")

if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("--dry-run", action="store_true"); a = ap.parse_args()
    for vid in sorted(os.listdir(VOICES)):
        d = os.path.join(VOICES, vid); ref = os.path.join(d, "ref.wav"); orig = os.path.join(d, "ref_orig.wav")
        if not os.path.exists(ref): continue
        src = orig if os.path.exists(orig) else ref
        x, sr = sf.read(src, dtype="float32")
        if x.ndim > 1: x = x.mean(1)
        before = report(x, sr); y = clean(x, sr, peak=0.9); after = report(y, sr)
        print(f"{vid}: thở/min {before['breaths_per_min']} -> {after['breaths_per_min']}, ồn nền {before['noise_floor_db']} -> {after['noise_floor_db']} dB"
              + (f"  ⚠ {ref_problem(x, sr)}" if ref_problem(x, sr) else ""))
        if a.dry_run: continue
        if not os.path.exists(orig): shutil.copy2(ref, orig)
        sf.write(ref, y, sr)
        for f in ("prompt.pt",):
            if os.path.exists(os.path.join(d, f)): os.remove(os.path.join(d, f))
