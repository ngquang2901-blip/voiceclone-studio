"""Where does the time go? Times each engine step in-process (close the app first so the GPU is free).

python tools/bench.py
"""
import os, sys, time
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "engine"))
os.environ["VC_WARMUP"] = "0"
import numpy as np  # noqa: E402
import core, audioclean  # noqa: E402

VOICE = core.read_json(os.path.join(core.D["voices"], "4e52cbc79d", "voice.json"))
SHORT = "Xin chào, đây là bản đo tốc độ của ứng dụng."
LONG = " ".join([
    "Trời hôm nay mưa to, đường phố ngập nước, xe cộ đi lại khó khăn.",
    "Cô giáo dặn học sinh phải chăm chỉ ôn bài trước kỳ thi cuối năm.",
    "Những chiếc lá vàng rơi xuống mặt hồ yên tĩnh vào buổi chiều thu.",
    "Anh ấy mua một cái bánh mì và hai ly cà phê sữa đá.",
    "Buổi tối, cả nhà quây quần bên mâm cơm và kể cho nhau nghe chuyện trong ngày.",
] * 3)
rows = []


def t(label, fn, audio=None):
    import torch
    if torch.cuda.is_available(): torch.cuda.synchronize()
    t0 = time.perf_counter(); r = fn()
    if torch.cuda.is_available(): torch.cuda.synchronize()
    dt = time.perf_counter() - t0
    secs = len(r) / core.SR if audio and r is not None else None
    rows.append((label, dt, secs)); print(f"{label:42s} {dt:7.2f}s" + (f"   {secs:5.1f}s audio  RTF {dt / secs:.2f}" if secs else ""), flush=True)
    return r


import torch  # noqa: E402
print("device", core.device(), torch.cuda.get_device_name(0) if torch.cuda.is_available() else "")
t("import + load OmniVoice", core.tts_model)
t("voice prompt (cached prompt.pt)", lambda: core.voice_prompt(VOICE))
t("generate short (first, warm-up)", lambda: core.generate(SHORT, VOICE, language="vi"), True)
t("generate short", lambda: core.generate(SHORT, VOICE, language="vi"), True)
for q in ("fast", "balanced", "quality"):
    t(f"generate short quality={q}", lambda: core.generate(SHORT, VOICE, language="vi", quality=q), True)
a = t(f"speak long ({len(LONG)} chars)", lambda: core.speak(LONG, VOICE, "vi"), True)
t("audioclean.clean on that audio", lambda: audioclean.clean(a, core.SR))
t("audioclean.report on that audio", lambda: audioclean.report(a, core.SR))
lines = [s.strip() + "." for s in LONG.split(".") if s.strip()][:8]
t("8 lines one by one (old dub path)", lambda: np.concatenate([core.generate(x, VOICE, language="vi") for x in lines]), True)
t("8 lines generate_many (new dub path)", lambda: np.concatenate(core.generate_many(lines, VOICE, language="vi")), True)
ref = os.path.join(core.D["voices"], VOICE["id"], "ref.wav")
t("load Whisper " + core.settings()["asr_model"], core.asr_model)
t("transcribe 9 s reference", lambda: core.transcribe(ref))
