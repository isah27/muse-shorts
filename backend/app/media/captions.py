"""Word-timed captions: SRT for platforms + animated ASS (pop + highlight) for burn-in."""
from __future__ import annotations
import re
from .. import config as C

def words_from_scenes(scenes: list[dict]) -> list[dict]:
    """Estimate word timings inside each scene's known audio window (weighted by word length)."""
    out = []
    for s in scenes:
        ws = s["narration"].split()
        t0, dur = s["start"] + 0.05, s["audio_seconds"] - 0.3
        weights = [len(re.sub(r"\W", "", w)) + 2 + (4 if re.search(r"[.,!?]$", w) else 0) for w in ws]
        tot, acc = sum(weights), 0
        for w, wt in zip(ws, weights):
            a = t0 + dur * acc / tot; acc += wt
            out.append({"word": w, "start": a, "end": t0 + dur * acc / tot})
    return out

def _ts(t, sep=","):
    h, m = int(t // 3600), int(t % 3600 // 60); s = t % 60
    return f"{h:02}:{m:02}:{int(s):02}{sep}{int(round((s % 1) * 1000)):03}"

def chunks(words, max_words=3):
    cur = []
    for w in words:
        cur.append(w)
        if len(cur) >= max_words or re.search(r"[.,!?]$", w["word"]):
            yield cur; cur = []
    if cur:
        yield cur

def write_srt(words, path):
    lines = []
    for i, c in enumerate(chunks(words, 5), 1):
        lines += [str(i), f"{_ts(c[0]['start'])} --> {_ts(c[-1]['end'])}", " ".join(w["word"] for w in c), ""]
    open(path, "w").write("\n".join(lines))

def _ass_t(t):
    h, m = int(t // 3600), int(t % 3600 // 60); s = t % 60
    return f"{h}:{m:02}:{s:05.2f}"

# Diacritic languages are captioned in mixed case with a font whose glyphs were checked by eye (docs/caption_frames/):
# Noto Sans for Yoruba/Igbo (ẹ ọ ṣ + stacked tones, ị ọ ụ ṅ). Hausa uses DejaVu Sans: Noto Sans draws capital Ƙ exactly like K.
CAPTION_FONTS = {"yo": "Noto Sans", "ig": "Noto Sans", "ha": "DejaVu Sans"}
CAPTION_SIZES = {"ha": 78}   # DejaVu Sans is wider than Noto: 3 Hausa words at 92 px overflow 1080 px
NOTO_LANGS = tuple(CAPTION_FONTS)
DIACRITICS = {"yo": "ẹọṣẸỌṢàáèéìíòóùúẹ́ọ̀ṣ", "ha": "ƙɗɓƘƊƁʼ'", "ig": "ịọụṅỊỌỤṄ"}


def caption_style(lang: str = "en"):
    """(font, case fn). Uppercasing breaks stacked marks and Montserrat misplaces combining marks, so yo/ha/ig stay mixed case."""
    if lang in CAPTION_FONTS:
        return CAPTION_FONTS[lang], (lambda t: t)
    return C.CAPTION_FONT, (lambda t: t.upper())


def write_ass(words, path, highlight="&H00FCD37D&", lang="en"):
    # Yoruba stacks tone marks on dot-below letters; Montserrat misplaces the
    # combining marks and uppercase drops them, so use Noto Sans in mixed case.
    font, up = caption_style(lang)
    head = f"""[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 2

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Cap,{font},{CAPTION_SIZES.get(lang, 92)},&H00FFFFFF,&H00FFFFFF,&H00000000,&H96000000,-1,0,0,0,100,100,0,0,1,7,4,2,80,80,560,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    ev = []
    for c in chunks(words, 3):
        end = c[-1]["end"]
        for j, w in enumerate(c):
            st = w["start"]; en = c[j + 1]["start"] if j + 1 < len(c) else end
            parts = []
            for k, x in enumerate(c):
                word = up(re.sub(r"[{}\\]", "", x["word"]))
                if k == j:
                    parts.append(r"{\c" + highlight + r"\fscx112\fscy112}" + word + r"{\c&H00FFFFFF&\fscx100\fscy100}")
                else:
                    parts.append(word)
            pop = r"{\fad(60,0)\t(0,90,\fscx106\fscy106)\t(90,180,\fscx100\fscy100)}" if j == 0 else ""
            ev.append(f"Dialogue: 0,{_ass_t(st)},{_ass_t(en)},Cap,,0,0,0,,{pop}{' '.join(parts)}")
    open(path, "w").write(head + "\n".join(ev) + "\n")
