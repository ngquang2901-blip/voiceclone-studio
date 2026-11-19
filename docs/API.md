# VoiceClone Studio — API contract (engine ⇄ UI)

Engine: FastAPI on `http://127.0.0.1:<port>` (default 3910). UI gets the base URL from `window.vc.engineUrl` (Electron preload) or falls back to `location.origin`.
All errors are JSON `{"error": "<code>", "message": "<Vietnamese text for people>"}` with a 4xx/5xx status.
`402 {"error":"license_required"|"feature_not_licensed"}` = paywall: UI shows the licence screen.

## Long jobs
Any route marked **JOB** returns `{"job_id": "..."}` at once. Poll `GET /jobs/{job_id}` every ~700 ms:
`{"id","kind","status":"queued|running|done|error","progress":0..1,"message":"<what it is doing, Vietnamese>","result":{...}|null,"error":{"error","message"}|null,"created"}`.
`GET /jobs?limit=20` lists recent jobs (newest first).

## System
- `GET /health` → `{"status":"ok","version","device":"cuda|cpu","gpu":{"name","free_mb","total_mb"}|null,"warning":str|null,"licensed":bool,"license":{"sub","features":[],"exp"}|null,"models_ready":bool,"tts_loaded","asr_loaded"}`
- `GET /settings` → `{"device":"auto|cuda|cpu","quality":"fast|balanced|quality","asr_model":"large-v3|small","llm":{"base_url","model","has_key":bool},"data_dir"}`
- `PATCH /settings` body: any subset of the above (+ `"llm":{"base_url","model","api_key"}`) → the new settings.
- `POST /model/unload` → frees GPU memory.
- `POST /license` `{"key"}` → `{"ok":true,"license":{...}}` | 400 invalid_key. `DELETE /license`.

## Models (first-run downloads)
- `GET /models` → `{"models":[{"id":"tts"|"asr"|"separator","name","size_mb","installed":bool,"required":bool,"license"}], "translation_packs":[{"from","to","installed"}]}`
- `POST /models/{id}/download` **JOB** (progress = bytes fraction).
- `POST /translation/packs` `{"from":"en","to":"vi"}` **JOB**.

## Voices
Voice object: `{"id","name","kind":"clone|design","language","ref_text","seconds","instruct":str|null,"created","tags":[]}`; audio sample at `GET /voices/{id}/sample` (wav).
- `GET /voices` → `{"voices":[...]}` (newest first)
- `POST /voices` multipart: `name`, `audio` (file: wav/mp3/m4a/webm/mp4…), optional `ref_text`, `language` → voice. (Mic recordings from the UI are sent as `audio/webm`.) License: `clone`.
- `PATCH /voices/{id}` `{"name"?, "tags"?}` → voice. `DELETE /voices/{id}`.
- `POST /design/preview` `{"instruct":"female, young adult, low pitch","text","language"}` → `audio/wav` (headers `x-audio-seconds`, `x-gen-time`, `x-design-id`). License: `clone`.
  Valid instruct items: male, female · child, teenager, young adult, middle-aged, elderly · very low pitch, low pitch, moderate pitch, high pitch, very high pitch · whisper · american/australian/british/canadian/chinese/indian/japanese/korean/portuguese/russian accent. Comma+space separated, at most one per group.
- `POST /design/save` `{"design_id","name"}` → voice (kind=design; the preview becomes its reference).

## Speech (TTS)
- `POST /speech` `{"text","voice","language"?,"speed"?:0.7..1.4,"quality"?}` → `audio/wav`, headers `x-take-id`, `x-audio-seconds`, `x-gen-time`. Saves a take. License: `tts`.
- `POST /v1/audio/speech` OpenAI shape `{"input","voice","response_format":"wav"}` → wav (for Kaiser/other apps; also saves a take).
- `GET /v1/audio/voices` → `{"voices":[{"filename":id,"display_name":name}]}`; `GET /v1/models` → `{"data":[]}`.
- Takes: `GET /takes?limit=50` → `{"takes":[{"id","text","voice","voice_name","seconds","gen_time","created"}]}`; audio `GET /takes/{id}/audio`; `DELETE /takes/{id}`.

## Transcribe
- `POST /transcriptions` multipart `file`, optional `language` **JOB** → result `{"id","language","text","segments":[{"id","start","end","text"}],"file_name","seconds"}`. Saved to history. License: `tts`.
- `GET /transcriptions` → `{"items":[{id,file_name,language,seconds,created,text(first 200 chars)}]}`; `GET /transcriptions/{id}` full; `GET /transcriptions/{id}/export?format=txt|srt|vtt` (file); `DELETE /transcriptions/{id}`.
- `POST /v1/audio/transcriptions` (OpenAI shape, sync) kept for other apps.

## Dub
Project object: `{"id","name","source_lang","target_lang","status":"new|transcribed|translated|rendered","segments":[{"id","start","end","speaker","text","translation","fit":null|"fits"|"sped_up"|"overflow"}],"voice":id|null,"keep_background":bool,"has_video":bool,"duration","output":"/dub/{id}/download"|null,"created"}`
- `POST /dub` multipart `file` (video or audio), `source_lang` (optional, auto), `target_lang` **JOB** (upload + extract audio + separate background if model installed + transcribe) → result = project.
- `GET /dub` → `{"projects":[...] }` (without segments); `GET /dub/{id}` → project; `DELETE /dub/{id}`.
- `PATCH /dub/{id}` `{"segments":[{"id","translation"}]?, "voice"?, "keep_background"?, "target_lang"?, "name"?}` → project.
- `POST /dub/{id}/translate` `{"engine":"argos"|"llm"}` **JOB** → project (fills `translation`; Argos pack missing → error `argos_pack_missing` with message).
- `POST /dub/{id}/render` `{"strategy":"smart_fit|strict_slot|stretch"}` **JOB** → project (status rendered, output set). voice null = clone the original speaker.
- `GET /dub/{id}/download` → mp4 (or m4a when the source had no video). `GET /dub/{id}/source` → original media.

## Audiobook
Script syntax: `# Chapter title` lines, `[voice:Name]` switches voice (name or id), `[pause 800ms]` / `[pause 0.5s]` inserts silence, blank line = paragraph gap.
- `POST /audiobook/plan` `{"script","voice"}` → `{"chapters":[{"title","words"}],"words","est_seconds","voices":[names],"missing_voices":[...]}` (no GPU, instant).
- `POST /audiobook` `{"script","voice","title","author","format":"m4b|mp3|wav","paragraph_gap_ms"}` **JOB** (progress per sentence) → result `{"id","file_name","download":"/audiobooks/{id}/download","seconds","chapters":[{"title","start_s"}]}`.
- `GET /audiobooks` list; `GET /audiobooks/{id}/download`; `DELETE /audiobooks/{id}`.

## Languages
`GET /languages` → `{"tts":[{"code":"vi","name":"Tiếng Việt"},...], "translation":[{"code","name"}]}` (UI lists these; first entries vi, en, ja, ko, zh, fr, es, de, th, id).
