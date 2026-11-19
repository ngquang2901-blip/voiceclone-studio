"""Dev helper: hard-link already-downloaded HuggingFace models (e.g. VoiceStudio's cache) into VoiceClone Studio's
model folder, so a dev machine does not download 6 GB again. Reads the source only; no extra disk space.

    python tools/seed_models.py [source_hf_cache] [dest_data_dir]
"""
import os, shutil, sys

SRC = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.environ["LOCALAPPDATA"], "OmniVoice", "hf_cache")
DATA = sys.argv[2] if len(sys.argv) > 2 else os.environ.get("VC_DATA") or os.path.join(os.environ["APPDATA"], "VoiceCloneStudio")
DEST = os.path.join(DATA, "models", "hf")
REPOS = ["models--k2-fsa--OmniVoice", "models--Systran--faster-whisper-large-v3"]

for repo in REPOS:
    s, d = os.path.join(SRC, repo), os.path.join(DEST, repo)
    if not os.path.isdir(s): print("không có", s); continue
    n = 0
    for root, _, files in os.walk(s):
        out = os.path.join(d, os.path.relpath(root, s)); os.makedirs(out, exist_ok=True)
        for f in files:
            if f.endswith((".lock", ".incomplete")): continue
            dst = os.path.join(out, f)
            if os.path.exists(dst): continue
            src = os.path.join(root, f)
            if os.path.islink(src): os.symlink(os.readlink(src), dst)
            else:
                try: os.link(src, dst)
                except OSError: shutil.copy2(src, dst)  # other drive: copy
            n += 1
    print(repo, "->", d, f"({n} file)")
