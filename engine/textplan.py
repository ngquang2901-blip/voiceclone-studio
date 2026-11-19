"""Pure text/timing logic (no GPU): chunking, audiobook script parsing, dub slot fitting."""
import re

SENT_END = re.compile(r"(?<=[.!?。！？…])\s+|\n+")


def chunk_text(text: str, max_chars: int = 300) -> list[str]:
    """Split on sentence ends, then pack sentences up to max_chars; a lone over-long sentence splits at commas/spaces."""
    out, cur = [], ""
    for sent in (s.strip() for s in SENT_END.split(text)):
        if not sent:
            continue
        pieces = [sent]
        if len(sent) > max_chars:
            pieces, buf = [], ""
            for w in re.split(r"(?<=[,;:])\s+|\s+", sent):
                if buf and len(buf) + 1 + len(w) > max_chars:
                    pieces.append(buf); buf = w
                else:
                    buf = f"{buf} {w}".strip()
            if buf: pieces.append(buf)
        for p in pieces:
            if cur and len(cur) + 1 + len(p) > max_chars:
                out.append(cur); cur = p
            else:
                cur = f"{cur} {p}".strip()
    if cur: out.append(cur)
    return out


TAG = re.compile(r"\[(voice):\s*([^\]]+)\]|\[pause\s+(\d+(?:\.\d+)?)\s*(ms|s)\]", re.I)


def parse_book(script: str, default_voice: str) -> list[dict]:
    """-> [{"chapter": title}, {"say": text, "voice": v}, {"pause_ms": n}, ...]. Blank line = paragraph break (gap)."""
    items, voice = [], default_voice
    for para in re.split(r"\n\s*\n", script):
        for line in para.strip().splitlines():
            line = line.strip()
            if line.startswith("#"):
                items.append({"chapter": line.lstrip("#").strip()}); continue
            pos = 0
            for m in TAG.finditer(line):
                before = line[pos:m.start()].strip()
                if before: items.append({"say": before, "voice": voice})
                if m.group(1): voice = m.group(2).strip()
                else: items.append({"pause_ms": int(float(m.group(3)) * (1 if m.group(4).lower() == "ms" else 1000))})
                pos = m.end()
            rest = line[pos:].strip()
            if rest: items.append({"say": rest, "voice": voice})
        items.append({"paragraph": True})
    return items


def fit_plan(dur: float, start: float, next_start: float | None, max_speed: float = 1.35) -> dict:
    """How to place a generated line of `dur` seconds in its slot [start, next_start)."""
    slot = (next_start - start) if next_start is not None else None
    if slot is None or dur <= slot:
        return {"speed": 1.0, "status": "fits"}
    need = dur / slot
    if need <= max_speed:
        return {"speed": round(need, 3), "status": "sped_up"}
    return {"speed": max_speed, "status": "overflow", "over_s": round(dur / max_speed - slot, 2)}


def plan_book(items: list[dict], words_per_second: float = 2.6) -> dict:
    """Instant estimate for the editor footer; ~2.6 spoken words/s (Vietnamese and English narration)."""
    chapters, words, pause_s = [], 0, 0.0
    for it in items:
        if "chapter" in it: chapters.append({"title": it["chapter"], "words": 0})
        elif "say" in it:
            n = len(it["say"].split()); words += n
            if chapters: chapters[-1]["words"] += n
        elif "pause_ms" in it: pause_s += it["pause_ms"] / 1000
    voices = sorted({it["voice"] for it in items if "say" in it and it["voice"]})
    return {"chapters": chapters, "words": words, "est_seconds": round(words / words_per_second + pause_s, 1), "voices": voices}
