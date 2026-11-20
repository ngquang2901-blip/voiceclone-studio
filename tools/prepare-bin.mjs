// Puts the helper programs the installer ships into bin/: uv (builds the Python runtime) and an LGPL ffmpeg/ffprobe.
import { copyFileSync, existsSync, mkdirSync, readdirSync } from "node:fs";
import { execFileSync, execSync } from "node:child_process";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const root = dirname(dirname(fileURLToPath(import.meta.url)));
const bin = join(root, "bin"), cache = join(root, "build", "cache");
const FFMPEG_ZIP = "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-n9.0-latest-win64-lgpl-9.0.zip";
mkdirSync(bin, { recursive: true });
const where = (n) => execSync(`where ${n}`, { encoding: "utf8" }).split(/\r?\n/).find((l) => l.toLowerCase().endsWith(".exe"));

function lgplFfmpegDir() {
  if (process.env.VC_FFMPEG_DIR) return process.env.VC_FFMPEG_DIR;
  const zip = join(cache, "ffmpeg-lgpl.zip");
  if (!existsSync(zip)) {
    mkdirSync(cache, { recursive: true });
    execFileSync("curl", ["-fL", "--retry", "3", "-o", zip, FFMPEG_ZIP], { stdio: "inherit" });
  }
  // Windows' own bsdtar reads zips; a git-bash GNU tar earlier in PATH would not.
  execFileSync(join(process.env.SystemRoot, "System32", "tar.exe"), ["-xf", zip, "-C", cache]);
  const dir = readdirSync(cache).find((d) => d.startsWith("ffmpeg-n9.0") && !d.endsWith(".zip"));
  return join(cache, dir, "bin");
}

const uv = process.env.VC_UV_EXE || where("uv");
if (!uv || !existsSync(uv)) throw new Error("không tìm thấy uv.exe (đặt VC_UV_EXE)");
copyFileSync(uv, join(bin, "uv.exe"));
console.log(`bin/uv.exe <- ${uv}`);

const ff = lgplFfmpegDir();
for (const n of ["ffmpeg", "ffprobe"]) {
  const src = join(ff, `${n}.exe`);
  const conf = execFileSync(src, ["-hide_banner", "-version"], { encoding: "utf8" });
  // A paid closed-source app may only ship LGPL ffmpeg: refuse GPL/nonfree builds outright.
  if (/--enable-(gpl|nonfree)/.test(conf)) throw new Error(`${src} là bản GPL/nonfree, không được đóng gói`);
  copyFileSync(src, join(bin, `${n}.exe`));
  console.log(`bin/${n}.exe <- ${src} (LGPL)`);
}
copyFileSync(join(ff, "..", "LICENSE.txt"), join(bin, "FFMPEG-LICENSE.txt"));  // LGPL: the licence text ships with the binary
