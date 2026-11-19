"""End-to-end check of a running engine against docs/API.md. Stdlib only.

    VC_TEST_KEY=<licence key> python tools/e2e.py [base_url]
Uses sample media from ../analysis/probe (sample.wav, source.mp4). Cleans up what it creates.
"""
import json, os, sys, time, uuid, urllib.error, urllib.request

B = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:3910"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROBE = os.path.join(ROOT, "..", "analysis", "probe")
SAMPLE, VIDEO = os.path.join(PROBE, "gen", "sample.wav"), os.path.join(PROBE, "dub", "source.mp4")
OUT = os.path.join(ROOT, "test-out"); os.makedirs(OUT, exist_ok=True)


def req(method, path, body=None, files=None, timeout=900):
    headers, data = {}, None
    if files is not None:
        bnd = uuid.uuid4().hex; parts = []
        for k, v in (body or {}).items():
            parts.append(f'--{bnd}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode())
        for k, (fn, blob) in files.items():
            parts.append(f'--{bnd}\r\nContent-Disposition: form-data; name="{k}"; filename="{fn}"\r\nContent-Type: application/octet-stream\r\n\r\n'.encode() + blob + b"\r\n")
        data = b"".join(parts) + f"--{bnd}--\r\n".encode(); headers["content-type"] = f"multipart/form-data; boundary={bnd}"
    elif body is not None:
        data = json.dumps(body).encode(); headers["content-type"] = "application/json"
    try:
        r = urllib.request.urlopen(urllib.request.Request(B + path, data, headers, method=method), timeout=timeout)
        return r.status, r.headers, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.headers, e.read()


def ok(c, b, want=200):
    assert c == want, (c, b[:400])
    return json.loads(b) if b[:1] in (b"{", b"[") else b


def job(start, timeout=1800):
    jid = start["job_id"]; t0 = time.time(); last = None
    while time.time() - t0 < timeout:
        j = ok(*req("GET", f"/jobs/{jid}")[::2])
        if j["message"] != last: print(f"     … {j['progress']:.0%} {j['message']}"); last = j["message"]
        if j["status"] == "done": return j["result"]
        if j["status"] == "error": raise AssertionError(j["error"])
        time.sleep(0.7)
    raise AssertionError("job timeout")


def step(name, fn):
    t = time.time(); r = fn(); print(f"[OK] {name} ({time.time() - t:.1f} s) {r if isinstance(r, str) else ''}"); return r


made = {"voices": [], "dub": [], "audiobooks": [], "takes": [], "transcriptions": []}
try:
    req("DELETE", "/license")
    c, _, b = req("POST", "/speech", {"text": "x", "voice": "x"}); assert c == 402, (c, b); print("[OK] không key -> 402")
    c, _, b = req("POST", "/license", {"key": "abc.def"}); assert c == 400, (c, b); print("[OK] key rác -> 400")
    lic = ok(*req("POST", "/license", {"key": os.environ["VC_TEST_KEY"]})[::2]); print("[OK] kích hoạt key:", lic["license"]["sub"])

    def models():
        m = ok(*req("GET", "/models")[::2])
        if not next(x for x in m["models"] if x["id"] == "separator")["installed"]:
            job(ok(*req("POST", "/models/separator/download")[::2]))
        m = ok(*req("GET", "/models")[::2]); return " ".join(f"{x['id']}={'có' if x['installed'] else 'chưa'}" for x in m["models"])
    step("model (tải Demucs nếu chưa có)", models)

    def clone():
        v = ok(*req("POST", "/voices", {"name": "E2E Giọng mẫu"}, {"audio": ("sample.wav", open(SAMPLE, "rb").read())})[::2])
        made["voices"].append(v["id"]); assert v["ref_text"] and v["seconds"] >= 2; return v
    v = step("clone giọng", clone)

    def design():
        c, h, b = req("POST", "/design/preview", {"instruct": "female, young adult, moderate pitch", "text": "Xin chào, tôi là giọng được thiết kế.", "language": "vi"})
        assert c == 200 and b[:4] == b"RIFF", (c, b[:300])
        c, _, b = req("POST", "/design/preview", {"instruct": "femail", "text": "x"}); assert c == 400, (c, b)
        dv = ok(*req("POST", "/design/save", {"design_id": h["x-design-id"], "name": "E2E Thiết kế"})[::2]); made["voices"].append(dv["id"])
        assert dv["kind"] == "design"; return f"{h['x-audio-seconds']} s, lưu {dv['id']}"
    step("thiết kế giọng + lưu", design)

    def speech():
        c, h, b = req("POST", "/speech", {"text": "Xin chào, đây là ứng dụng nhân bản giọng nói chạy ngay trên máy của bạn.", "voice": v["id"], "language": "vi", "speed": 1.1})
        assert c == 200 and b[:4] == b"RIFF", (c, b[:300]); made["takes"].append(h["x-take-id"])
        open(os.path.join(OUT, "speech.wav"), "wb").write(b)
        t = ok(*req("GET", "/takes")[::2])["takes"]; assert t[0]["id"] == h["x-take-id"]
        c, _, a = req("GET", f"/takes/{h['x-take-id']}/audio"); assert c == 200 and a == b
        c, _, b2 = req("POST", "/v1/audio/speech", {"input": "Thử kiểu OpenAI.", "voice": "E2E Giọng mẫu"}); assert c == 200
        made["takes"].append(ok(*req("GET", "/takes")[::2])["takes"][0]["id"])
        return f"{h['x-audio-seconds']} s audio / {h['x-gen-time']} s"
    step("đọc văn bản + lịch sử", speech)

    def transcribe():
        r = job(ok(*req("POST", "/transcriptions", {"language": "vi"}, {"file": ("speech.wav", open(os.path.join(OUT, "speech.wav"), "rb").read())})[::2]))
        made["transcriptions"].append(r["id"])
        srt = req("GET", f"/transcriptions/{r['id']}/export?format=srt")[2].decode(); assert "-->" in srt
        assert "xin chào" in r["text"].lower(), r["text"]; return repr(r["text"])
    step("chép lời + xuất SRT", transcribe)

    def dub():
        p = job(ok(*req("POST", "/dub", {"source_lang": "en", "target_lang": "vi"}, {"file": ("demo.mp4", open(VIDEO, "rb").read())})[::2]))
        made["dub"].append(p["id"]); assert p["segments"] and p["has_video"]
        c, _, b = req("POST", f"/dub/{p['id']}/translate", {"engine": "argos"})
        if c == 409 or (c == 200 and False): pass
        r = json.loads(b)
        if c == 200:
            try: p = job(r)
            except AssertionError as e:
                if "argos_pack_missing" not in str(e): raise
                job(ok(*req("POST", "/translation/packs", {"from": "en", "to": "vi"})[::2])); p = job(ok(*req("POST", f"/dub/{p['id']}/translate", {"engine": "argos"})[::2]))
        print("     dịch máy:", [s["translation"] for s in p["segments"]])
        vi = ["VoiceStudio là ứng dụng nhân bản giọng, lồng tiếng và thiết kế giọng.", "Nó chạy hoàn toàn trên máy của bạn.",
              "Không tài khoản, không đám mây, không khóa API.", "Mở ứng dụng là sáng tạo ngay."]
        p = ok(*req("PATCH", f"/dub/{p['id']}", {"segments": [{"id": s["id"], "translation": vi[i] if i < len(vi) else s["translation"]} for i, s in enumerate(p["segments"])], "keep_background": True})[::2])
        p = job(ok(*req("POST", f"/dub/{p['id']}/render", {"strategy": "smart_fit"})[::2]))
        c, _, mp4 = req("GET", p["output"]); assert c == 200 and len(mp4) > 10000
        open(os.path.join(OUT, "dub.vi.mp4"), "wb").write(mp4)
        return f"{len(p['segments'])} câu, tách nhạc nền={p.get('separated')}, fit={[s['fit'] for s in p['segments']]}"
    step("lồng tiếng: tải lên → dịch Argos → sửa → render", dub)

    def book():
        script = "# Chương 1\nNgày xưa có một ngôi làng nhỏ. [pause 0.8s] Sương phủ trắng mặt sông.\n\n# Chương 2\n[voice:E2E Thiết kế] Một hôm có người khách lạ."
        pl = ok(*req("POST", "/audiobook/plan", {"script": script, "voice": v["id"]})[::2]); assert len(pl["chapters"]) == 2 and not pl["missing_voices"], pl
        bad = req("POST", "/audiobook", {"script": "[voice:KhôngCó] chào", "voice": v["id"]}); assert bad[0] == 400
        r = job(ok(*req("POST", "/audiobook", {"script": script, "voice": v["id"], "title": "E2E", "format": "m4b"})[::2]))
        made["audiobooks"].append(r["id"]); c, _, m = req("GET", r["download"]); assert c == 200
        open(os.path.join(OUT, "book.m4b"), "wb").write(m); return f"{r['seconds']} s, chương {[c['title'] for c in r['chapters']]}"
    step("sách nói m4b", book)
    print("E2E PASS, file ra ở", OUT)
finally:
    for kind, ids in made.items():
        for i in ids:
            path = {"voices": f"/voices/{i}", "dub": f"/dub/{i}", "audiobooks": f"/audiobooks/{i}", "takes": f"/takes/{i}", "transcriptions": f"/transcriptions/{i}"}[kind]
            req("DELETE", path)
    print("đã dọn:", {k: len(v) for k, v in made.items()})
