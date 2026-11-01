import sys, subprocess
sys.path.insert(0, "backend")
from app.media import captions as cap
S = {"yo": "Àjẹsára ṣẹ́ ọ̀pọ̀", "ha": "Ƙwayoyin ɗaya ɓangare", "ig": "Ọrịa ụmụ ṅụọ"}
for lang, text in S.items():
    ws = text.split(); words = [{"word": w, "start": i * 0.4, "end": i * 0.4 + 0.4} for i, w in enumerate(ws)]
    ass = f"/tmp/cap_{lang}.ass"; cap.write_ass(words, ass, lang=lang)
    out = f"docs/caption_frames/caption_{lang}.png"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=0x203040:s=1080x1920:d=2", "-vf", f"ass={ass}",
                    "-ss", "0.5", "-frames:v", "1", out], check=True)
    print(out)
