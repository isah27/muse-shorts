"""Export a Pidgin Short's narration lines for the WazobiaVoice Kaggle run.
usage: python scripts/export_pcm_lines.py [outputs/<run>-pcm] [-o lines.json] [--notebook ../kaggle_wz]
Defaults to the newest outputs/*-pcm folder. Writes lines.json ([{index, hash, text}]) and, with --notebook DIR,
DIR/notebook_lines.py + .ipynb + c_lines.html with the lines embedded (no dataset change needed)."""
import argparse, json, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from app.media.wazobia import text_hash, norm_text  # noqa: E402


def latest_pcm() -> Path:
    runs = sorted((ROOT / "outputs").glob("*-pcm"), key=lambda p: p.name)
    if not runs:
        sys.exit("no outputs/*-pcm run found")
    return runs[-1]


def lines_for(run: Path) -> list[dict]:
    st = json.loads((run / "state.json").read_text())
    if (st.get("language") or st.get("opts", {}).get("language")) != "pcm":
        sys.exit(f"{run} is not a Pidgin run")
    return [{"index": i, "hash": text_hash(s["narration"]), "text": norm_text(s["narration"])}
            for i, s in enumerate(st["scenes"])]


def build_notebook(lines: list[dict], template: Path, out_dir: Path, source: str):
    import html
    code = template.read_text().replace("LINES_JSON = None  # filled by scripts/export_pcm_lines.py",
                                        "LINES_JSON = " + repr(json.dumps(lines, ensure_ascii=False)) + f"  # from {source}")
    assert "LINES_JSON = None" not in code
    (out_dir / "notebook_lines.py").write_text(code)
    nb = {"cells": [{"cell_type": "code", "metadata": {}, "execution_count": None, "outputs": [],
                     "source": code.splitlines(keepends=True)}],
          "metadata": {"kernelspec": {"name": "python3", "display_name": "Python 3", "language": "python"}},
          "nbformat": 4, "nbformat_minor": 5}
    (out_dir / "notebook_lines.ipynb").write_text(json.dumps(nb, indent=1, ensure_ascii=False))
    (out_dir / "c_lines.html").write_text("<textarea id=t rows=40 cols=100>" + html.escape(code) + "</textarea>")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("run", nargs="?")
    ap.add_argument("-o", "--out")
    ap.add_argument("--notebook", help="kaggle_wz dir holding notebook_lines_template.py")
    a = ap.parse_args()
    run = Path(a.run) if a.run else latest_pcm()
    lines = lines_for(run)
    out = Path(a.out) if a.out else run / "pcm_lines.json"
    out.write_text(json.dumps({"run": run.name, "lines": lines}, indent=2, ensure_ascii=False))
    print(f"{len(lines)} lines -> {out}")
    if a.notebook:
        d = Path(a.notebook)
        build_notebook(lines, d / "notebook_lines_template.py", d, run.name)
        print(f"notebook -> {d / 'notebook_lines.py'}, {d / 'c_lines.html'}")
