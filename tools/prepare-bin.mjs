// Copies the helper programs the installer ships (uv to build the Python runtime, ffmpeg/ffprobe for media) into bin/.
import { copyFileSync, existsSync, mkdirSync } from "node:fs";
import { execSync } from "node:child_process";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const bin = join(dirname(dirname(fileURLToPath(import.meta.url))), "bin");
mkdirSync(bin, { recursive: true });
const where = (n) => execSync(`where ${n}`, { encoding: "utf8" }).split(/\r?\n/).find((l) => l.toLowerCase().endsWith(".exe"));
for (const n of ["uv", "ffmpeg", "ffprobe"]) {
  const src = process.env[`VC_${n.toUpperCase()}_EXE`] || where(n);
  if (!src || !existsSync(src)) throw new Error(`không tìm thấy ${n}.exe (đặt VC_${n.toUpperCase()}_EXE)`);
  copyFileSync(src, join(bin, `${n}.exe`));
  console.log(`bin/${n}.exe <- ${src}`);
}
