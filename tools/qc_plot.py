"""Spectrogram strip of a wav with marked breath candidates, to eyeball what audio_qc flags."""
import sys
import numpy as np, soundfile as sf
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
sys.path.insert(0, __import__("os").path.dirname(__file__))
from audio_qc import analyse, load

paths, out = sys.argv[1:-1], sys.argv[-1]
fig, axes = plt.subplots(len(paths), 1, figsize=(16, 2.6 * len(paths)), squeeze=False)
for ax, p in zip(axes[:, 0], paths):
    a, sr = load(p); m = analyse(a, sr)
    ax.specgram(a, NFFT=512, Fs=sr, noverlap=384, cmap="magma", vmin=-120)
    for s, l in m["breaths"]: ax.axvspan(s, s + l, color="cyan", alpha=0.25)
    ax.set_ylim(0, 12000); ax.set_title(f"{p.split(chr(92))[-1]}  clicks/min {m['clicks_per_min']}  thở/min {m['breaths_per_min']}  peak {m['peak']}", fontsize=9)
plt.tight_layout(); plt.savefig(out, dpi=70); print(out)
