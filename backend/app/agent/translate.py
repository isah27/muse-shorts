"""Translation gate: verified English script -> Yoruba / Nigerian Pidgin, checked by back-translation.

Each spoken line is translated in place (it keeps its claim id, source_id and verbatim English quote, so proof.json
still ties every translated claim to its source). The translation is then translated BACK to English by a separate
call that never sees the original, and the claim critic compares meaning line by line. A line whose meaning changed
is re-translated with the critic's reason (up to MAX_ROUNDS times); if it still differs it is flagged, never hidden.
"""
from __future__ import annotations
import json, unicodedata
from typing import Callable
from . import prompts as P
from .claims import _ask

LANGS = {"yo": "Yoruba", "pcm": "Nigerian Pidgin", "ha": "Hausa", "ig": "Igbo"}
MAX_ROUNDS = 2


def nfc(t: str) -> str:
    return unicodedata.normalize("NFC", (t or "").strip())


def _lines(scenes):
    for si, s in enumerate(scenes):
        for li, l in enumerate(s["lines"]):
            yield f"{si + 1}.{li + 1}", s, l


def _ensure_en(scenes):
    for s in scenes:
        s.setdefault("narration_en", s["narration"])
        for l in s["lines"]:
            l.setdefault("text_en", l["text"])


def _map(d: dict) -> dict[str, str]:
    out = {}
    for x in (d or {}).get("lines") or []:
        if isinstance(x, dict) and x.get("id") is not None and str(x.get("text", "")).strip():
            out[str(x["id"])] = nfc(str(x["text"]))
    return out


def translate_scenes(scenes: list[dict], lang: str, writer, critic, emit: Callable[..., None], max_rounds: int = MAX_ROUNDS) -> dict:
    """Mutates scenes: line['tr'] + line['text'] become the target language (English kept in text_en / narration_en)."""
    if lang not in LANGS:
        raise ValueError(f"unsupported language {lang}")
    name = LANGS[lang]
    _ensure_en(scenes)
    items = {i: l for i, _, l in _lines(scenes)}
    script_en = [{"id": i, "text": l["text_en"]} for i, l in items.items()]
    emit("translate", "running", f"Translating {len(items)} lines into {name}…")
    d, _ = _ask(writer, P.TRANSLATE, json.dumps({"language": name, "lines": script_en}, ensure_ascii=False), P.TRANSLATE_SCHEMA)
    tr = _map(d)
    missing = [i for i in items if i not in tr]
    if missing:   # one retry for lines the model skipped
        d, _ = _ask(writer, P.TRANSLATE, json.dumps({"language": name, "lines": [x for x in script_en if x["id"] in missing],
                                                     "context": script_en}, ensure_ascii=False), P.TRANSLATE_SCHEMA)
        tr.update(_map(d))
    if any(i not in tr for i in items):
        raise RuntimeError(f"translator skipped lines: {[i for i in items if i not in tr]}")
    state = {i: {"lang": lang, "text": tr[i], "rounds": 0, "history": []} for i in items}
    todo = list(items)
    for rnd in range(max_rounds + 1):
        # back-translate WITHOUT showing the original, then let the critic compare meaning
        bd, _ = _ask(writer, P.BACK_TRANSLATE, json.dumps({"language": name, "lines": [{"id": i, "text": state[i]["text"]} for i in todo]},
                                                           ensure_ascii=False), P.TRANSLATE_SCHEMA)
        back = _map(bd)
        cd, _ = _ask(critic, P.CHECK_MEANING, json.dumps({"lines": [{"id": i, "original": items[i]["text_en"], "back_translation": back.get(i, "")}
                                                                    for i in todo]}, ensure_ascii=False), P.CHECK_MEANING_SCHEMA)
        verdicts = {str(x.get("id")): x for x in (cd.get("lines") or []) if isinstance(x, dict)}
        bad = []
        for i in todo:
            v = verdicts.get(i) or {"verdict": "changed", "reason": "no verdict returned"}
            same = str(v.get("verdict", "")).lower() == "same" and back.get(i)
            st = state[i]
            st.update(back=back.get(i, ""), verdict="same" if same else "changed", reason=str(v.get("reason", ""))[:300])
            st["history"].append({"round": rnd + 1, "text": st["text"], "back": st["back"], "verdict": st["verdict"], "reason": st["reason"]})
            if not same:
                bad.append(i)
                emit("translate", "retry", f"Line {i}: meaning changed in back-translation ({st['reason'][:120]})",
                     kind="reject", line=i, round=rnd + 1)
        if not bad or rnd == max_rounds:
            break
        rd, _ = _ask(writer, P.TRANSLATE, json.dumps({"language": name, "context": script_en,
                                                      "lines": [{"id": i, "text": items[i]["text_en"], "previous": state[i]["text"],
                                                                 "back_translation": state[i]["back"], "problem": state[i]["reason"]} for i in bad]},
                                                     ensure_ascii=False), P.TRANSLATE_SCHEMA)
        for i, t in _map(rd).items():
            if i in state:
                state[i]["text"], state[i]["rounds"] = t, state[i]["rounds"] + 1
                emit("translate", "retry", f"Line {i}: re-translated (round {rnd + 1})", kind="rewrite", line=i, round=rnd + 1)
        todo = bad
    flagged = [i for i in items if state[i]["verdict"] != "same"]
    for i in flagged:
        state[i]["flagged"] = True
        emit("translate", "retry", f"Line {i}: still differs after {max_rounds} re-translations — flagged", kind="flag", line=i)
    for i, l in items.items():
        l["tr"], l["text"] = state[i], state[i]["text"]
    for s in scenes:
        s["narration"] = " ".join(t if t[-1:] in ".!?…" else t + "." for t in (l["text"].strip() for l in s["lines"]) if t)
        s["language"] = lang
    summary = {"language": lang, "language_name": name, "lines": len(items), "verified_same": len(items) - len(flagged),
               "rewritten": sum(1 for s in state.values() if s["rounds"]), "flagged": flagged,
               "method": "translate -> blind back-translation -> claim critic meaning check (re-translate up to 2x, then flag)"}
    emit("translate", "done", f"{summary['verified_same']}/{len(items)} lines keep their meaning in {name}"
         + (f" · {summary['rewritten']} re-translated" if summary["rewritten"] else "") + (f" · {len(flagged)} flagged" if flagged else ""),
         translation=summary, scenes=scenes)
    return summary
