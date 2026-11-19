"""VoiceClone Studio engine (HTTP API). Contract: ../docs/API.md

Run: python -m uvicorn server:app --app-dir engine --host 127.0.0.1 --port 3910
Env: VC_DATA (data dir), VC_PORT, VC_PARENT_PID (exit when the desktop shell dies), VC_FFMPEG/VC_FFPROBE.
"""
import json, os, re, shutil, tempfile, threading, time, uuid

import numpy as np
import soundfile as sf
from fastapi import Body, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, Response

import core, jobs
import license as lic
from core import D, SR, JobError
from textplan import fit_plan, parse_book, plan_book

app = FastAPI(title="VoiceClone Studio engine", version=core.VERSION)
# The UI is loaded from file:// in Electron (origin "null"); only this machine can reach 127.0.0.1.
app.add_middleware(CORSMiddleware, allow_origins=["null", "http://127.0.0.1:3910", "http://localhost:3910"], allow_origin_regex=r"http://127\.0\.0\.1:\d+",
                   allow_methods=["*"], allow_headers=["*"], expose_headers=["x-take-id", "x-audio-seconds", "x-gen-time", "x-design-id"])


def err(status, code, message):
    raise HTTPException(status, {"error": code, "message": message})


@app.exception_handler(HTTPException)
def _http_error(_, e: HTTPException):
    return JSONResponse(e.detail if isinstance(e.detail, dict) else {"error": "http", "message": str(e.detail)}, status_code=e.status_code)


@app.exception_handler(JobError)
def _job_error(_, e: JobError):
    status = {"model_missing": 409, "argos_pack_missing": 409, "gpu_oom": 503, "llm_not_configured": 409}.get(e.code, 400)
    return JSONResponse({"error": e.code, "message": e.message}, status_code=status)


def new_id():
    return uuid.uuid4().hex[:10]


def safe_id(x):
    if not re.fullmatch(r"[0-9a-f]{6,12}", x or ""): err(404, "not_found", "Không tìm thấy")
    return x


async def save_upload(up: UploadFile, dest_noext):
    ext = (os.path.splitext(up.filename or "")[1] or ".bin").lower()
    if not re.fullmatch(r"\.[a-z0-9]{1,5}", ext): ext = ".bin"
    path = dest_noext + ext
    with open(path, "wb") as f:
        while chunk := await up.read(1 << 20): f.write(chunk)
    if os.path.getsize(path) == 0: os.remove(path); err(400, "empty_file", "File rỗng")
    return path


# ---------- licence ----------
def licence():
    try: return lic.verify(open(core.LICENSE_FILE, encoding="ascii").read())
    except (OSError, ValueError): return None


def need(feature):
    p = licence()
    if not p: err(402, "license_required", "Cần license key để dùng tính năng này")
    if feature not in p.get("features", []): err(402, "feature_not_licensed", f"License hiện tại không gồm tính năng này ({feature})")


@app.post("/license")
def set_licence(key: str = Body(..., embed=True)):
    try: p = lic.verify(key)
    except ValueError as e: err(400, "invalid_key", str(e).capitalize())
    open(core.LICENSE_FILE, "w", encoding="ascii").write(key.strip())
    return {"ok": True, "license": p}


@app.delete("/license")
def clear_licence():
    if os.path.exists(core.LICENSE_FILE): os.remove(core.LICENSE_FILE)
    return {"ok": True}


# ---------- system ----------
@app.get("/health")
def health():
    import torch
    g = None
    if torch.cuda.is_available():
        free, total = torch.cuda.mem_get_info()
        g = {"name": torch.cuda.get_device_name(0), "free_mb": free // 2**20, "total_mb": total // 2**20, **core.vram()}
    dev = core.device(); p = licence()
    return {"status": "ok", "version": core.VERSION, "device": dev, "gpu": g, "licensed": bool(p), "license": p,
            "models_ready": core.models_ready(), **core.loaded(),
            "warning": None if dev == "cuda" else "Đang chạy bằng CPU (không có GPU NVIDIA hoặc đã chọn CPU): tạo giọng chậm hơn nhiều lần"}


@app.get("/settings")
def get_settings():
    s = core.settings(); llm = s["llm"]
    return {**{k: s[k] for k in ("device", "quality", "asr_model")}, "data_dir": core.DATA,
            "llm": {"base_url": llm["base_url"], "model": llm["model"], "has_key": bool(llm["api_key"])}}


@app.patch("/settings")
def patch_settings(body: dict = Body(...)):
    s = core.settings(); before = (s["device"], s["asr_model"])
    if body.get("device") in ("auto", "cuda", "cpu"): s["device"] = body["device"]
    if body.get("quality") in core.QUALITY_STEPS: s["quality"] = body["quality"]
    if body.get("asr_model") in ("large-v3", "small"): s["asr_model"] = body["asr_model"]
    if isinstance(body.get("llm"), dict):
        for k in ("base_url", "model", "api_key"):
            if isinstance(body["llm"].get(k), str): s["llm"][k] = body["llm"][k].strip()
    core.save_settings(s)
    if (s["device"], s["asr_model"]) != before: core.unload()  # reloads on the next request with the new choice
    return get_settings()


@app.post("/model/unload")
def unload():
    core.unload(); return {"ok": True}


@app.get("/languages")
def languages():
    l = [{"code": c, "name": n} for c, n, _ in core.LANGS]
    return {"tts": l, "translation": l}


@app.get("/jobs")
def list_jobs(limit: int = 20):
    return {"jobs": jobs.recent(limit)}


@app.get("/jobs/{job_id}")
def get_job(job_id: str):
    j = jobs.get(job_id)
    if not j: err(404, "job_not_found", "Không còn tác vụ này (engine đã khởi động lại?)")
    return j.view()


@app.get("/models")
def models():
    return {"models": core.models_view(), "translation_packs": core.argos_packs()}


@app.post("/models/{mid}/download")
def model_download(mid: str):
    if mid not in core.MODELS: err(404, "not_found", "Không có model này")
    return jobs.start("model_download", core.download_model, mid, lane="io")


@app.post("/translation/packs")
def pack_install(body: dict = Body(...)):
    src, dst = body.get("from"), body.get("to")
    if src not in core.LANG_NAME or dst not in core.LANG_NAME: err(400, "bad_request", "Ngôn ngữ không hợp lệ")
    return jobs.start("translation_pack", core.install_argos, src, dst, lane="io")


# ---------- voices ----------
def voice_file(vid): return os.path.join(D["voices"], safe_id(vid), "voice.json")


def get_voice(key):
    """By id, or by name (case-insensitive) so scripts can say [voice:Lan]."""
    if re.fullmatch(r"[0-9a-f]{6,12}", key or "") and os.path.exists(voice_file(key)): return core.read_json(voice_file(key))
    for v in all_voices(True):
        if v["name"].lower() == (key or "").strip().lower(): return v
    raise JobError("voice_not_found", f"Không có giọng '{key}'")


def all_voices(include_auto=False):
    vs = [core.read_json(os.path.join(D["voices"], d, "voice.json")) for d in os.listdir(D["voices"])]
    vs = [v for v in vs if v and (include_auto or v.get("kind") != "auto")]
    return sorted(vs, key=lambda v: v["created"], reverse=True)


def make_voice(name, src, kind="clone", ref_text=None, language=None, start=None, dur=None, instruct=None):
    vid = new_id(); d = os.path.join(D["voices"], vid); os.makedirs(d)
    try:
        a = core.load_mono(src, start=start, dur=dur or 15)  # the model clones best from 3-15 s of clean speech
        if len(a) < SR * 2: raise JobError("too_short", "Mẫu giọng cần ít nhất 2 giây có tiếng nói")
        peak = float(np.max(np.abs(a)) or 1); a = a / peak * 0.9 if peak > 0.01 else a
        ref = os.path.join(d, "ref.wav"); sf.write(ref, a, SR)
        if not ref_text:
            tr = core.transcribe(ref)  # always auto-detect: forcing a language makes Whisper translate instead of transcribe
            ref_text, language = tr["text"], tr["language"]
        if not ref_text.strip(): raise JobError("no_speech", "Không nghe thấy lời nói trong mẫu")
        v = {"id": vid, "name": (name or "Giọng mới").strip()[:80], "kind": kind, "language": language, "ref_text": ref_text.strip(),
             "seconds": round(len(a) / SR, 2), "instruct": instruct, "created": time.time(), "tags": []}
        core.write_json(os.path.join(d, "voice.json"), v)
        return v
    except BaseException:
        shutil.rmtree(d, ignore_errors=True); raise


@app.get("/voices")
def list_voices():
    return {"voices": all_voices()}


@app.post("/voices")
async def create_voice(name: str = Form(...), audio: UploadFile = File(...), ref_text: str | None = Form(None), language: str | None = Form(None)):
    need("clone")
    with tempfile.TemporaryDirectory() as t:
        src = await save_upload(audio, os.path.join(t, "src"))
        return make_voice(name, src, "clone", ref_text, language or None)


@app.get("/voices/{vid}")
def voice_detail(vid: str):
    v = core.read_json(voice_file(vid))
    if not v: err(404, "voice_not_found", "Không có giọng này")
    return v


@app.get("/voices/{vid}/sample")
def voice_sample(vid: str):
    p = os.path.join(D["voices"], safe_id(vid), "ref.wav")
    if not os.path.exists(p): err(404, "voice_not_found", "Không có giọng này")
    return FileResponse(p, media_type="audio/wav")


@app.patch("/voices/{vid}")
def voice_patch(vid: str, body: dict = Body(...)):
    v = voice_detail(vid)
    if isinstance(body.get("name"), str) and body["name"].strip(): v["name"] = body["name"].strip()[:80]
    if isinstance(body.get("tags"), list): v["tags"] = [str(t)[:30] for t in body["tags"]][:10]
    core.write_json(voice_file(vid), v); return v


@app.delete("/voices/{vid}")
def voice_delete(vid: str):
    voice_detail(vid); core.forget_voice(vid); shutil.rmtree(os.path.join(D["voices"], vid)); return {"ok": True}


@app.post("/design/preview")
def design_preview(body: dict = Body(...)):
    need("clone")
    text = (body.get("text") or "").strip()[:600]; instruct = (body.get("instruct") or "").strip()
    if not text: err(400, "empty", "Nhập câu để nghe thử")
    t0 = time.time()
    try: a = core.generate(text, None, instruct=instruct or None, language=body.get("language"))
    finally: core.release_cache()
    did = new_id(); sf.write(os.path.join(D["designs"], did + ".wav"), a, SR)
    core.write_json(os.path.join(D["designs"], did + ".json"), {"instruct": instruct, "text": text, "language": body.get("language")})
    for f in sorted(os.listdir(D["designs"]))[:-40]: os.remove(os.path.join(D["designs"], f))  # keep the last previews only
    return Response(core.wav_bytes(a), media_type="audio/wav",
                    headers={"x-design-id": did, "x-audio-seconds": f"{len(a) / SR:.2f}", "x-gen-time": f"{time.time() - t0:.2f}"})


@app.post("/design/save")
def design_save(body: dict = Body(...)):
    need("clone")
    did = safe_id(body.get("design_id")); meta = core.read_json(os.path.join(D["designs"], did + ".json"))
    if not meta: err(404, "not_found", "Bản nghe thử đã hết hạn, bấm Nghe thử lại")
    return make_voice(body.get("name") or "Giọng thiết kế", os.path.join(D["designs"], did + ".wav"), "design",
                      meta["text"], meta.get("language"), instruct=meta["instruct"])


# ---------- speech ----------
def do_speech(text, voice_key, language=None, speed=None, quality=None):
    need("tts")
    text = (text or "").strip()
    if not text: err(400, "empty", "Chưa có chữ để đọc")
    if len(text) > 20000: err(400, "too_long", "Văn bản quá dài (tối đa 20.000 ký tự); dùng Sách nói cho văn bản dài")
    v = get_voice(voice_key); t0 = time.time()
    a = core.speak(text, v, language or None, speed, quality)
    tid = new_id(); dt = time.time() - t0
    sf.write(os.path.join(D["takes"], tid + ".wav"), a, SR)
    core.write_json(os.path.join(D["takes"], tid + ".json"), {"id": tid, "text": text, "voice": v["id"], "voice_name": v["name"],
                    "language": language, "seconds": round(len(a) / SR, 2), "gen_time": round(dt, 2), "created": time.time()})
    return Response(core.wav_bytes(a), media_type="audio/wav",
                    headers={"x-take-id": tid, "x-audio-seconds": f"{len(a) / SR:.2f}", "x-gen-time": f"{dt:.2f}"})


@app.post("/speech")
def speech(body: dict = Body(...)):
    sp = body.get("speed"); sp = min(1.4, max(0.7, float(sp))) if sp else None
    return do_speech(body.get("text"), body.get("voice"), body.get("language"), sp, body.get("quality"))


@app.post("/v1/audio/speech")
def openai_speech(body: dict = Body(...)):
    return do_speech(body.get("input"), body.get("voice"), body.get("language"), body.get("speed"))


@app.get("/v1/audio/voices")
def openai_voices():
    return {"voices": [{"filename": v["id"], "display_name": v["name"]} for v in all_voices()]}


@app.get("/v1/models")
def openai_models():
    return {"object": "list", "data": []}  # Kaiser's Chatterbox provider then lists /v1/audio/voices


@app.get("/takes")
def takes(limit: int = 50):
    items = [core.read_json(os.path.join(D["takes"], f)) for f in os.listdir(D["takes"]) if f.endswith(".json")]
    return {"takes": sorted([t for t in items if t], key=lambda t: t["created"], reverse=True)[:limit]}


@app.get("/takes/{tid}/audio")
def take_audio(tid: str):
    p = os.path.join(D["takes"], safe_id(tid) + ".wav")
    if not os.path.exists(p): err(404, "not_found", "Không còn bản này")
    return FileResponse(p, media_type="audio/wav", filename=f"take_{tid}.wav")


@app.delete("/takes/{tid}")
def take_delete(tid: str):
    for ext in (".wav", ".json"):
        p = os.path.join(D["takes"], safe_id(tid) + ext)
        if os.path.exists(p): os.remove(p)
    return {"ok": True}


# ---------- transcribe ----------
def _transcribe_job(job, path, name, language):
    job.update(0.1, "Đang chép lời (lần đầu phải nạp model, ~1 phút)…")
    tr = core.transcribe(path, language)
    tid = new_id(); rec = {"id": tid, "file_name": name, "created": time.time(), **tr}
    core.write_json(os.path.join(D["transcriptions"], tid + ".json"), rec)
    shutil.rmtree(os.path.dirname(path), ignore_errors=True)
    return rec


@app.post("/transcriptions")
async def transcription_create(file: UploadFile = File(...), language: str | None = Form(None)):
    need("tts")
    t = tempfile.mkdtemp(dir=D["transcriptions"]); path = await save_upload(file, os.path.join(t, "in"))
    core.probe(path)
    return jobs.start("transcription", _transcribe_job, path, file.filename or "audio", language or None)


@app.get("/transcriptions")
def transcription_list():
    items = [core.read_json(os.path.join(D["transcriptions"], f)) for f in os.listdir(D["transcriptions"]) if f.endswith(".json")]
    items = sorted([i for i in items if i], key=lambda i: i["created"], reverse=True)
    return {"items": [{k: i.get(k) for k in ("id", "file_name", "language", "seconds", "created")} | {"text": i["text"][:200]} for i in items]}


def transcription_get(tid):
    rec = core.read_json(os.path.join(D["transcriptions"], safe_id(tid) + ".json"))
    if not rec: err(404, "not_found", "Không còn bản chép lời này")
    return rec


app.get("/transcriptions/{tid}")(transcription_get)


def _ts(t, sep):
    h, rem = divmod(t, 3600); m, s = divmod(rem, 60)
    return f"{int(h):02d}:{int(m):02d}:{int(s):02d}{sep}{int(round((s - int(s)) * 1000)):03d}"


def subtitles(segs, fmt):
    if fmt == "txt": return "\n".join(s["text"] for s in segs) + "\n"
    sep = "," if fmt == "srt" else "."
    cues = [(f"{i + 1}\n" if fmt == "srt" else "") + f"{_ts(s['start'], sep)} --> {_ts(s['end'], sep)}\n{s['text']}\n" for i, s in enumerate(segs)]
    return ("WEBVTT\n\n" if fmt == "vtt" else "") + "\n".join(cues)


@app.get("/transcriptions/{tid}/export")
def transcription_export(tid: str, format: str = "txt"):
    if format not in ("txt", "srt", "vtt"): err(400, "bad_request", "Định dạng phải là txt, srt hoặc vtt")
    rec = transcription_get(tid); base = os.path.splitext(rec["file_name"])[0] or "transcript"
    return PlainTextResponse(subtitles(rec["segments"], format), media_type="text/plain; charset=utf-8",
                             headers={"content-disposition": f"attachment; filename*=UTF-8''{__import__('urllib.parse').parse.quote(base)}.{format}"})


@app.delete("/transcriptions/{tid}")
def transcription_delete(tid: str):
    p = os.path.join(D["transcriptions"], safe_id(tid) + ".json")
    if os.path.exists(p): os.remove(p)
    return {"ok": True}


@app.post("/v1/audio/transcriptions")
async def openai_transcribe(file: UploadFile = File(...), language: str | None = Form(None)):
    need("tts")
    with tempfile.TemporaryDirectory() as t:
        return core.transcribe(await save_upload(file, os.path.join(t, "in")), language or None)


# ---------- dub ----------
def pdir(pid): return os.path.join(D["dub"], safe_id(pid))


def project(pid):
    p = core.read_json(os.path.join(pdir(pid), "project.json"))
    if not p: err(404, "project_not_found", "Không còn dự án lồng tiếng này")
    return p


def save_project(p):
    core.write_json(os.path.join(pdir(p["id"]), "project.json"), p); return p


def _dub_prepare(job, p, src):
    d = pdir(p["id"]); info = core.probe(src)
    p.update(duration=round(info["duration"], 2), has_video=info["has_video"]); save_project(p)
    job.update(0.1, "Đang tách âm thanh…")
    mix = os.path.join(d, "mix.wav"); core.ffmpeg("-i", src, "-vn", "-ac", "2", "-ar", "44100", mix)
    speech = mix
    if core.model_path("separator"):
        job.update(0.2, "Đang tách giọng nói khỏi nhạc nền…")
        speech = core.separate(mix, d)[0]; p["separated"] = True
    else:
        p["separated"] = False
    job.update(0.5, "Đang chép lời (lần đầu phải nạp model)…")
    tr = core.transcribe(speech, p["source_lang"] if p["source_lang"] != "auto" else None)
    p["source_lang"] = tr["language"] if p["source_lang"] == "auto" else p["source_lang"]
    p["segments"] = [dict(s, speaker="1", translation="", fit=None) for s in tr["segments"]]
    if not p["segments"]: raise JobError("no_speech", "Không nghe thấy lời nói trong file")
    p["status"] = "transcribed"; return save_project(p)


@app.post("/dub")
async def dub_create(file: UploadFile = File(...), source_lang: str | None = Form(None), target_lang: str = Form("vi")):
    need("dub")
    pid = new_id(); d = os.path.join(D["dub"], pid); os.makedirs(d)
    src = await save_upload(file, os.path.join(d, "source"))
    p = save_project({"id": pid, "name": os.path.splitext(file.filename or "Video")[0][:80], "source_lang": source_lang or "auto",
                      "target_lang": target_lang, "status": "new", "segments": [], "voice": None, "keep_background": True,
                      "has_video": False, "duration": 0, "output": None, "created": time.time(), "source_file": os.path.basename(src)})
    return jobs.start("dub_prepare", _dub_prepare, p, src)


@app.get("/dub")
def dub_list():
    ps = [core.read_json(os.path.join(D["dub"], d, "project.json")) for d in os.listdir(D["dub"])]
    return {"projects": [{k: v for k, v in p.items() if k != "segments"} for p in sorted([p for p in ps if p], key=lambda p: p["created"], reverse=True)]}


app.get("/dub/{pid}")(project)


@app.patch("/dub/{pid}")
def dub_patch(pid: str, body: dict = Body(...)):
    p = project(pid); by_id = {s["id"]: s for s in p["segments"]}
    for s in body.get("segments") or []:
        if s.get("id") in by_id and isinstance(s.get("translation"), str): by_id[s["id"]]["translation"] = s["translation"].strip()
    if "voice" in body: p["voice"] = body["voice"] or None
    for k in ("keep_background",):
        if isinstance(body.get(k), bool): p[k] = body[k]
    if body.get("target_lang") in core.LANG_NAME: p["target_lang"] = body["target_lang"]
    if isinstance(body.get("name"), str) and body["name"].strip(): p["name"] = body["name"].strip()[:80]
    if any(s["translation"] for s in p["segments"]) and p["status"] == "transcribed": p["status"] = "translated"
    return save_project(p)


@app.delete("/dub/{pid}")
def dub_delete(pid: str):
    p = project(pid)
    if p.get("auto_voice"):
        shutil.rmtree(os.path.join(D["voices"], p["auto_voice"]), ignore_errors=True); core.forget_voice(p["auto_voice"])
    shutil.rmtree(pdir(pid)); return {"ok": True}


def _dub_translate(job, pid, engine):
    p = project(pid); segs = p["segments"]
    job.update(0.1, f"Đang dịch {len(segs)} câu…")
    if engine == "llm":
        out = core.translate_llm([{"text": s["text"], "seconds": s["end"] - s["start"]} for s in segs], p["source_lang"], p["target_lang"])
    else:
        out = core.translate_argos([s["text"] for s in segs], p["source_lang"], p["target_lang"])
    for s, t in zip(segs, out): s["translation"] = t
    p["status"] = "translated"; return save_project(p)


@app.post("/dub/{pid}/translate")
def dub_translate(pid: str, body: dict = Body(default={})):
    need("dub"); p = project(pid)
    if p["source_lang"] == p["target_lang"]: err(400, "same_language", "Ngôn ngữ gốc và ngôn ngữ lồng tiếng đang giống nhau")
    return jobs.start("dub_translate", _dub_translate, pid, "llm" if body.get("engine") == "llm" else "argos", lane="io")


def _auto_voice(p):
    """Keeps the original speaker's voice: the longest clean lines, up to ~12 s, become the reference."""
    if p.get("auto_voice") and os.path.exists(voice_file(p["auto_voice"])): return core.read_json(voice_file(p["auto_voice"]))
    d = pdir(p["id"]); speech = os.path.join(d, "vocals.wav") if p.get("separated") else os.path.join(d, "mix.wav")
    segs = sorted(p["segments"], key=lambda s: s["end"] - s["start"], reverse=True)
    best = segs[0]; start = best["start"]; end = min(best["end"], start + 12)
    picked = [s for s in sorted(p["segments"], key=lambda s: s["start"]) if s["start"] >= start and s["end"] <= end + 0.05] or [best]
    v = make_voice("Giọng gốc · " + p["name"], speech, "auto", " ".join(s["text"] for s in picked), p["source_lang"],
                   start=max(0, start - 0.1), dur=end - start + 0.2)
    p["auto_voice"] = v["id"]; return v


def _dub_render(job, pid, strategy):
    p = project(pid); d = pdir(pid)
    lines = [s for s in p["segments"] if s.get("translation", "").strip()]
    if not lines: raise JobError("no_translation", "Chưa có câu dịch nào. Điền bản dịch hoặc bấm Dịch tự động.")
    job.update(0.03, "Đang chuẩn bị giọng…")
    voice = get_voice(p["voice"]) if p["voice"] else _auto_voice(p)
    lang = p["target_lang"]; dur = p["duration"]
    clips, overflow_total = [], 0.0
    for i, s in enumerate(lines):
        job.update(0.05 + 0.8 * i / len(lines), f"Đang lồng câu {i + 1}/{len(lines)}…")
        nxt = lines[i + 1]["start"] if i + 1 < len(lines) else dur
        a = core.generate(s["translation"], voice, language=lang)
        natural = len(a) / SR; slot = max(0.3, nxt - s["start"])
        if strategy == "stretch":
            plan = {"speed": 1.0, "status": "fits" if natural <= slot else "overflow"}
        else:
            plan = fit_plan(natural, s["start"], nxt, max_speed=1.35 if strategy == "smart_fit" else 1.8)
            if plan["speed"] > 1:  # re-say it faster with the model instead of time-stretching the audio
                a = core.generate(s["translation"], voice, language=lang, duration=round(natural / plan["speed"], 2))
        s["fit"] = plan["status"]
        clips.append((s, a)); overflow_total += max(0.0, len(a) / SR - slot)
    # stretch: slow the whole video so every line fits; others keep the video length
    factor = 1.0
    if strategy == "stretch":
        need_s = sum(max(len(a) / SR, max(0.3, (lines[i + 1]["start"] if i + 1 < len(lines) else dur) - s["start"])) for i, (s, a) in enumerate(clips))
        span = dur - lines[0]["start"]
        factor = max(1.0, min(2.0, (lines[0]["start"] + need_s) / dur if span > 0 else 1.0))
    total = dur * factor
    track = np.zeros(int(SR * (total + 30)), np.float32); cursor = 0
    for s, a in clips:
        at = max(int(s["start"] * factor * SR), cursor if strategy == "stretch" else 0)
        track[at:at + len(a)] += a[: max(0, len(track) - at)]; cursor = at + len(a)
    end_s = max(total, cursor / SR); track = np.clip(track[: int(end_s * SR)], -1, 1)
    core.release_cache()
    job.update(0.88, "Đang trộn âm thanh và xuất video…")
    dub_wav = os.path.join(d, "dub.wav"); sf.write(dub_wav, track, SR)
    src = os.path.join(d, p["source_file"])
    bg = os.path.join(d, "background.wav") if p.get("separated") else None
    inputs, filt = ["-i", src, "-i", dub_wav], []
    if p["keep_background"] and bg:
        inputs += ["-i", bg]; tempo = "" if factor == 1 else atempo(1 / factor) + ","
        filt = [f"[2:a]{tempo}volume=1.0[bg];[1:a]aresample=44100,volume=1.0[v];[v][bg]amix=inputs=2:duration=longest:normalize=0[a]"]
    elif p["keep_background"]:
        tempo = "" if factor == 1 else atempo(1 / factor) + ","
        filt = [f"[0:a]{tempo}volume=0.12[bg];[1:a]aresample=44100[v];[v][bg]amix=inputs=2:duration=longest:normalize=0[a]"]
    amap = ["-map", "[a]"] if filt else ["-map", "1:a"]
    if p["has_video"]:
        out = os.path.join(d, "output.mp4")
        vf = ["-filter:v", f"setpts={factor:.5f}*PTS", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20"] if factor != 1 else ["-c:v", "copy"]
        core.ffmpeg(*inputs, *(["-filter_complex", filt[0]] if filt else []), "-map", "0:v:0", *amap, *vf, "-c:a", "aac", "-b:a", "192k",
                    "-movflags", "+faststart", out)
    else:
        out = os.path.join(d, "output.m4a")
        core.ffmpeg(*inputs, *(["-filter_complex", filt[0]] if filt else []), *amap, "-c:a", "aac", "-b:a", "192k", out)
    p.update(status="rendered", output=f"/dub/{pid}/download", output_file=os.path.basename(out), rendered=time.time(),
             stretch_factor=round(factor, 3), overflow_s=round(overflow_total, 2),
             background_note=None if (not p["keep_background"] or bg) else "Chưa có model tách nhạc nền: tiếng gốc được giữ nhỏ (vẫn nghe lẫn giọng gốc). Tải 'Demucs' trong Cài đặt → Model.")
    return save_project(p)


def atempo(f): return core.atempo_chain(f)


@app.post("/dub/{pid}/render")
def dub_render(pid: str, body: dict = Body(default={})):
    need("dub"); project(pid)
    strategy = body.get("strategy") if body.get("strategy") in ("smart_fit", "strict_slot", "stretch") else "smart_fit"
    return jobs.start("dub_render", _dub_render, pid, strategy)


@app.get("/dub/{pid}/download")
def dub_download(pid: str):
    p = project(pid)
    if not p.get("output_file"): err(404, "not_rendered", "Chưa lồng tiếng xong")
    f = os.path.join(pdir(pid), p["output_file"]); ext = os.path.splitext(f)[1]
    return FileResponse(f, media_type="video/mp4" if ext == ".mp4" else "audio/mp4", filename=f"{p['name']}.{p['target_lang']}{ext}")


@app.get("/dub/{pid}/source")
def dub_source(pid: str):
    p = project(pid); return FileResponse(os.path.join(pdir(pid), p["source_file"]))


# ---------- audiobook ----------
@app.post("/audiobook/plan")
def audiobook_plan(body: dict = Body(...)):
    items = parse_book(body.get("script") or "", body.get("voice") or "")
    pl = plan_book(items); missing = []
    for v in pl["voices"]:
        try: get_voice(v)
        except JobError: missing.append(v)
    if not pl["chapters"] and pl["words"]: pl["chapters"] = [{"title": "(Không tên)", "words": pl["words"]}]
    return {**pl, "missing_voices": missing}


def _audiobook_job(job, body):
    items = parse_book(body.get("script") or "", body.get("voice") or "")
    says = [i for i in items if "say" in i]
    if not says: raise JobError("empty", "Kịch bản trống")
    voices = {v: get_voice(v) for v in {i["voice"] for i in says}}
    gap = np.zeros(int(SR * int(body.get("paragraph_gap_ms") or 600) / 1000), np.float32)
    parts, chapters, pos, done = [], [], 0, 0
    lang = body.get("language")
    for it in items:
        if "chapter" in it: chapters.append((pos, it["chapter"])); continue
        if "say" in it:
            job.update(0.02 + 0.9 * done / len(says), f"Đang đọc câu {done + 1}/{len(says)}…")
            a = core.speak(it["say"], voices[it["voice"]], lang); done += 1
        elif "pause_ms" in it: a = np.zeros(int(SR * it["pause_ms"] / 1000), np.float32)
        else: a = gap
        parts.append(a); pos += len(a)
    audio = np.concatenate(parts); bid = new_id(); fmt = body.get("format") if body.get("format") in ("m4b", "mp3", "wav") else "m4b"
    job.update(0.95, "Đang xuất file…")
    title = (body.get("title") or "Sách nói").strip()[:120]
    out = os.path.join(D["audiobooks"], f"{bid}.{fmt}"); wav = os.path.join(D["audiobooks"], f"{bid}.tmp.wav"); sf.write(wav, audio, SR)
    if fmt == "wav":
        os.replace(wav, out)
    else:
        meta = os.path.join(D["audiobooks"], f"{bid}.ffmeta"); marks = chapters or [(0, title)]
        clean = lambda x: re.sub(r"([=;#\\\n])", r"\\\1", x)
        with open(meta, "w", encoding="utf-8") as f:
            f.write(f";FFMETADATA1\ntitle={clean(title)}\nartist={clean(body.get('author') or '')}\nalbum={clean(title)}\n")
            for k, (s, name) in enumerate(marks):
                e = marks[k + 1][0] if k + 1 < len(marks) else len(audio)
                f.write(f"[CHAPTER]\nTIMEBASE=1/{SR}\nSTART={s}\nEND={e}\ntitle={clean(name)}\n")
        codec = ["-c:a", "aac", "-b:a", "96k"] if fmt == "m4b" else ["-c:a", "libmp3lame", "-b:a", "128k", "-id3v2_version", "3"]
        try: core.ffmpeg("-i", wav, "-i", meta, "-map", "0:a", "-map_metadata", "1", "-map_chapters", "1", *codec, *(["-f", "mp4"] if fmt == "m4b" else []), out)
        finally:
            for f in (wav, meta):
                if os.path.exists(f): os.remove(f)
    rec = {"id": bid, "title": title, "author": body.get("author") or "", "format": fmt, "file_name": f"{title}.{fmt}",
           "download": f"/audiobooks/{bid}/download", "seconds": round(len(audio) / SR, 2), "created": time.time(),
           "chapters": [{"title": n, "start_s": round(s / SR, 2)} for s, n in chapters]}
    core.write_json(os.path.join(D["audiobooks"], bid + ".json"), rec)
    return rec


@app.post("/audiobook")
def audiobook(body: dict = Body(...)):
    need("audiobook")
    pl = audiobook_plan(body)
    if pl["missing_voices"]: err(400, "voice_not_found", "Kịch bản dùng giọng chưa có: " + ", ".join(pl["missing_voices"]))
    if not pl["words"]: err(400, "empty", "Kịch bản trống")
    return jobs.start("audiobook", _audiobook_job, body)


@app.get("/audiobooks")
def audiobook_list():
    items = [core.read_json(os.path.join(D["audiobooks"], f)) for f in os.listdir(D["audiobooks"]) if f.endswith(".json")]
    return {"audiobooks": sorted([i for i in items if i], key=lambda i: i["created"], reverse=True)}


def audiobook_rec(bid):
    r = core.read_json(os.path.join(D["audiobooks"], safe_id(bid) + ".json"))
    if not r: err(404, "not_found", "Không còn sách nói này")
    return r


@app.get("/audiobooks/{bid}/download")
def audiobook_download(bid: str):
    r = audiobook_rec(bid)
    mt = {"m4b": "audio/mp4", "mp3": "audio/mpeg", "wav": "audio/wav"}[r["format"]]
    return FileResponse(os.path.join(D["audiobooks"], f"{bid}.{r['format']}"), media_type=mt, filename=r["file_name"])


@app.delete("/audiobooks/{bid}")
def audiobook_delete(bid: str):
    r = audiobook_rec(bid)
    for f in (f"{bid}.{r['format']}", f"{bid}.json"):
        p = os.path.join(D["audiobooks"], f)
        if os.path.exists(p): os.remove(p)
    return {"ok": True}


# ---------- UI (browser use without Electron) ----------
UI = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ui")


@app.get("/", include_in_schema=False)
def ui_index():
    from fastapi.responses import RedirectResponse
    return RedirectResponse("/ui/index.html")


if os.path.isdir(UI):
    from fastapi.staticfiles import StaticFiles
    app.mount("/ui", StaticFiles(directory=UI), name="ui")


# ---------- exit with the desktop shell ----------
def _watch_parent(pid):
    import ctypes
    k = ctypes.windll.kernel32
    h = k.OpenProcess(0x00100000, False, pid)  # SYNCHRONIZE
    if not h: os._exit(0)
    k.WaitForSingleObject(h, 0xFFFFFFFF); os._exit(0)


if os.environ.get("VC_PARENT_PID", "").isdigit() and os.name == "nt":
    threading.Thread(target=_watch_parent, args=(int(os.environ["VC_PARENT_PID"]),), daemon=True).start()
