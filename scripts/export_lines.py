"""Export a translated Short's narration lines (pcm/yo/ha/ig) for the WazobiaVoice Kaggle run.
usage: python scripts/export_lines.py --lang yo outputs/<run-yo> [--lang ha outputs/<run-ha> ...] [--notebook ../kaggle_wz]
Each --lang/run pair writes <run>/<lang>_lines.json. With --notebook DIR it builds ONE notebook for all given languages
(one subprocess worker per language, so a kernel crash in one does not lose the others): DIR/notebook_langs.py + .ipynb
+ c_langs.html (UTF-8 textarea page for pasting into Kaggle). Unzip the result as assets/wazobia/<topic>-<lang>/ per language."""
import argparse, html, json, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from app.media.wazobia import text_hash, norm_text  # noqa: E402

LANGS = ("pcm", "yo", "ha", "ig")


def lines_for(run: Path, lang: str) -> list[dict]:
    st = json.loads((run / "state.json").read_text())
    got = st.get("language") or st.get("opts", {}).get("language")
    if got != lang:
        raise SystemExit(f"{run} is a '{got}' run, not '{lang}'")
    if not (st.get("proof") or {}).get("translation"):
        raise SystemExit(f"{run} has no verified translation; run the translation gate first")
    return [{"index": i, "hash": text_hash(s["narration"]), "text": norm_text(s["narration"])} for i, s in enumerate(st["scenes"])]


def build_notebook(by_lang: dict, template: Path, out_dir: Path, source: str, stem: str = "langs") -> dict:
    code = template.read_text().replace("LINES_JSON = None  # filled by scripts/export_lines.py",
                                        "LINES_JSON = " + repr(json.dumps(by_lang, ensure_ascii=False)) + f"  # from {source}")
    assert "LINES_JSON = None" not in code
    compile(code, "notebook", "exec")
    py, ipynb, page = out_dir / f"notebook_{stem}.py", out_dir / f"notebook_{stem}.ipynb", out_dir / f"c_{stem}.html"
    py.write_text(code, encoding="utf-8")
    nb = {"cells": [{"cell_type": "code", "metadata": {}, "execution_count": None, "outputs": [],
                     "source": code.splitlines(keepends=True)}],
          "metadata": {"kernelspec": {"name": "python3", "display_name": "Python 3", "language": "python"}},
          "nbformat": 4, "nbformat_minor": 5}
    ipynb.write_text(json.dumps(nb, indent=1, ensure_ascii=False), encoding="utf-8")
    page.write_text('<meta charset="utf-8">\n<textarea id=t rows=40 cols=100>' + html.escape(code) + "</textarea>", encoding="utf-8")
    return {"py": py, "ipynb": ipynb, "html": page}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--lang", action="append", choices=LANGS, required=True)
    ap.add_argument("runs", nargs="+")
    ap.add_argument("--notebook", help="kaggle_wz dir holding notebook_langs_template.py")
    ap.add_argument("--stem", default="langs")
    a = ap.parse_intermixed_args(argv)
    if len(a.lang) != len(a.runs):
        ap.error("give one run per --lang, in the same order")
    by_lang = {}
    for lang, r in zip(a.lang, a.runs):
        run = Path(r) if Path(r).is_absolute() or Path(r).exists() else ROOT / "outputs" / r
        by_lang[lang] = lines_for(run, lang)
        out = run / f"{lang}_lines.json"
        out.write_text(json.dumps({"run": run.name, "lang": lang, "lines": by_lang[lang]}, indent=2, ensure_ascii=False))
        print(f"{lang}: {len(by_lang[lang])} lines -> {out}")
    if a.notebook:
        d = Path(a.notebook)
        f = build_notebook(by_lang, d / "notebook_langs_template.py", d, ", ".join(Path(r).name for r in a.runs), a.stem)
        print("notebook ->", f["py"], f["html"])
    return by_lang


if __name__ == "__main__":
    main()
