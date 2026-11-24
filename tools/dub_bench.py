"""Time each dub stage on a longer video, to estimate long jobs. Needs the app running + licensed.

python tools/dub_bench.py [minutes]   (builds a looped copy of the e2e sample video)
"""
import json, os, subprocess, sys, time
_src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "e2e.py"), encoding="utf-8").read()
exec(_src[:_src.index("\nmade = ")])  # reuse e2e's req/ok/job/VIDEO/ROOT without running its test body
_t0, _print = time.time(), print
def print(*a, **k): _print(f"[{time.time() - _t0:7.1f}s]", *a, **k, flush=True)  # noqa: E302
sys.argv = sys.argv[:1] + [a for a in sys.argv[1:] if not a.startswith("http")]

mins = float(sys.argv[1]) if len(sys.argv) > 1 else 5
B = "http://127.0.0.1:3910"
ff = os.path.join(ROOT, "bin", "ffmpeg.exe")
src = os.path.join(os.environ.get("TMPDIR", "."), f"dub_{mins:g}min.mp4")
if not os.path.exists(src):
    subprocess.run([ff, "-y", "-v", "error", "-stream_loop", "-1", "-i", VIDEO, "-t", str(mins * 60), "-c", "copy", src], check=True)

T = {}
t = time.time()
p = job(ok(*req("POST", "/dub", {"source_lang": "en", "target_lang": "vi"}, {"file": ("long.mp4", open(src, "rb").read())})[::2]))
T["tải lên + tách nhạc + chép lời"] = time.time() - t
t = time.time(); p = job(ok(*req("POST", f"/dub/{p['id']}/translate", {"engine": os.environ.get("DUB_ENGINE", "llm")})[::2])); T["dịch"] = time.time() - t
t = time.time(); r = job(ok(*req("POST", f"/dub/{p['id']}/render", {"strategy": "smart_fit"})[::2])); T["đọc lồng tiếng + xuất video"] = time.time() - t
fits = [s.get("fit") for s in (r.get("segments") or [])]
print(json.dumps({"minutes": mins, "segments": len(p["segments"]), "sped_up": fits.count("sped_up"), "overflow": fits.count("overflow"),
                  "stages_s": {k: round(v, 1) for k, v in T.items()}, "total_s": round(sum(T.values()), 1)}, ensure_ascii=False))
for x in r["segments"][:6]: print(f"{x['start']:6.1f} {x['text'][:60]!r} -> {x['translation'][:70]!r} [{x.get('fit')}]")
req("DELETE", f"/dub/{p['id']}")
