"""Find and remove what makes cloned speech sound dirty: breaths, hiss between words, crackle, overs.

The model copies its reference: a breath or hiss in ref.wav comes back in every sentence it reads. So the same
cleaning runs on the reference when a voice is made and on every generated clip.
"""
import numpy as np

HOP_S, WIN_S = 0.01, 0.02


def _frames(x, n, hop):
    if len(x) < n: x = np.pad(x, (0, n - len(x)))
    idx = np.arange(0, len(x) - n + 1, hop)[:, None] + np.arange(n)
    return x[idx]


def _runs(mask, min_len):
    """(start, length) of True runs at least min_len long."""
    out, run = [], 0
    for i, c in enumerate(np.append(mask, False)):
        if c: run += 1
        else:
            if run >= min_len: out.append((i - run, run))
            run = 0
    return out


def _periodicity(a, sr, count):
    """Best normalised autocorrelation in the 60-400 Hz pitch range, per hop, on 40 ms windows: a 20 ms window holds
    only ~1.5 periods of a deep male voice (~75 Hz), which read as unvoiced."""
    n, hop = int(0.04 * sr), int(HOP_S * sr)
    pad = np.pad(a.astype(np.float64), (n // 4, n))
    f = _frames(pad, n, hop)[:count]
    f = f - f.mean(1, keepdims=True)
    spec = np.fft.rfft(f, 2 * n, axis=1)
    r = np.fft.irfft(np.abs(spec) ** 2, axis=1)[:, :n]
    c = np.cumsum(f ** 2, axis=1)
    lags = np.arange(int(sr / 400), int(sr / 60))
    head = c[:, n - 1 - lags]                        # energy of x[0:n-k]
    tail = c[:, -1:] - np.pad(c, ((0, 0), (1, 0)))[:, lags]  # energy of x[k:n]
    norm = r[:, lags] / np.sqrt(head * tail + 1e-12)
    out = norm.max(1)
    return np.pad(out, (0, count - len(out)))


def features(a, sr):
    n, hop = int(WIN_S * sr), int(HOP_S * sr)
    f = _frames(a.astype(np.float64), n, hop) * np.hanning(n)
    spec = np.abs(np.fft.rfft(f, axis=1)) ** 2
    freqs = np.fft.rfftfreq(n, 1 / sr)
    tot = spec.sum(1) + 1e-12
    rms_db = 10 * np.log10(tot / n)
    speech_db = np.percentile(rms_db, 90)
    low = spec[:, freqs < 1000].sum(1) / tot
    hi = spec[:, freqs > 6000].sum(1) / tot
    voiced = (_periodicity(a, sr, len(rms_db)) > 0.5) & (low > 0.5) & (rms_db > speech_db - 30)
    return rms_db, speech_db, voiced, low, hi


def breaths(a, sr, feats=None):
    """Breath = >=150 ms of unvoiced, soft, broadband sound. Sibilants (s, x) are excluded by their >6 kHz share,
    other consonants by length (they last <120 ms)."""
    rms_db, speech_db, voiced, low, hi = feats or features(a, sr)
    cand = (~voiced) & (rms_db > speech_db - 32) & (rms_db < speech_db - 6) & (hi < 0.35) & (low < 0.6)
    cand = np.convolve(cand.astype(float), np.ones(3), "same") >= 2  # one odd frame must not split a breath in two
    return [(s * HOP_S, l * HOP_S) for s, l in _runs(cand, 15)]


def _click_idx(a):
    """Isolated sample jumps far above the local level: crackle, bad splices, codec glitches."""
    d = np.abs(np.diff(a.astype(np.float64)))
    loc = np.convolve(d, np.ones(480) / 480, "same") + 1e-6
    return np.where((d / loc > 25) & (d > 0.05))[0]


def clicks(a):
    return len(_click_idx(a))


def declick(a):
    """Replace each flagged sample by the mean of its neighbours (the model leaves rare one-sample spikes)."""
    out = a.copy()
    for i in _click_idx(a)[:200]:  # a crackling file has thousands: that is a bad source, not something to patch
        for j in (i, i + 1):
            if 0 < j < len(out) - 1: out[j] = 0.5 * (out[j - 1] + out[j + 1])
    return out


def report(a, sr):
    feats = features(a, sr); rms_db, speech_db = feats[0], feats[1]
    dur = len(a) / sr; br = breaths(a, sr, feats)
    quiet = rms_db[rms_db < speech_db - 35]
    return {"dur_s": round(dur, 2), "peak": round(float(np.abs(a).max()), 3), "clipped": int(np.sum(np.abs(a) >= 0.999)),
            "clicks_per_min": round(clicks(a) / dur * 60, 1), "breaths_per_min": round(len(br) / dur * 60, 1),
            "breaths": [(round(s, 2), round(l, 2)) for s, l in br][:8],
            "noise_floor_db": round(float(np.median(quiet)) - speech_db, 1) if len(quiet) > 10 else None,
            "voiced_share": round(float(feats[2].mean()), 3)}


def clean(a, sr, gate_db=40.0, peak=0.95):
    """Mute breaths, silence the hiss between words, cap the peak. Length is unchanged (dub timing relies on it)."""
    a = np.asarray(a, dtype=np.float32)
    if len(a) < int(WIN_S * sr) * 4: return a
    feats = features(a, sr); rms_db, speech_db = feats[0], feats[1]
    keep = np.ones(len(rms_db))
    for s, l in breaths(a, sr, feats):
        keep[int(round(s / HOP_S)): int(round((s + l) / HOP_S)) + 1] = 0
    # gate: >=40 ms near the file's own noise floor is room noise, not a word tail. The threshold follows the noise
    # (noisy refs sit only ~38 dB under speech) but never rises above speech-28 dB, where soft syllables live.
    floor = np.percentile(rms_db, 10)
    thr = min(speech_db - 28, max(floor + 6, speech_db - gate_db))
    for s, l in _runs(rms_db < thr, 4):
        keep[s + 1: s + l - 1] = 0
    hop = int(HOP_S * sr)
    g = np.repeat(keep, hop)[: len(a)]
    if len(g) < len(a): g = np.pad(g, (0, len(a) - len(g)), constant_values=keep[-1])
    ramp = int(0.015 * sr)  # 15 ms fades: no click where the gain changes
    g = np.convolve(g, np.ones(ramp) / ramp, "same")
    g = 0.03 + 0.97 * g  # -30 dB, not dead air: switching residual noise fully on/off between words reads as pumping
    out = declick((a * g).astype(np.float32))
    m = float(np.abs(out).max())
    if m > peak: out *= peak / m
    return np.clip(out, -1.0, 1.0)


def ref_problem(a, sr):
    """A reason the reference cannot make a usable voice, or None."""
    r = report(a, sr)
    if r["clicks_per_min"] > 60: return "Mẫu giọng bị rè/lách tách (nhiễu dày đặc): hãy dùng bản ghi sạch hơn"
    if r["voiced_share"] < 0.15: return "Mẫu gần như không có giọng nói rõ (toàn tiếng ồn hoặc nhạc)"
    return None
