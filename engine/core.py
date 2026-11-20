"""Paths, settings, model files, audio helpers and the model calls (TTS, ASR, separation, translation)."""
import io, json, os, re, shutil, subprocess, tempfile, threading, time, urllib.request

import numpy as np
import soundfile as sf

from jobs import JobError

VERSION = "0.1.0"
SR = 24000
DATA = os.environ.get("VC_DATA") or os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "VoiceCloneStudio")
D = {k: os.path.join(DATA, k) for k in ("voices", "takes", "transcriptions", "dub", "audiobooks", "designs", "models")}
for d in D.values(): os.makedirs(d, exist_ok=True)
HF_CACHE = os.path.join(D["models"], "hf")
os.environ.setdefault("HF_HUB_CACHE", HF_CACHE)
os.environ.setdefault("TORCH_HOME", os.path.join(D["models"], "torch"))
os.environ.setdefault("ARGOS_PACKAGES_DIR", os.path.join(D["models"], "argos"))
os.environ.setdefault("ARGOS_DEVICE_TYPE", "cpu")
LICENSE_FILE = os.path.join(DATA, "license.key")
SETTINGS_FILE = os.path.join(DATA, "settings.json")
FFMPEG = os.environ.get("VC_FFMPEG") or shutil.which("ffmpeg") or "ffmpeg"
FFPROBE = os.environ.get("VC_FFPROBE") or shutil.which("ffprobe") or "ffprobe"
gpu = threading.RLock()  # every model call; jobs already run on one lane, this also covers the sync /speech route

DEFAULTS = {"device": "auto", "tts_engine": "vieneu", "quality": "balanced", "asr_model": "large-v3", "llm": {"base_url": "", "model": "", "api_key": ""}}
QUALITY_STEPS = {"fast": 16, "balanced": 32, "quality": 48}

LANGS = [("vi", "Tiếng Việt", "Vietnamese"), ("en", "Tiếng Anh", "English"), ("ja", "Tiếng Nhật", "Japanese"),
         ("ko", "Tiếng Hàn", "Korean"), ("zh", "Tiếng Trung", "Chinese"), ("fr", "Tiếng Pháp", "French"),
         ("es", "Tiếng Tây Ban Nha", "Spanish"), ("de", "Tiếng Đức", "German"), ("th", "Tiếng Thái", "Thai"),
         ("id", "Tiếng Indonesia", "Indonesian"), ("ru", "Tiếng Nga", "Russian"), ("pt", "Tiếng Bồ Đào Nha", "Portuguese"),
         ("it", "Tiếng Ý", "Italian"), ("hi", "Tiếng Hindi", "Hindi"), ("ar", "Tiếng Ả Rập", "Arabic")]
LANG_NAME = {c: n for c, n, _ in LANGS}
LANG_EN = {c: e for c, _, e in LANGS}


# ---------- small json store ----------
def read_json(path, default=None):
    try: return json.load(open(path, encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError): return default


def write_json(path, obj):
    tmp = path + ".tmp"
    json.dump(obj, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    os.replace(tmp, path)  # atomic: a crash never leaves half a project file


def settings():
    s = read_json(SETTINGS_FILE, {}) or {}
    out = {**DEFAULTS, **{k: v for k, v in s.items() if k in DEFAULTS}}
    out["llm"] = {**DEFAULTS["llm"], **(s.get("llm") or {})}
    return out


def save_settings(s):
    write_json(SETTINGS_FILE, s)


# ---------- ffmpeg ----------
def ffmpeg(*args):
    r = subprocess.run([FFMPEG, "-y", "-v", "error", *args], capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode: raise JobError("ffmpeg", "FFmpeg lỗi: " + r.stderr.strip()[-400:])


def probe(path):
    r = subprocess.run([FFPROBE, "-v", "error", "-show_entries", "format=duration:stream=codec_type", "-of", "json", path],
                       capture_output=True, text=True)
    try: info = json.loads(r.stdout)
    except json.JSONDecodeError: raise JobError("bad_media", "Không đọc được file âm thanh/video này")
    kinds = {s.get("codec_type") for s in info.get("streams", [])}
    if "audio" not in kinds: raise JobError("no_audio", "File không có tiếng")
    return {"duration": float(info.get("format", {}).get("duration") or 0), "has_video": "video" in kinds}


def load_mono(path, sr=SR, start=None, dur=None):
    with tempfile.TemporaryDirectory() as t:
        wav = os.path.join(t, "a.wav")
        ffmpeg(*(["-ss", f"{start:.3f}"] if start is not None else []), "-i", path, *(["-t", f"{dur:.3f}"] if dur else []),
               "-vn", "-ac", "1", "-ar", str(sr), wav)
        return sf.read(wav, dtype="float32")[0]


def wav_bytes(a, sr=SR):
    b = io.BytesIO(); sf.write(b, a, sr, format="WAV", subtype="PCM_16"); return b.getvalue()


def atempo_chain(f):
    """ffmpeg atempo accepts 0.5..2 per filter; chain for anything else."""
    parts = []
    while f > 2: parts.append("atempo=2"); f /= 2
    while f < 0.5: parts.append("atempo=0.5"); f /= 0.5
    return ",".join(parts + [f"atempo={f:.5f}"])


# ---------- model files ----------
MODELS = {
    "tts-vi": {"name": "VieNeu-TTS v3 Turbo (tiếng Việt/Anh, clone giọng, chạy CPU)", "repo": "pnnbao-ump/VieNeu-TTS-v3-Turbo",
               "files": ["speaker_encoder.onnx", "onnx_update/vieneu_backbone_shared.data"],
               "also": {"OpenMOSS-Team/MOSS-Audio-Tokenizer-Nano-ONNX": ["moss_audio_tokenizer_encode.onnx", "moss_audio_tokenizer_decode_step.onnx"]},
               "size_mb": 1000, "required": True, "license": "Apache-2.0 (model, MOSS codec, sea-g2p) — dùng thương mại được"},
    "tts": {"name": "OmniVoice (600 ngôn ngữ, thiết kế giọng)", "repo": "k2-fsa/OmniVoice", "files": ["model.safetensors", "audio_tokenizer/model.safetensors"], "size_mb": 3260, "required": False,
            "license": "CC-BY-NC (trọng số): KHÔNG dùng thương mại · code Apache-2.0 · tokenizer: Boson Higgs Audio 2 Community License"},
    "asr-large-v3": {"name": "Whisper large-v3 (chép lời, chính xác)", "repo": "Systran/faster-whisper-large-v3", "files": ["model.bin"], "size_mb": 3090,
                     "required": False, "license": "MIT"},
    "asr-small": {"name": "Whisper small (chép lời, nhẹ)", "repo": "Systran/faster-whisper-small", "files": ["model.bin"], "size_mb": 484, "required": False,
                  "license": "MIT"},
    "separator": {"name": "Demucs htdemucs (tách nhạc nền khỏi giọng)", "repo": "adefossez/HTDemucs", "files": ["htdemucs.yaml", "955717e8.safetensors"],
                  "size_mb": 81, "required": False, "license": "MIT"},
}


def asr_model_id():
    return "asr-" + settings()["asr_model"]


def _repo_dir(repo):
    return os.path.join(HF_CACHE, "models--" + repo.replace("/", "--"))


def _snapshot(repo, files):
    # Weights present = installed; huggingface_hub 2.x also wants README/.gitattributes to call a snapshot complete.
    try: rev = open(os.path.join(_repo_dir(repo), "refs", "main"), encoding="ascii").read().strip()
    except OSError: return None
    snap = os.path.join(_repo_dir(repo), "snapshots", rev)
    return snap if all(os.path.isfile(os.path.join(snap, f)) for f in files) else None


def model_path(mid):
    m = MODELS[mid]
    snap = _snapshot(m["repo"], m["files"])
    return snap if snap and all(_snapshot(r, f) for r, f in m.get("also", {}).items()) else None


def models_view():
    out = []
    for mid, m in MODELS.items():
        out.append({"id": mid, "name": m["name"], "size_mb": m["size_mb"], "installed": model_path(mid) is not None,
                    "required": m["required"] or mid == asr_model_id(), "license": m["license"]})
    return out


def models_ready():
    return (model_path("tts-vi") or model_path("tts")) is not None and model_path(asr_model_id()) is not None


def _dir_size(path):
    return sum(os.path.getsize(os.path.join(r, f)) for r, _, fs in os.walk(path) for f in fs if not f.endswith(".lock"))


def download_model(job, mid):
    m = MODELS[mid]
    if model_path(mid): return {"id": mid, "installed": True}
    total = m["size_mb"] * 2**20
    from huggingface_hub import snapshot_download
    dirs = [_repo_dir(r) for r in [m["repo"], *m.get("also", {})]]
    done = threading.Event()

    def watch():
        while not done.wait(1):
            got = sum(_dir_size(d) for d in dirs if os.path.isdir(d))
            job.update(min(0.99, got / total), f"Đang tải {m['name']}: {got / 2**20:.0f} / {m['size_mb']} MB")
    threading.Thread(target=watch, daemon=True).start()
    try:
        # VieNeu fetches exactly the ONNX files it runs from both repos; the full repos also hold GGUF/PyTorch copies.
        if mid == "tts-vi": vieneu_model()
        else: snapshot_download(m["repo"], cache_dir=HF_CACHE)
    except Exception as e: raise JobError("download_failed", f"Tải model lỗi (kiểm tra mạng): {e}")
    finally: done.set()
    return {"id": mid, "installed": True}


# ---------- loaded models ----------
_tts = _asr = _sep = _vn = None
_prompts: dict[str, object] = {}
_vn_voices: set[str] = set()
vn_lock = threading.Lock()  # VieNeu runs on the CPU, so it does not queue behind the GPU lock


def device():
    import torch
    want = settings()["device"]
    if want == "cpu" or not torch.cuda.is_available(): return "cpu"
    return "cuda"


def need_model(mid):
    p = model_path(mid)
    if not p: raise JobError("model_missing", f"Chưa tải model: {MODELS[mid]['name']}. Vào Cài đặt → Model để tải.")
    return p


def tts_model():
    global _tts
    if _tts is None:
        import torch
        from omnivoice import OmniVoice
        dev = device()
        _tts = OmniVoice.from_pretrained(need_model("tts"), device_map="cuda:0" if dev == "cuda" else "cpu",
                                         dtype=torch.float16 if dev == "cuda" else torch.float32)
    return _tts


def vieneu_model():
    global _vn
    with vn_lock:
        if _vn is None:
            from vieneu import Vieneu
            _vn = Vieneu(backend="onnx")  # CPU/ONNX: leaves the GPU to Whisper/Demucs and needs no torch/transformers pins
    return _vn


def asr_model():
    global _asr
    if _asr is None:
        from faster_whisper import WhisperModel
        _asr = WhisperModel(need_model(asr_model_id()), device="cpu", compute_type="int8")  # GPU stays free for TTS
    return _asr


def unload():
    global _tts, _asr, _sep, _vn
    with vn_lock: _vn = None; _vn_voices.clear()
    with gpu:
        _tts = _asr = _sep = None; _prompts.clear()
        import gc, torch
        gc.collect()
        if torch.cuda.is_available(): torch.cuda.empty_cache()


def loaded():
    return {"tts_loaded": _tts is not None or _vn is not None, "asr_loaded": _asr is not None}


# ---------- TTS ----------
def voice_prompt(voice):
    """The reference is encoded once per voice, saved as prompt.pt beside it, and reused by every request."""
    key = voice["id"]
    if key in _prompts: return _prompts[key]
    from omnivoice.models.omnivoice import VoiceClonePrompt
    vdir = os.path.join(D["voices"], key); cached = os.path.join(vdir, "prompt.pt")
    prompt = None
    if os.path.exists(cached):
        try: prompt = VoiceClonePrompt.load(cached)
        except Exception: prompt = None  # older format: rebuild below
    if prompt is None:
        m = tts_model(); tok = m.audio_tokenizer; dev = tok.device
        # Encoding a 10 s reference peaks at ~4.8 GB on the GPU (generation itself ~2.1 GB), so it runs on the CPU, once.
        if dev.type == "cuda":
            import torch
            tok.to("cpu"); torch.cuda.empty_cache()
        try: prompt = m.create_voice_clone_prompt(os.path.join(vdir, "ref.wav"), voice["ref_text"])
        finally: tok.to(dev)
        prompt.save(cached)
    _prompts[key] = prompt
    return prompt


def forget_voice(vid):
    _prompts.pop(vid, None); _vn_voices.discard(vid)


def use_vieneu(text, language, instruct):
    """VieNeu (commercial-safe) reads Vietnamese/English clones; OmniVoice is only for other languages and voice design."""
    lang = language or ("en" if text.isascii() else None)  # undetected non-ASCII text may be any language: not VieNeu's
    return settings()["tts_engine"] == "vieneu" and not instruct and lang in ("vi", "en") and model_path("tts-vi") is not None


def vieneu_generate(text, voice, speed=None, duration=None):
    import librosa, soxr
    m = vieneu_model()
    with vn_lock:
        if voice["id"] not in _vn_voices:
            m.add_voice(voice["id"], ref_audio=os.path.join(D["voices"], voice["id"], "ref.wav")); _vn_voices.add(voice["id"])
        a = np.asarray(m.infer(text, voice=voice["id"]), dtype=np.float32)
    a = soxr.resample(a, getattr(m, "sample_rate", 48000), SR).astype(np.float32)
    # VieNeu has no duration/speed control: stretch afterwards (dub fitting passes a target duration).
    target = duration or (len(a) / SR / speed if speed and abs(speed - 1) > 0.01 else None)
    if target and len(a): a = librosa.effects.time_stretch(a, rate=(len(a) / SR) / target).astype(np.float32)
    return a


def generate(text, voice=None, instruct=None, language=None, speed=None, duration=None, quality=None):
    """One call to the model. voice = voice dict (clone) or None with instruct (design)."""
    steps = QUALITY_STEPS.get(quality or settings()["quality"], 32)
    if not language:
        from textplan import guess_language
        language = guess_language(text)
    if voice and use_vieneu(text, language, instruct): return vieneu_generate(text, voice, speed, duration)
    with gpu:  # first import of omnivoice also happens here: two threads importing it at once broke the package import
        m = tts_model()
        from omnivoice.models.omnivoice import OmniVoiceGenerationConfig
        kw = {"generation_config": OmniVoiceGenerationConfig(num_step=steps)}
        if language: kw["language"] = language
        if duration: kw["duration"] = duration
        elif speed and abs(speed - 1) > 0.01: kw["speed"] = speed
        if voice: kw["voice_clone_prompt"] = voice_prompt(voice)
        elif instruct: kw["instruct"] = instruct
        try:
            return np.asarray(m.generate(text=text, **kw)[0], dtype=np.float32)
        except ValueError as e:  # bad instruct items come back as ValueError with the valid list
            raise JobError("bad_request", str(e).split("\n")[0])
        except RuntimeError as e:
            if "out of memory" in str(e).lower():
                unload(); raise JobError("gpu_oom", "GPU hết bộ nhớ. Đóng bớt app dùng GPU hoặc chọn CPU trong Cài đặt rồi thử lại.")
            raise


def speak(text, voice, language=None, speed=None, quality=None, progress=None, gap_ms=120):
    from textplan import chunk_text
    chunks = chunk_text(text)
    if not chunks: raise JobError("empty", "Chưa có chữ để đọc")
    gap = np.zeros(int(SR * gap_ms / 1000), np.float32); parts = []
    try:
        for i, c in enumerate(chunks):
            parts += [generate(c, voice, language=language, speed=speed, quality=quality), gap]
            if progress: progress((i + 1) / len(chunks))
    finally:
        release_cache()
    return np.concatenate(parts[:-1])


def release_cache():
    """Hand cached GPU blocks back after a request: on a shared 6 GB card a full VRAM makes Windows spill to RAM (~50x slower)."""
    import torch
    if torch.cuda.is_available(): torch.cuda.empty_cache()


def vram():
    import torch
    if not torch.cuda.is_available(): return None
    return {"engine_allocated_mb": torch.cuda.memory_allocated() // 2**20, "engine_reserved_mb": torch.cuda.memory_reserved() // 2**20,
            "engine_peak_mb": torch.cuda.max_memory_reserved() // 2**20}


# ---------- ASR ----------
def transcribe(path, language=None):
    audio = load_mono(path, sr=16000)  # ffmpeg decode: faster-whisper 1.2.1's PyAV call breaks on PyAV 19
    with gpu:
        segs, info = asr_model().transcribe(audio, language=language or None, vad_filter=True)
        segs = [{"id": i, "start": round(s.start, 2), "end": round(s.end, 2), "text": s.text.strip()} for i, s in enumerate(segs)]
    return {"language": info.language, "text": " ".join(s["text"] for s in segs), "segments": segs, "seconds": round(len(audio) / 16000, 2)}


# ---------- separation ----------
def separate(src_wav, out_dir):
    """-> (vocals.wav, background.wav) at 44.1 kHz stereo, or None when the separator model is not installed."""
    global _sep
    if not model_path("separator"): return None
    import torch, yaml
    from demucs.apply import BagOfModels, apply_model
    from demucs.hf import load_safetensors_model
    with gpu:
        if _sep is None:  # load from our model folder: no network at use time
            snap = model_path("separator"); bag = yaml.safe_load(open(os.path.join(snap, "htdemucs.yaml"), encoding="utf-8"))
            _sep = BagOfModels([load_safetensors_model(os.path.join(snap, f"{sig}.safetensors")) for sig in bag["models"]], bag.get("weights"), bag.get("segment"))
            _sep.eval()
        a, sr = sf.read(src_wav, dtype="float32", always_2d=True)
        wav = torch.from_numpy(a.T.copy())
        ref = wav.mean(0); wav = (wav - ref.mean()) / (ref.std() + 1e-8)
        dev = device()
        _sep.to(dev)
        try:
            out = apply_model(_sep, wav[None], device=dev, split=True, overlap=0.25, progress=False)[0]
        except RuntimeError as e:
            if "out of memory" not in str(e).lower(): raise
            torch.cuda.empty_cache(); _sep.to("cpu"); out = apply_model(_sep, wav[None], device="cpu", split=True)[0]
        finally:
            _sep.to("cpu")
            if torch.cuda.is_available(): torch.cuda.empty_cache()
        out = out * (ref.std() + 1e-8) + ref.mean()
        names = _sep.sources  # drums, bass, other, vocals
        vocals = out[names.index("vocals")]; bg = sum(out[i] for i, n in enumerate(names) if n != "vocals")
    v, b = os.path.join(out_dir, "vocals.wav"), os.path.join(out_dir, "background.wav")
    sf.write(v, vocals.numpy().T, sr); sf.write(b, bg.numpy().T, sr)
    return v, b


# ---------- translation ----------
def argos_packs():
    try:
        import argostranslate.package as pkg
        return [{"from": p.from_code, "to": p.to_code, "installed": True} for p in pkg.get_installed_packages()]
    except Exception:
        return []


def install_argos(job, src, dst):
    import argostranslate.package as pkg
    job.update(0.05, "Đang lấy danh sách gói dịch…")
    try: pkg.update_package_index()
    except Exception as e: raise JobError("download_failed", f"Không tải được danh sách gói dịch: {e}")
    avail = pkg.get_available_packages()
    pairs = [(src, dst)] if any(p.from_code == src and p.to_code == dst for p in avail) else [(src, "en"), ("en", dst)]
    have = {(p["from"], p["to"]) for p in argos_packs()}
    for i, (a, b) in enumerate(pairs):
        if (a, b) in have: continue
        p = next((p for p in avail if p.from_code == a and p.to_code == b), None)
        if not p: raise JobError("no_pack", f"Không có gói dịch {a}→{b}")
        job.update(0.1 + 0.8 * i / len(pairs), f"Đang tải gói dịch {a}→{b}…")
        pkg.install_from_path(p.download())
    return {"installed": pairs}


def translate_argos(texts, src, dst):
    import argostranslate.translate as tr
    langs = {l.code: l for l in tr.get_installed_languages()}
    t = langs.get(src) and langs.get(dst) and langs[src].get_translation(langs[dst])
    if not t: raise JobError("argos_pack_missing", f"Chưa có gói dịch {src}→{dst}. Bấm 'Cài gói dịch' (cần mạng một lần).")
    return [t.translate(x) if x.strip() else "" for x in texts]


def translate_llm(lines, src, dst):
    """lines = [{"text","seconds"}]; OpenAI-compatible chat API from Settings."""
    llm = settings()["llm"]
    if not (llm["base_url"] and llm["model"]): raise JobError("llm_not_configured", "Chưa cài AI dịch. Vào Cài đặt → Dịch bằng AI.")
    numbered = "\n".join(f"{i + 1}. [{l['seconds']:.1f}s] {l['text']}" for i, l in enumerate(lines))
    prompt = (f"Translate these {len(lines)} dubbing lines from {LANG_EN.get(src, src)} to {LANG_EN.get(dst, dst)}. "
              "Each must be speakable in about the given seconds: natural, concise, no notes. "
              f"Answer ONLY a JSON array of {len(lines)} strings in order.\n\n{numbered}")
    body = json.dumps({"model": llm["model"], "temperature": 0.3, "messages": [{"role": "user", "content": prompt}]}).encode()
    url = llm["base_url"].rstrip("/") + ("" if llm["base_url"].rstrip("/").endswith("/chat/completions") else "/chat/completions")
    req = urllib.request.Request(url, body, {"content-type": "application/json", **({"authorization": f"Bearer {llm['api_key']}"} if llm["api_key"] else {})})
    try: out = json.load(urllib.request.urlopen(req, timeout=180))["choices"][0]["message"]["content"]
    except Exception as e: raise JobError("llm_failed", f"AI dịch lỗi: {e}")
    m = re.search(r"\[.*\]", out, re.S)
    try: arr = json.loads(m.group(0)) if m else None
    except json.JSONDecodeError: arr = None
    if not isinstance(arr, list) or len(arr) != len(lines): raise JobError("llm_failed", "AI trả lời sai định dạng, thử lại")
    return [str(x).strip() for x in arr]
