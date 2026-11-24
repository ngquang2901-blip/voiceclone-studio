# VoiceClone Studio

App desktop chạy hoàn toàn trên máy: **clone giọng**, **đọc văn bản**, **lồng tiếng video** (tách nhạc nền, chép lời + phụ đề SRT, dịch bằng AI — chỉ cần dán API key Google Gemini trong Cài đặt → Dịch bằng AI — hoặc Argos offline), **sách nói** (m4b có chương). Thiết kế giọng và trang Chép lời riêng đã ẩn khỏi giao diện (API `/design/*`, `/transcriptions` vẫn còn). Có khoá trả phí bằng license key.
Bản dựng lại (clean-room) theo hành vi đo được của VoiceStudio 0.5.8: không dùng code VoiceStudio (AGPL).

## Cách hoạt động
```
VoiceClone Studio.exe (Electron)
 ├─ lần đầu: uv tạo Python 3.12 + cài đúng requirements.lock.txt vào %APPDATA%\VoiceCloneStudio\runtime
 │           (có GPU NVIDIA → torch CUDA 12.8; không có → torch CPU)
 ├─ mỗi lần mở: bật engine (FastAPI, 127.0.0.1:3910 hoặc cổng trống kế tiếp), màn hình chờ đến khi /health ok
 ├─ cửa sổ chính: giao diện ui/ do engine phục vụ; đóng app = tắt engine (engine cũng tự thoát nếu app chết)
 └─ engine: OmniVoice (TTS/clone/design) · faster-whisper (ASR, chạy CPU) · Demucs (tách nhạc) · Argos (dịch offline)
            mọi việc dài chạy nền (jobs) qua 1 hàng GPU; model tải lần đầu trong Cài đặt → Model
Dữ liệu: %APPDATA%\VoiceCloneStudio\ (voices, takes, dub, audiobooks, transcriptions, models, logs, license.key)
```
API: [docs/API.md](docs/API.md). Ngoài app, các chương trình khác (Kaiser…) gọi `POST /v1/audio/speech`, `GET /v1/audio/voices`, `POST /v1/audio/transcriptions`.

## Chạy khi phát triển
```
npm install && node node_modules/electron/install.js     # npm 11 chặn script cài của electron
set VC_PYTHON=<python có sẵn đủ thư viện> & npx electron .  # bỏ VC_PYTHON để thử đúng luồng cài lần đầu
python tools/seed_models.py        # (máy dev) hard link model có sẵn của VoiceStudio, khỏi tải lại 6 GB
```
Đóng gói: `npm run dist` → `release/VoiceClone-Studio-<ver>-setup.exe`. `tools/prepare-bin.mjs` tự tải ffmpeg/ffprobe bản **LGPL** (BtbN, từ chối bản GPL) vào bin/; cần `uv` trong PATH (hoặc đặt `VC_UV_EXE`).

**Ký số bộ cài** (để Windows SmartScreen không cảnh báo "không rõ nhà phát hành"): mua chứng chỉ ký mã (OV/EV, file `.pfx`
hoặc dịch vụ ký đám mây như Azure Trusted Signing), rồi trước `npm run dist` đặt:
```
set CSC_LINK=C:\đường\dẫn\chung-chi.pfx
set CSC_KEY_PASSWORD=<mật khẩu chứng chỉ>
```
electron-builder tự ký `VoiceClone Studio.exe`, `uv.exe`, `ffmpeg.exe`, `ffprobe.exe` và bộ cài. Không có hai biến này thì bản build không được ký (vẫn chạy được, nhưng SmartScreen cảnh báo).

## License key (máy người bán)
```
python tools/keytool.py init                          # một lần; khoá bí mật ở %USERPROFILE%\.voiceclone-keys (đừng làm mất, đừng chia sẻ)
python tools/keytool.py issue khach@x.com --machine ABCD-1234-EF56-7890 --days 30   # key chỉ chạy trên máy có mã đó (khách xem ở Cài đặt → License); --any-machine = mọi máy
```

## Kiểm thử
- `python tools/selfcheck.py` — logic không cần GPU (cắt câu, kịch bản sách nói, khớp thời lượng, license).
- `VC_TEST_KEY=<key> python tools/e2e.py` — chạy trọn mọi tính năng qua API với engine đang chạy, tự dọn.

## Giấy phép thành phần
Xem [NOTICE.txt](NOTICE.txt). Cần làm rõ trước khi bán rộng: (1) giấy phép trọng số OmniVoice (thẻ model để trống), (2) điều kiện Higgs Audio 2 (< 100k người dùng/năm, phải hiện dòng "Built with…"), (3) bản FFmpeg đóng gói phải là bản LGPL.
