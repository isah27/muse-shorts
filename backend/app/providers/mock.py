"""Offline providers so the full agent runs end-to-end with no API keys.
Images are procedurally generated placeholders; the script is canned/templated."""
from __future__ import annotations
import colorsys, hashlib, json, math, random, re
from pathlib import Path
from PIL import Image, ImageDraw, ImageFilter, ImageFont
from .. import config as C
from .base import Segment, Transcript

NEURON_SCENES = [
    ("Right now, about eighty six billion neurons are firing inside your head. Here's how one of them actually fires.",
     "Cinematic macro of a glowing pyramidal neuron in deep blue space, bioluminescent dendrites", ["neuron"]),
    ("Each neuron has three key parts. Dendrites catch signals, the cell body adds them up, and the axon carries the message away. "
     "Scientists have spent more than a century mapping every one of these tiny branching structures in incredible detail.",
     "Anatomical 3D render of a single neuron with dendrites, soma and long axon, labeled-diagram style", ["dendrites", "cell body", "axon"]),
    ("At rest, the inside of the cell sits at about minus seventy millivolts, held there by ion pumps.",
     "Cross-section of a neuron membrane with sodium and potassium ion channels, glowing ions", ["ion channel", "membrane"]),
    ("When enough input arrives, sodium channels snap open. Positive ions rush in and the voltage spikes.",
     "Sodium ions flooding through open channels in a neuron membrane, electric cyan light", ["sodium channel"]),
    ("That spike, the action potential, races down the axon, jumping between gaps in the myelin.",
     "Electric pulse travelling along a myelinated axon, nodes of Ranvier glowing", ["myelin sheath", "axon"]),
    ("At the end, it reaches the synapse and releases chemical messengers to the next neuron.",
     "Synapse close-up releasing neurotransmitter vesicles across a gap, purple and gold", ["synapse", "vesicles"]),
    ("One spark, a thousand times a second, across billions of cells. That's a thought. Follow for more brain science.",
     "Vast neural network lighting up like a galaxy, cinematic wide shot", ["neural network"]),
]

def _generic_scenes(topic: str):
    t = topic.strip().rstrip("?")
    return [
        (f"{t}. It's happening inside you right now, and most people never think about it.", f"Cinematic macro visual of {t}", ["structure"]),
        (f"First, meet the main structure behind {t.lower()}.", f"Anatomical 3D render explaining {t}", ["main structure"]),
        ("Here's the part that surprises everyone: it works automatically, every second of your life.", f"Close-up detail of {t}", ["detail"]),
        ("Each step hands off to the next, like a perfectly timed relay.", f"Step by step process diagram of {t}", ["step one", "step two"]),
        ("Now you know what's going on in there. Follow for more body science.", f"Wide cinematic shot related to {t}", ["overview"]),
    ]

_NUM = {"zero","one","two","three","four","five","six","seven","eight","nine","ten","twenty","thirty","forty","fifty","sixty","seventy","eighty",
        "ninety","hundred","thousand","million","billion","minus"}
def _sentences(t): return [x.strip() for x in re.split(r"(?<=[.!?])\s+", t) if len(x.strip()) > 20]
def _nums(t): return {w for w in re.findall(r"[a-z]+|\d+", t.lower()) if w in _NUM or w.isdigit()}
def _best_sentence(line, text):
    lw = set(re.findall(r"[a-z]{4,}", line.lower()))
    return max(_sentences(text), key=lambda s: len(lw & set(re.findall(r"[a-z]{4,}", s.lower()))), default="")

class MockLLM:
    name = "Mock LLM (offline)"
    def complete_json_ex(self, system, user, schema_hint=""):
        return self.complete_json(system, user, schema_hint), ""
    def complete_json(self, system: str, user: str, schema_hint: str = "") -> dict:
        task = re.search(r"\[task:(\w+)\]", system).group(1)
        data = json.loads(user) if user.strip().startswith("{") else {"topic": user}
        if task == "plan":
            topic = data["topic"]
            return {"title": topic.title() if len(topic) < 40 else topic[:40],
                    "audience": "curious scrollers, 16-35", "angle": "one vivid mechanism, explained in under a minute",
                    "hook": "Open on a surprising number", "target_seconds": data.get("target_seconds", 45),
                    "beats": ["hook", "anatomy", "mechanism", "payoff", "cta"],
                    "claims": [{"point": sent, "source_id": src["id"]} for src in data.get("sources", [])[:4]
                               for sent in _sentences(src.get("text", ""))[:1]]}
        if task == "domain":
            return {"domain": "general", "reason": "offline mock: no strict-domain keywords"}
        if task == "write":
            scenes = NEURON_SCENES if "neuron" in data["topic"].lower() else _generic_scenes(data["topic"])
            return {"scenes": [{"narration": n, "visual_prompt": v, "structures": s,
                                "on_screen_text": s[0].title()} for n, v, s in scenes],
                    "hashtags": ["#neuroscience", "#brain", "#learnontiktok", "#science"],
                    "caption": f"{data['topic']} in under a minute 🧠⚡"}
        if task == "critique":
            # Heuristic stand-in for the LLM critic: flag over-long scenes for pacing.
            issues = []
            for i, s in enumerate(data["scenes"]):
                wc = len(s["narration"].split())
                if wc > 30:
                    issues.append({"scene": i, "type": "pacing", "detail": f"{wc} words is too long for one shot; split or tighten to <=28."})
            return {"approved": not issues, "score": 9 if not issues else 6, "issues": issues,
                    "notes": "Facts consistent with standard neuroscience texts." if not issues else "Tighten pacing."}
        if task == "rewrite":
            s = data["scene"]["narration"]
            first = re.split(r"(?<=[.!?])\s+", s)
            return {"narration": " ".join(first[:2])}
        if task == "scope":
            return {"allowed": True, "category": "ok", "reason": "", "suggestion": "", "topic_clean": data["topic"],
                    "search_queries": [data["topic"]]}
        if task == "write_sourced":
            srcs = {x["id"]: x["text"] for x in data["sources"]}
            first = _sentences(srcs.get("W1", next(iter(srcs.values()))))
            neuron = "neuron" in data["topic"].lower()
            base = NEURON_SCENES if neuron else _generic_scenes(data["topic"])
            scenes = []
            for i, (n, v, st) in enumerate(base[:6]):
                cl = first[i % len(first)] if first else n
                line = {"kind": "claim", "text": cl, "source_id": "W1", "quote": cl.rstrip(".")}
                lines = [line]
                if i == 0:
                    lines.insert(0, {"kind": "framing", "text": "Stay with me for a minute.", "source_id": None, "quote": None})
                if i == len(base[:6]) - 1:
                    lines.append({"kind": "framing", "text": "Follow for more body science.", "source_id": None, "quote": None})
                if neuron and i == 4:  # planted flaw so the offline demo shows the claim gate working
                    lines.append({"kind": "claim", "text": "In the fastest neurons the signal zips along at three hundred metres per second.",
                                  "source_id": "P1", "quote": "reaching about one hundred and twenty metres per second"})
                scenes.append({"lines": lines, "visual_prompt": v, "structures": st, "on_screen_text": st[0].title()})
            return {"scenes": scenes, "hashtags": ["#neuroscience", "#brain", "#science"], "caption": f"{data['topic']}, sourced 🧠"}
        if task == "more_queries":
            return {"queries": [f"{data['topic']} physiology", f"{data['topic']} mechanism"]}
        if task == "extend_sourced":
            have = " ".join(" ".join(x["lines"]) for x in data["current_script"]).lower()
            out = []
            for src in data["sources"]:
                for snt in _sentences(src["text"]):
                    if snt.lower().rstrip(".") in have or len(snt) > 200:
                        continue
                    out.append({"lines": [{"kind": "claim", "text": snt, "source_id": src["id"], "quote": snt.rstrip(".")}],
                                "visual_prompt": f"Cinematic visualization of {data['topic']}", "structures": ["main structure"], "on_screen_text": "More"})
                    have += " " + snt.lower()
            return {"scenes": out[:4]}
        if task == "translate":
            tag = {"Yoruba": "yo", "Hausa": "ha", "Igbo": "ig"}.get(data.get("language", ""), "pcm")
            return {"lines": [{"id": x["id"], "text": f"[{tag}] {x['text']}"} for x in data["lines"]]}
        if task == "back_translate":
            return {"lines": [{"id": x["id"], "text": re.sub(r"^\[\w+\] ", "", x["text"])} for x in data["lines"]]}
        if task == "check_meaning":
            return {"lines": [{"id": x["id"], "verdict": "same" if x["back_translation"].strip() == x["original"].strip() else "changed",
                               "reason": "" } for x in data["lines"]]}
        if task == "check_framing":
            return {"verdict": "unsupported" if _nums(data["line"]) else "supported", "reason": "states a number" if _nums(data["line"]) else ""}
        if task == "check_claim":
            line, src = data["line"], data["source"]["text"]
            bad = _nums(line) - _nums(src)
            if bad:
                return {"verdict": "contradicted", "reason": f"source gives a different value (line says {', '.join(sorted(bad))})",
                        "supporting_quote": None, "fix": _best_sentence(line, src)}
            q = _best_sentence(line, src)
            return {"verdict": "supported", "reason": "", "supporting_quote": q.rstrip("."), "fix": ""}
        if task == "rewrite_claim":
            best_id, best = max(((x["id"], _best_sentence(data["line"], x["text"])) for x in data["sources"]),
                                key=lambda t: len(set(re.findall(r"[a-z]{4,}", data["line"].lower())) & set(re.findall(r"[a-z]{4,}", t[1].lower()))))
            return {"drop": False, "text": f"Myelinated axons conduct at up to about one hundred and twenty metres per second." if "metres" in data["line"] else best,
                    "source_id": best_id, "quote": best.rstrip(".") if "metres" not in data["line"] else "up to about one hundred and twenty metres per second"}
        raise ValueError(task)

def _font(size):
    for p in [C.FONT_DIR / "Inter/Inter-VariableFont_opsz,wght.ttf", Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")]:
        if p.exists():
            return ImageFont.truetype(str(p), size)
    return ImageFont.load_default()

class MockImage:
    name = "Placeholder art (mock Muse Image)"
    def generate(self, prompt, out_path, seed=0, aspect="1080x1920"):
        W, H = 1080, 1920
        rnd = random.Random(f"{prompt}{seed}")
        hue = rnd.random()
        import numpy as np
        c1 = np.array(colorsys.hsv_to_rgb(hue, .8, .2)) * 255
        c2 = np.array(colorsys.hsv_to_rgb((hue + .15) % 1, .9, .04)) * 255
        t = np.linspace(0, 1, H)[:, None, None]
        base = Image.fromarray(np.broadcast_to(c1 * (1 - t) + c2 * t, (H, W, 3)).astype("uint8"))
        glow = Image.new("RGB", (W, H))
        g = ImageDraw.Draw(glow)
        boxes = []
        names = [x.strip(" .") for x in prompt.split("clearly showing:")[1].split(". Make")[0].split(",")] if "clearly showing:" in prompt else ["subject"]
        # Deterministic demo flaw (like a real model forgetting a part): on the first seed, about half the multi-structure frames omit the last one.
        draw_names = names[:-1] if (seed == 0 and len(names) >= 2 and C.MOCK_FLAWS and int(hashlib.sha1(prompt.encode()).hexdigest(), 16) % 2 == 0) else names
        n = len(draw_names)
        for i in range(n):
            cx, cy = rnd.randint(250, W - 250), int(H * (0.28 + 0.5 * (i + .5) / n)) + rnd.randint(-80, 80)
            r = rnd.randint(70, 130)
            col = tuple(int(v * 255) for v in colorsys.hsv_to_rgb((hue + .5 + .1 * i) % 1, .7, 1))
            for _ in range(rnd.randint(6, 10)):   # dendrite-like branches
                a = rnd.random() * 2 * math.pi; L = rnd.randint(180, 420)
                x0, y0 = cx, cy
                for s in range(6):
                    a += rnd.uniform(-.5, .5)
                    x1, y1 = x0 + math.cos(a) * L / 6, y0 + math.sin(a) * L / 6
                    g.line([x0, y0, x1, y1], fill=col, width=max(2, 12 - 2 * s)); x0, y0 = x1, y1
            g.ellipse([cx - r, cy - r, cx + r, cy + r], fill=col)
            boxes.append([cx - r - 40, cy - r - 40, cx + r + 40, cy + r + 40])
        for _ in range(140):  # bokeh particles
            x, y, r = rnd.randint(0, W), rnd.randint(0, H), rnd.randint(2, 9)
            g.ellipse([x - r, y - r, x + r, y + r], fill=(200, 220, 255))
        glow_b = glow.filter(ImageFilter.GaussianBlur(28))
        img = Image.blend(base, glow_b, .55)
        img = Image.composite(glow.filter(ImageFilter.GaussianBlur(3)), img, glow.convert("L").point(lambda v: 255 if v > 40 else 0).filter(ImageFilter.GaussianBlur(4)))
        d = ImageDraw.Draw(img)
        d.text((40, H - 70), "placeholder art · swap in Muse Image", font=_font(26), fill=(255, 255, 255, 90))
        img.save(out_path)
        Path(out_path + ".boxes.json").write_text(json.dumps(dict(zip(draw_names, boxes))))
        return out_path

class MockSAM:
    name = "Mock SAM (reads placeholder layout)"
    def segment(self, image_path, phrase):
        p = Path(image_path + ".boxes.json")
        boxes = json.loads(p.read_text()) if p.exists() else {}
        return [Segment(phrase, tuple(boxes[phrase]))] if phrase in boxes else []

class NoASR:
    name = "none"
    def transcribe(self, wav_path, keywords=None):
        return Transcript("")
