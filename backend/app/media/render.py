"""ffmpeg renderer: 1080x1920 @30fps, Ken Burns per scene, crossfades, burned animated captions, optional music."""
from __future__ import annotations
import subprocess, shlex
from pathlib import Path
from PIL import Image, ImageOps
from .. import config as C

FPS, W, H, XF = 30, 1080, 1920, 0.45
MOVES = [  # zoom expression, x, y  (alternating so consecutive shots feel different)
    ("1.0+0.10*on/{d}", "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"),
    ("1.12-0.10*on/{d}", "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"),
    ("1.08", "(iw-iw/zoom)*on/{d}", "ih/2-(ih/zoom/2)"),
    ("1.0+0.08*on/{d}", "iw/2-(iw/zoom/2)", "(ih-ih/zoom)*(1-on/{d})"),
]

def run(cmd: list[str]):
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode:
        raise RuntimeError(f"ffmpeg failed: {' '.join(map(shlex.quote, cmd))[:400]}\n{p.stderr[-1500:]}")

def cover(src: str, dst: str):
    ImageOps.fit(Image.open(src).convert("RGB"), (W * 2, H * 2), Image.LANCZOS).save(dst, quality=95)
    return dst

def scene_clip(img: str, seconds: float, idx: int, out: str):
    d = max(1, int(round(seconds * FPS)))
    z, x, y = (e.format(d=d) for e in MOVES[idx % len(MOVES)])
    vf = (f"zoompan=z='{z}':x='{x}':y='{y}':d={d}:s={W}x{H}:fps={FPS},"
          f"format=yuv420p,setsar=1")
    run(["ffmpeg", "-y", "-loglevel", "error", "-i", img, "-vf", vf, "-frames:v", str(d),
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", out])

def concat_audio(wavs: list[str], out: str):
    lst = Path(out).with_suffix(".txt")
    lst.write_text("".join(f"file '{Path(w).resolve()}'\n" for w in wavs))
    run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", out])
    lst.unlink()

def final(clips: list[str], audio_durs: list[float], voice: str, ass: str | None, out: str,
          music: str | None = None, music_vol: float = 0.12):
    """clips[i] length = audio_durs[i] + XF (except last). xfade offsets = cumulative audio time."""
    cmd = ["ffmpeg", "-y", "-loglevel", "error"]
    for c in clips:
        cmd += ["-i", c]
    cmd += ["-i", voice]
    if music:
        cmd += ["-stream_loop", "-1", "-i", music]
    fc, prev, t = [], "[0:v]", 0.0
    for i in range(1, len(clips)):
        t += audio_durs[i - 1]
        tag = f"[v{i}]"
        fc.append(f"{prev}[{i}:v]xfade=transition=fade:duration={XF}:offset={t - XF / 2:.3f}{tag}")
        prev = tag
    vlast = prev
    if ass:
        fc.append(f"{vlast}subtitles='{ass}':fontsdir='{C.FONT_DIR}'[vs]"); vlast = "[vs]"
    fc.append(f"{vlast}fade=t=in:st=0:d=0.3[vout]")
    a_idx = len(clips)
    if music:
        fc.append(f"[{a_idx}:a]asplit[vo1][vo2];[{a_idx + 1}:a]volume={music_vol}[m];"
                  f"[m][vo1]sidechaincompress=threshold=0.05:ratio=6[duck];"
                  f"[vo2][duck]amix=inputs=2:duration=first:normalize=0[aout]")
        amap = "[aout]"
    else:
        amap = f"{a_idx}:a"
    total = sum(audio_durs)
    cmd += ["-filter_complex", ";".join(fc), "-map", "[vout]", "-map", amap, "-t", f"{total:.3f}",
            "-c:v", "libx264", "-preset", "medium", "-crf", "19", "-pix_fmt", "yuv420p", "-r", str(FPS),
            "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", out]
    run(cmd)
    return out

def probe_duration(path: str) -> float:
    p = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
                       capture_output=True, text=True)
    return float(p.stdout.strip() or 0)
