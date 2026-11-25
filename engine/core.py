"""Paths, settings, model files, audio helpers and the model calls (TTS, ASR, separation, translation)."""
import io, json, os, re, shutil, subprocess, tempfile, threading, time, urllib.request

import numpy as np
import soundfile as sf

from jobs import JobError

VERSION = "0.2.8"
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

DEFAULTS = {"device": "auto", "quality": "balanced", "asr_model": "large-v3", "llm": {"base_url": "", "model": "", "api_key": ""}}
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
    "tts": {"name": "OmniVoice (giọng nói, clone, thiết kế giọng)", "repo": "k2-fsa/OmniVoice", "files": ["model.safetensors", "audio_tokenizer/model.safetensors"], "size_mb": 3260, "required": True,
            "license": "Trọng số CC-BY-NC (phi thương mại) · code Apache-2.0 · tokenizer: Boson Higgs Audio 2 Community License"},
    "asr-large-v3": {"name": "Whisper large-v3 (chép lời, chính xác)", "repo": "Systran/faster-whisper-large-v3", "files": ["model.bin"], "size_mb": 3090,
                     "required": False, "license": "MIT"},
    "asr-small": {"name": "Whisper small (chép lời, nhẹ)", "repo": "Systran/faster-whisper-small", "files": ["model.bin"], "size_mb": 484, "required": False,
                  "license": "MIT"},
    "separator": {"name": "Demucs htdemucs (tách nhạc nền khỏi giọng)", "repo": "adefossez/HTDemucs", "files": ["htdemucs.yaml", "955717e8.safetensors"],
                  "size_mb": 81, "required": False, "license": "MIT"},
}


def asr_model_id():
    return "asr-" + settings()["asr_model"]


def model_path(mid):
    m = MODELS[mid]
    if "repo" in m:
        # Weights present = installed; huggingface_hub 2.x also wants README/.gitattributes to call a snapshot complete.
        repo_dir = os.path.join(HF_CACHE, "models--" + m["repo"].replace("/", "--"))
        try: rev = open(os.path.join(repo_dir, "refs", "main"), encoding="ascii").read().strip()
        except OSError: return None
        snap = os.path.join(repo_dir, "snapshots", rev)
        return snap if all(os.path.isfile(os.path.join(snap, f)) for f in m["files"]) else None
    return None


def models_view():
    out = []
    for mid, m in MODELS.items():
        out.append({"id": mid, "name": m["name"], "size_mb": m["size_mb"], "installed": model_path(mid) is not None,
                    "required": m["required"] or mid == asr_model_id(), "license": m["license"]})
    return out


def models_ready():
    return model_path("tts") is not None and model_path(asr_model_id()) is not None


def _dir_size(path):
    return sum(os.path.getsize(os.path.join(r, f)) for r, _, fs in os.walk(path) for f in fs if not f.endswith(".lock"))


def download_model(job, mid):
    m = MODELS[mid]
    if model_path(mid): return {"id": mid, "installed": True}
    total = m["size_mb"] * 2**20
    from huggingface_hub import snapshot_download
    repo_dir = os.path.join(HF_CACHE, "models--" + m["repo"].replace("/", "--"))
    done = threading.Event()

    def watch():
        while not done.wait(1):
            if os.path.isdir(repo_dir):
                got = _dir_size(repo_dir)
                job.update(min(0.99, got / total), f"Đang tải {m['name']}: {got / 2**20:.0f} / {m['size_mb']} MB")
    threading.Thread(target=watch, daemon=True).start()
    try: snapshot_download(m["repo"], cache_dir=HF_CACHE)
    except Exception as e: raise JobError("download_failed", f"Tải model lỗi (kiểm tra mạng): {e}")
    finally: done.set()
    return {"id": mid, "installed": True}


# ---------- loaded models ----------
_tts = _asr = _sep = None
_prompts: dict[str, object] = {}


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


def asr_model():
    global _asr
    if _asr is None:
        from faster_whisper import WhisperModel
        path = need_model(asr_model_id())
        if device() == "cuda":
            import torch  # CTranslate2 needs cuBLAS/cuDNN 9: use the copies torch already ships
            os.add_dll_directory(os.path.join(os.path.dirname(torch.__file__), "lib"))
            try:
                # 9 s clip: 4.4 s on an RTX 3060 vs 42-57 s on the CPU, same text; ~1.5 GB next to OmniVoice's ~2.4 GB
                _asr = WhisperModel(path, device="cuda", compute_type="int8_float16"); return _asr
            except (RuntimeError, ValueError, OSError) as e:  # no usable CUDA for CTranslate2: fall back to the CPU
                print("Whisper on CPU:", e, flush=True)
        _asr = WhisperModel(path, device="cpu", compute_type="int8", cpu_threads=os.cpu_count() or 4)
    return _asr


def warm_up():
    """Load the models in the background when the engine starts, so the first click does not wait ~40 s."""
    def run():
        try:
            if model_path("tts"):
                with gpu: tts_model()
            if model_path(asr_model_id()):
                with gpu: asr_model()
        except Exception as e:  # a failed warm-up only means the first request loads them (and reports the error)
            print("warm-up:", e, flush=True)
    threading.Thread(target=run, daemon=True, name="warm-up").start()


def unload():
    global _tts, _asr, _sep
    with gpu:
        _tts = _asr = _sep = None; _prompts.clear()
        import gc, torch
        gc.collect()
        if torch.cuda.is_available(): torch.cuda.empty_cache()


def loaded():
    return {"tts_loaded": _tts is not None, "asr_loaded": _asr is not None}


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
    _prompts.pop(vid, None)


BATCH = 4  # measured on a 6 GB RTX 3060: 4 lines per call is 1.9x faster than one at a time (+360 MB); 8 is no faster


def generate(text, voice=None, instruct=None, language=None, speed=None, duration=None, quality=None):
    """One line. voice = voice dict (clone) or None with instruct (design)."""
    return generate_many([text], voice, instruct, language, speed, [duration], quality)[0]


LEN_BIAS = 1.07  # real clips (and duration=… requests) came out 4-12 % longer than the model's estimate, 4 lines measured


def natural_seconds(texts, voice):
    """Seconds the model will take for each line at normal speed: its own text-based estimate, no audio made."""
    with gpu:
        m = tts_model(); p = voice_prompt(voice)
        fr = m.audio_tokenizer.config.frame_rate; n = p.ref_audio_tokens.size(-1)
        # shortcut: private omnivoice helper (same call generate() makes), re-check after upgrading omnivoice
        return [m._estimate_target_tokens(t, p.ref_text, n) / fr * LEN_BIAS for t in texts]


def generate_many(texts, voice=None, instruct=None, language=None, speed=None, durations=None, quality=None, progress=None):
    """Several lines with one voice, BATCH per model call (the reference prompt is shared, so batching saves most
    of the per-call cost). durations: per-line target seconds or None. Returns cleaned float32 arrays in order."""
    from textplan import guess_language
    from audioclean import clean
    steps = QUALITY_STEPS.get(quality or settings()["quality"], 32)
    langs = [language or guess_language(t) for t in texts]
    durations = durations or [None] * len(texts)
    out, i, size = [], 0, BATCH
    with gpu:  # first import of omnivoice also happens here: two threads importing it at once broke the package import
        m = tts_model()
        from omnivoice.models.omnivoice import OmniVoiceGenerationConfig
        kw = {"generation_config": OmniVoiceGenerationConfig(num_step=steps)}
        if voice: kw["voice_clone_prompt"] = voice_prompt(voice)
        elif instruct: kw["instruct"] = instruct
        if speed and abs(speed - 1) > 0.01 and not any(durations): kw["speed"] = speed
        while i < len(texts):
            j = min(len(texts), i + size)
            part = {"duration": durations[i:j]} if any(durations[i:j]) else {}
            if any(langs[i:j]): part["language"] = langs[i:j]
            try:
                res = m.generate(text=texts[i:j], **kw, **part)
            except ValueError as e:  # bad instruct items come back as ValueError with the valid list
                raise JobError("bad_request", str(e).split("\n")[0])
            except RuntimeError as e:
                if "out of memory" not in str(e).lower(): raise
                import torch
                torch.cuda.empty_cache()
                if size > 1: size //= 2; continue  # retry this slice smaller
                unload(); raise JobError("gpu_oom", "GPU hết bộ nhớ. Đóng bớt app dùng GPU hoặc chọn CPU trong Cài đặt rồi thử lại.")
            out += [clean(np.asarray(a, dtype=np.float32), SR) for a in res]
            i = j
            if progress: progress(i / len(texts))
    return out


def speak(text, voice, language=None, speed=None, quality=None, progress=None, gap_ms=120):
    from textplan import chunk_text
    chunks = chunk_text(text)
    if not chunks: raise JobError("empty", "Chưa có chữ để đọc")
    gap = np.zeros(int(SR * gap_ms / 1000), np.float32); parts = []
    try: clips = generate_many(chunks, voice, language=language, speed=speed, quality=quality, progress=progress)
    finally: release_cache()
    for c in clips: parts += [c, gap]
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
def sentences(segs):
    """Whisper segments (with words) -> one segment per sentence: cut at end punctuation, a 0.8 s pause, or a comma past 15 s."""
    out, cur = [], []
    words = [w for s in segs for w in (s.words or [])]
    for i, w in enumerate(words):
        cur.append(w)
        gap = words[i + 1].start - w.end if i + 1 < len(words) else 9
        if re.search(r"[.?!。？！…]$", w.word.strip()) or gap > 0.8 or (w.end - cur[0].start > 15 and w.word.strip().endswith((",", "，"))):
            out.append({"start": round(float(cur[0].start), 2), "end": round(float(w.end), 2), "text": "".join(x.word for x in cur).strip()}); cur = []
    return [dict(s, id=i) for i, s in enumerate(o for o in out if o["text"])]


def transcribe(path, language=None):
    from faster_whisper import BatchedInferencePipeline
    audio = load_mono(path, sr=16000)  # ffmpeg decode: faster-whisper 1.2.1's PyAV call breaks on PyAV 19
    global _tts, _asr
    with gpu:
        # batched decoding of VAD chunks: 2 min of speech 70.5 s -> 5.7 s on an RTX 3060, same text (99.5 %).
        # GPU shared with browsers/games can run out: free the TTS model, smaller batches, then the CPU.
        for bs in (8, 4, 2, 1, "cpu"):
            try:
                if bs == "cpu":
                    from faster_whisper import WhisperModel
                    _asr = WhisperModel(need_model(asr_model_id()), device="cpu", compute_type="int8", cpu_threads=os.cpu_count() or 4)
                segs, info = BatchedInferencePipeline(model=asr_model()).transcribe(audio, language=language or None, batch_size=4 if bs == "cpu" else bs, word_timestamps=True)
                segs = sentences(list(segs))
                if bs == "cpu": _asr = None  # next job tries the GPU again
                break
            except RuntimeError as e:
                # after an OOM CTranslate2 can also fail with other CUDA errors ("invalid device ordinal"): same path
                if not re.search(r"out of memory|cuda", str(e), re.I) or bs == "cpu": raise
                print(f"transcribe: GPU error at batch {bs} ({e}), retrying smaller", flush=True)
                _tts = _asr = None  # TTS reloads (~20 s) on the next speech request; Whisper reloads fresh here
                import gc, torch
                gc.collect(); torch.cuda.empty_cache()
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


# Key prefix -> OpenAI-compatible endpoint. Most specific prefix first; "sk-" is shared by OpenAI and DeepSeek,
# so every matching provider is tried in order and the first that lists models wins.
PROVIDERS = [  # (name, key prefixes, base url, preferred model keywords)
    ("Google Gemini", ("AIza", "AQ."), "https://generativelanguage.googleapis.com/v1beta/openai", ("gemini-3.5-flash", "flash")),
    ("Anthropic Claude", ("sk-ant-",), "https://api.anthropic.com/v1", ("sonnet", "haiku")),
    ("OpenRouter", ("sk-or-",), "https://openrouter.ai/api/v1", ("gemini", "gpt", "claude", "deepseek")),
    ("OpenAI", ("sk-proj-", "sk-svcacct-", "sk-"), "https://api.openai.com/v1", ("gpt-5-mini", "gpt-4.1-mini", "mini", "gpt")),
    ("DeepSeek", ("sk-",), "https://api.deepseek.com/v1", ("deepseek-chat",)),
    ("xAI Grok", ("xai-",), "https://api.x.ai/v1", ("mini", "grok")),
    ("Groq", ("gsk_",), "https://api.groq.com/openai/v1", ("llama", "gpt")),
]
CPS = {"zh": 5, "ja": 7, "ko": 7, "th": 12}  # characters a voice says per second; 15 for alphabetic languages


def providers_for(key):
    return [p for p in PROVIDERS if key.startswith(p[1])]


def provider_of(base):
    return next((p for p in PROVIDERS if p[2] == (base or "").rstrip("/")), None)


def llm_headers(key, base):
    h = {"content-type": "application/json", "authorization": f"Bearer {key}"} if key else {"content-type": "application/json"}
    if "anthropic.com" in base: h.update({"x-api-key": key, "anthropic-version": "2023-06-01"})  # its /models wants these
    return h


def llm_config():
    """Settings' AI; base URL filled from the key's provider when none was saved."""
    llm = dict(settings()["llm"])
    if not llm["base_url"] and (cands := providers_for(llm["api_key"])): llm["base_url"] = cands[0][2]
    return llm


NOT_CHAT = re.compile(r"tts|image|embed|audio|live|veo|imagen|lyria|banana|whisper|dall-e|moderation|transcribe|realtime|search|customtools|aqa"
                      r"|robotics|computer-use|antigravity|genie|decision|davinci|babbage|sora|guard|rerank", re.I)


def llm_models(api_key=None, base_url=None):
    """Chat models the given (or saved) key can use, recommended first. base_url given -> only that endpoint,
    else the key's provider(s) by prefix (a new key ignores the saved URL). GET {base}/models, OpenAI-compatible."""
    llm = settings()["llm"]
    key = (api_key or llm["api_key"]).strip(); base_url = (base_url or "").strip().rstrip("/")
    if not key: raise JobError("bad_request", "Hãy dán API key")
    if base_url: cands = [provider_of(base_url) or ("Dịch vụ tự điền", (), base_url, ())]
    elif not api_key and llm["base_url"]: cands = [provider_of(llm["base_url"]) or ("Dịch vụ đã lưu", (), llm["base_url"], ())]
    else: cands = providers_for(key)
    if not cands:
        raise JobError("bad_request", "Không nhận ra key này (hỗ trợ sẵn: Gemini, OpenAI/GPT, Claude, DeepSeek, Grok, Groq, OpenRouter). "
                                      "Dịch vụ khác: điền Base URL trong Tuỳ chọn thêm")
    why = ""
    for name, _, base, prefer in cands:
        try:
            data = json.load(urllib.request.urlopen(urllib.request.Request(base + "/models", headers=llm_headers(key, base)), timeout=30)).get("data") or []
            if name == "OpenRouter":  # its model list is public: check the key itself
                urllib.request.urlopen(urllib.request.Request(base + "/key", headers=llm_headers(key, base)), timeout=30).read()
        except urllib.error.HTTPError as e:
            why = "API key không đúng hoặc không có quyền" if e.code in (400, 401, 403) else f"{name} trả lỗi HTTP {e.code}"; continue
        except Exception as e:
            why = f"Không kết nối được {name}: {e}"; continue
        ids = {m["id"].removeprefix("models/") for m in data if isinstance(m, dict) and m.get("id")} - {""}
        bucket = lambda i: next((k for k, w in enumerate(prefer) if w in i), len(prefer))  # noqa: E731
        ids = sorted((i for i in ids if not NOT_CHAT.search(i)), reverse=True)  # newest version first...
        return {"provider": name, "base_url": base, "models": sorted(ids, key=bucket)}  # ...within each preferred group
    raise JobError("llm_failed", why)


def llm_test(model):
    """One tiny request with the saved key: is this model usable right now? -> (ok, message)"""
    llm = llm_config(); llm["model"] = model or llm["model"]
    body = json.dumps({"model": llm["model"], "messages": [{"role": "user", "content": "Reply with: ok"}]}).encode()
    req = urllib.request.Request(llm["base_url"].rstrip("/") + "/chat/completions", body, llm_headers(llm["api_key"], llm["base_url"]))
    t = time.time()
    try: urllib.request.urlopen(req, timeout=45).read()  # gemini-3.5-flash takes ~25 s even for one word
    except urllib.error.HTTPError as e:
        if e.code in (429, 503): return True, "Model dùng được nhưng đang quá tải, có thể chậm"
        return False, f"Model này không dùng được với key (HTTP {e.code}), hãy chọn model khác"
    except Exception as e:
        if "timed out" in str(e): return False, "Model không trả lời trong 45 s (đang quá tải?): thử lại sau hoặc chọn model khác"
        return False, f"Không kết nối được máy chủ AI: {e}"
    return True, f"Model trả lời sau {time.time() - t:.1f} s"


def _llm_call(llm, prompt, n):
    payload = {"model": llm["model"], "temperature": 0.3, "messages": [{"role": "user", "content": prompt}]}
    url = llm["base_url"].rstrip("/") + ("" if llm["base_url"].rstrip("/").endswith("/chat/completions") else "/chat/completions")
    for attempt in range(5):  # Gemini answers 429/503 "high demand" often; they clear within seconds
        req = urllib.request.Request(url, json.dumps(payload).encode(), llm_headers(llm["api_key"], llm["base_url"]))
        try:
            out = json.load(urllib.request.urlopen(req, timeout=180))["choices"][0]["message"]["content"]
            m = re.search(r"\[.*\]", out, re.S)
            try: arr = json.loads(m.group(0)) if m else None
            except json.JSONDecodeError: arr = None
            if isinstance(arr, list) and len(arr) == n: return [str(x).strip() for x in arr]
            why = "AI trả lời sai định dạng"
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")
            if e.code == 400 and "temperature" in detail and "temperature" in payload:
                payload.pop("temperature"); continue  # newer Claude / GPT-5 models refuse it: resend without
            if e.code in (400, 401, 403, 404):
                try: detail = json.loads(detail)["error"]["message"]
                except Exception: detail = detail[:200]
                raise JobError("llm_failed", f"AI dịch từ chối (HTTP {e.code}): {detail}")
            why = f"HTTP {e.code}"
        except Exception as e:  # timeouts, connection resets
            why = str(e)
        time.sleep(3 * 2 ** attempt)
    raise JobError("llm_failed", f"AI dịch lỗi sau 5 lần thử: {why}")


def translate_llm(lines, src, dst, progress=None):
    """lines = [{"text","seconds"}]; OpenAI-compatible chat API from Settings. 60 lines per request, 4 at once."""
    from concurrent.futures import ThreadPoolExecutor
    llm = llm_config()
    if not (llm["base_url"] and llm["model"]): raise JobError("llm_not_configured", "Chưa cài AI dịch. Vào Cài đặt → Dịch bằng AI.")
    cps = CPS.get(dst, 15)

    def one(start):
        part = lines[start:start + 60]
        before = " ".join(l["text"] for l in lines[max(0, start - 3):start])
        numbered = "\n".join(f"{i + 1}. [{l['seconds']:.1f}s, max {max(4, round(l['seconds'] * cps))} chars] {l['text']}" for i, l in enumerate(part))
        prompt = (f"You translate a video's dubbing script from {LANG_EN.get(src, src)} to {LANG_EN.get(dst, dst)}. "
                  "Each line is spoken in the given seconds, so keep it within its character limit: natural spoken words, "
                  "same meaning, shorter wording when needed, no notes or brackets. Keep names, numbers and terms consistent. "
                  + (f"The script just before: \"{before}\". " if before else "")
                  + f"Answer ONLY a JSON array of {len(part)} strings, one per line, in order.\n\n{numbered}")
        return _llm_call(llm, prompt, len(part))

    starts = list(range(0, len(lines), 60)); out = {}
    with ThreadPoolExecutor(4) as ex:
        for k, (st, arr) in enumerate(zip(starts, ex.map(one, starts))):
            out[st] = arr
            if progress: progress((k + 1) / len(starts))
    return [t for st in starts for t in out[st]]
