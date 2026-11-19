"""Import voices from a VoiceStudio install into VoiceClone Studio, through the engine API (read-only on VoiceStudio's side).

    python tools/import_voicestudio.py --list
    python tools/import_voicestudio.py [--all | id id ...] [--engine http://127.0.0.1:3910]
Takes each profile's reference audio and its saved transcript (no re-transcription), keeps the name, maps the language.
--all skips demos and "_preview" entries. Voices already imported (same name) are skipped.
"""
import argparse, json, os, sqlite3, sys, urllib.error, urllib.request, uuid

VS = os.path.join(os.environ["APPDATA"], "OmniVoice")
LANG = {"english": "en", "en": "en", "vietnamese": "vi", "vi": "vi", "japanese": "ja", "ja": "ja", "chinese": "zh", "korean": "ko"}


def profiles():
    db = sqlite3.connect(f"file:{os.path.join(VS, 'omnivoice.db')}?mode=ro", uri=True)  # never write to VoiceStudio's database
    rows = db.execute("select id, name, ref_text, language, kind, is_demo from voice_profiles order by created_at").fetchall()
    out = []
    for vid, name, ref_text, lang, kind, demo in rows:
        wav = next((os.path.join(VS, "voices", f) for f in (f"{vid}.wav", f"{vid}_gallery.wav") if os.path.exists(os.path.join(VS, "voices", f))), None)
        out.append({"id": vid, "name": name, "ref_text": (ref_text or "").strip(), "language": LANG.get((lang or "").lower()),
                    "kind": kind, "demo": bool(demo), "wav": wav})
    return out


def post_voice(engine, p):
    bnd = uuid.uuid4().hex; fields = {"name": p["name"], "ref_text": p["ref_text"], **({"language": p["language"]} if p["language"] else {})}
    body = b"".join(f'--{bnd}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode() for k, v in fields.items())
    body += f'--{bnd}\r\nContent-Disposition: form-data; name="audio"; filename="{p["id"]}.wav"\r\nContent-Type: audio/wav\r\n\r\n'.encode()
    body += open(p["wav"], "rb").read() + f"\r\n--{bnd}--\r\n".encode()
    req = urllib.request.Request(engine + "/voices", body, {"content-type": f"multipart/form-data; boundary={bnd}"})
    try: return json.load(urllib.request.urlopen(req, timeout=600))
    except urllib.error.HTTPError as e: raise SystemExit(f"{p['name']}: {e.code} {e.read().decode(errors='replace')[:300]}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("ids", nargs="*"); ap.add_argument("--all", action="store_true")
    ap.add_argument("--list", action="store_true"); ap.add_argument("--engine", default="http://127.0.0.1:3910")
    a = ap.parse_args(); ps = profiles()
    if a.list or not (a.ids or a.all):
        for p in ps: print(f"{p['id']}  {p['kind']:6} {p['language'] or '?':3} {'demo ' if p['demo'] else ''}{'(no audio) ' if not p['wav'] else ''}{p['name']}")
        sys.exit(0)
    pick = [p for p in ps if (p["id"] in a.ids) or (a.all and not p["demo"] and not p["name"].startswith("_preview"))]
    have = {v["name"] for v in json.load(urllib.request.urlopen(a.engine + "/voices"))["voices"]}
    for p in pick:
        if not p["wav"] or not p["ref_text"]: print("bỏ qua (thiếu audio/lời mẫu):", p["name"]); continue
        if p["name"] in have: print("đã có:", p["name"]); continue
        v = post_voice(a.engine, p); print(f"đã nhập: {v['name']} ({v['language']}, {v['seconds']} s) -> {v['id']}")
