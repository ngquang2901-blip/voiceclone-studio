// VoiceClone Studio desktop shell: prepares the Python runtime on first run, starts the engine, shows the UI.
const { app, BrowserWindow, ipcMain, shell, dialog } = require("electron");
const { spawn, spawnSync } = require("child_process");
const crypto = require("crypto");
const fs = require("fs");
const net = require("net");
const path = require("path");

const ROOT = app.isPackaged ? process.resourcesPath : __dirname;
const DATA = process.env.VC_DATA || path.join(app.getPath("appData"), "VoiceCloneStudio");
if (process.env.VC_DATA) app.setPath("userData", path.join(DATA, "electron")); // isolated test run: its own single-instance lock
const RUNTIME = path.join(DATA, "runtime");
const VENV_PY = path.join(RUNTIME, ".venv", "Scripts", "python.exe");
const LOGS = path.join(DATA, "logs");
const BIN = path.join(ROOT, "bin");
const exe = (name) => (fs.existsSync(path.join(BIN, name + ".exe")) ? path.join(BIN, name + ".exe") : name);
fs.mkdirSync(LOGS, { recursive: true });

let splash, win, engine, engineUrl, quitting = false;

if (!app.requestSingleInstanceLock()) app.quit();
app.on("second-instance", () => { const w = win || splash; if (w) { if (w.isMinimized()) w.restore(); w.focus(); } });

function status(state, message, extra = {}) {
  if (splash && !splash.isDestroyed()) splash.webContents.send("status", { state, message, ...extra });
}

function log(name) { return fs.createWriteStream(path.join(LOGS, name), { flags: "a" }); }

function run(cmd, args, opts, onLine) {
  return new Promise((resolve, reject) => {
    const out = log("setup.log");
    out.write(`\n$ ${cmd} ${args.join(" ")}\n`);
    const p = spawn(cmd, args, { windowsHide: true, ...opts });
    const feed = (b) => { out.write(b); for (const l of b.toString().split(/\r?\n/)) if (l.trim()) onLine?.(l.trim()); };
    p.stdout.on("data", feed); p.stderr.on("data", feed);
    p.on("error", reject);
    p.on("close", (code) => (code === 0 ? resolve() : reject(new Error(`${path.basename(cmd)} thoát với mã ${code}. Xem log: ${path.join(LOGS, "setup.log")}`))));
  });
}

function hasNvidia() {
  const r = spawnSync("nvidia-smi", ["-L"], { windowsHide: true, encoding: "utf8" });
  return r.status === 0 && /GPU \d/.test(r.stdout || "");
}

// First run (or after an update changed the lock file): one venv with the exact package set.
async function ensureRuntime() {
  if (process.env.VC_PYTHON) return process.env.VC_PYTHON; // dev: use an existing environment
  const lock = fs.readFileSync(path.join(ROOT, "engine", "requirements.lock.txt"), "utf8");
  const gpu = hasNvidia();
  const want = crypto.createHash("sha256").update(lock + (gpu ? "cuda" : "cpu")).digest("hex");
  const marker = path.join(RUNTIME, "installed.json");
  try { if (JSON.parse(fs.readFileSync(marker, "utf8")).hash === want && fs.existsSync(VENV_PY)) return VENV_PY; } catch {}

  const uv = exe("uv");
  const env = { ...process.env, UV_PYTHON_INSTALL_DIR: path.join(RUNTIME, "python"), VIRTUAL_ENV: path.join(RUNTIME, ".venv") };
  fs.mkdirSync(RUNTIME, { recursive: true });
  status("setup", "Đang chuẩn bị Python (chỉ lần đầu)…", { step: 1, steps: 3 });
  await run(uv, ["venv", "--python", "3.12", "--allow-existing", path.join(RUNTIME, ".venv")], { env });
  const req = path.join(RUNTIME, "requirements.txt");
  fs.writeFileSync(req, gpu ? lock : lock.replace(/\+cu\d+/g, ""));
  const index = gpu ? "https://download.pytorch.org/whl/cu128" : "https://download.pytorch.org/whl/cpu";
  status("setup", gpu ? "Đang cài thư viện AI cho GPU NVIDIA (~4 GB, chỉ lần đầu)…" : "Đang cài thư viện AI chạy bằng CPU (chỉ lần đầu)…", { step: 2, steps: 3 });
  let n = 0;
  await run(uv, ["pip", "install", "--python", VENV_PY, "--no-deps", "-r", req, "--extra-index-url", index, "--index-strategy", "unsafe-best-match"], { env }, (l) => {
    const m = l.match(/^(Downloading|Downloaded|Prepared|Installed|Resolved)\b.*$/);
    if (m) { n++; status("setup", "Đang cài thư viện AI (chỉ lần đầu)…", { step: 2, steps: 3, detail: l.slice(0, 120), count: n }); }
  });
  fs.writeFileSync(marker, JSON.stringify({ hash: want, gpu, at: new Date().toISOString() }));
  return VENV_PY;
}

function freePort(start) {
  return new Promise((resolve) => {
    const s = net.createServer();
    s.once("error", () => resolve(freePort(start + 1)));
    s.listen(start, "127.0.0.1", () => s.close(() => resolve(start)));
  });
}

function portFree(port) {
  return new Promise((resolve) => { const s = net.createServer(); s.once("error", () => resolve(false)); s.listen(port, "127.0.0.1", () => s.close(() => resolve(true))); });
}

async function startEngine(python) {
  // Keep the port the window already knows: a killed engine releases it within a few seconds.
  let port = engineUrl ? Number(new URL(engineUrl).port) : 3910;
  for (let i = 0; engineUrl && i < 20 && !(await portFree(port)); i++) await new Promise((r) => setTimeout(r, 500));
  if (!(await portFree(port))) port = await freePort(port + 1);
  engineUrl = `http://127.0.0.1:${port}`;
  status("starting", "Đang khởi động engine…", { step: 3, steps: 3 });
  const out = log("engine.log");
  out.write(`\n=== ${new Date().toISOString()} port ${port}\n`);
  engine = spawn(python, ["-m", "uvicorn", "server:app", "--app-dir", path.join(ROOT, "engine"), "--host", "127.0.0.1", "--port", String(port)], {
    windowsHide: true,
    env: { ...process.env, VC_DATA: DATA, VC_PARENT_PID: String(process.pid), VC_FFMPEG: exe("ffmpeg"), VC_FFPROBE: exe("ffprobe"), PYTHONIOENCODING: "utf-8", PYTHONUTF8: "1" },
  });
  engine.stdout.pipe(out); engine.stderr.pipe(out);
  const died = new Promise((_, reject) => engine.once("exit", (code) => reject(new Error(`Engine dừng (mã ${code}). Xem log: ${path.join(LOGS, "engine.log")}`))));
  engine.once("exit", () => { engine = null; if (!quitting && win) win.webContents.send("engine-exit"); });
  const t0 = Date.now();
  const ready = (async () => {
    while (Date.now() - t0 < 180000) {
      try { if ((await fetch(engineUrl + "/health", { signal: AbortSignal.timeout(3000) })).ok) return; } catch {}
      status("starting", "Đang khởi động engine…", { step: 3, steps: 3, elapsed: Math.round((Date.now() - t0) / 1000) });
      await new Promise((r) => setTimeout(r, 700));
    }
    throw new Error("Engine không phản hồi sau 3 phút. Xem log: " + path.join(LOGS, "engine.log"));
  })();
  await Promise.race([ready, died]);
}

function stopEngine() {
  if (engine && engine.pid) spawnSync("taskkill", ["/PID", String(engine.pid), "/T", "/F"], { windowsHide: true });
  engine = null;
}

function openMain() {
  win = new BrowserWindow({
    width: 1440, height: 900, minWidth: 1100, minHeight: 700, show: false, backgroundColor: "#0b0b0c", title: "VoiceClone Studio", icon: path.join(__dirname, "build", "icon.png"),
    autoHideMenuBar: true, webPreferences: { preload: path.join(__dirname, "preload.js"), additionalArguments: [`--vc-engine=${engineUrl}`, `--vc-version=${app.getVersion()}`] },
  });
  win.loadURL(engineUrl + "/ui/index.html");
  win.once("ready-to-show", () => { win.show(); if (splash && !splash.isDestroyed()) splash.close(); });
  win.webContents.setWindowOpenHandler(({ url }) => { if (/^https?:/.test(url) && !url.startsWith(engineUrl)) shell.openExternal(url); return { action: "deny" }; });
  win.webContents.on("will-navigate", (e, url) => { if (!url.startsWith(engineUrl)) { e.preventDefault(); if (/^https?:/.test(url)) shell.openExternal(url); } });
  win.on("closed", () => { win = null; });
}

async function boot() {
  if (!splash || splash.isDestroyed()) {
    splash = new BrowserWindow({ width: 760, height: 460, frame: false, resizable: false, backgroundColor: "#0b0b0c", show: false,
      webPreferences: { preload: path.join(__dirname, "shell", "splash-preload.js") } });
    splash.loadFile(path.join(__dirname, "shell", "splash.html"));
    await new Promise((r) => splash.once("ready-to-show", r)); splash.show();
  }
  try {
    const py = await ensureRuntime();
    await startEngine(py);
    openMain();
  } catch (e) {
    stopEngine();
    status("error", e.message || String(e));
  }
}

ipcMain.handle("retry", () => boot());
ipcMain.handle("open-logs", () => shell.openPath(LOGS));
ipcMain.handle("quit", () => app.quit());
ipcMain.handle("show-item", (_, p) => { if (typeof p === "string" && p.startsWith(DATA)) shell.openPath(p); });
ipcMain.handle("restart-engine", async () => {
  const before = engineUrl;
  stopEngine(); await startEngine(await ensureRuntime());
  if (engineUrl !== before && win) { const old = win; openMain(); old.destroy(); } // the page holds the engine address from its preload
  return engineUrl;
});

// ---------- updates: latest GitHub release of the public repo ----------
const REPO = "ngquang2901-blip/voiceclone-studio";
const newer = (a, b) => { // semver-ish: 0.2.10 > 0.2.9, 0.2.9 > 0.2.9-test.0
  const p = (v) => { const [main, pre] = v.replace(/^v/, "").split("-"); return [...main.split(".").map(Number), pre ? 0 : 1]; };
  const x = p(a), y = p(b);
  for (let i = 0; i < 4; i++) if ((x[i] || 0) !== (y[i] || 0)) return (x[i] || 0) > (y[i] || 0);
  return false;
};
async function latestRelease() {
  const r = await fetch(`https://api.github.com/repos/${REPO}/releases/latest`, { headers: { accept: "application/vnd.github+json" }, signal: AbortSignal.timeout(20000) });
  if (!r.ok) throw new Error(`Không kiểm tra được bản mới (GitHub trả HTTP ${r.status})`);
  const rel = await r.json(); const asset = (rel.assets || []).find((a) => /setup\.exe$/i.test(a.name));
  return { rel, asset };
}
ipcMain.handle("update-check", async () => {
  const { rel, asset } = await latestRelease();
  return { current: app.getVersion(), latest: rel.tag_name.replace(/^v/, ""), newer: !!asset && newer(rel.tag_name, app.getVersion()),
           notes: rel.body || "", url: rel.html_url, size: asset ? asset.size : 0 };
});
ipcMain.handle("update-install", async (e) => {
  const { rel, asset } = await latestRelease();
  if (!asset || !newer(rel.tag_name, app.getVersion())) throw new Error("Đang dùng bản mới nhất");
  const file = path.join(app.getPath("temp"), asset.name);
  const r = await fetch(asset.browser_download_url, { signal: AbortSignal.timeout(30 * 60000) });
  if (!r.ok) throw new Error(`Tải bản cập nhật lỗi (HTTP ${r.status})`);
  const out = fs.createWriteStream(file), hash = crypto.createHash("sha256"); let got = 0;
  for await (const chunk of r.body) {
    out.write(chunk); hash.update(chunk); got += chunk.length;
    e.sender.send("update-progress", got / asset.size);
  }
  await new Promise((res, rej) => out.end((err) => (err ? rej(err) : res())));
  // a cut download or a swapped file must never run
  if (got !== asset.size) throw new Error("Tải bản cập nhật bị thiếu, hãy thử lại");
  if (asset.digest && asset.digest !== "sha256:" + hash.digest("hex")) throw new Error("File cập nhật không khớp mã kiểm tra, đã huỷ");
  // silent install (keeps license, voices, settings), then the installer starts the app again
  spawn(file, ["/S", "--force-run"], { detached: true, stdio: "ignore" }).unref();
  setTimeout(() => app.quit(), 500);
  return true;
});

app.whenReady().then(() => {
  // the updater leaves its downloaded setup.exe in temp: remove old ones once the new version runs
  for (const f of fs.readdirSync(app.getPath("temp")).filter((n) => /^VoiceClone-Studio-.*-setup\.exe$/i.test(n)))
    fs.rm(path.join(app.getPath("temp"), f), { force: true }, () => {});
  boot();
});
app.on("before-quit", () => { quitting = true; stopEngine(); });
app.on("window-all-closed", () => app.quit());
