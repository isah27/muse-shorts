"""Import a Kaggle WazobiaVoice result (wz_out.zip) into assets/wazobia/<topic>-<lang>/.
usage: python scripts/import_wz.py path/to/wz_out.zip --topic vaccines [--force]
The zip from the languages notebook holds runs.json (summary) and one folder per language (<lang>/manifest.json + wavs).
A single-language zip (manifest/runs.json + wavs at the top, with "lang") is also accepted; its runs.json becomes manifest.json.
Refuses a language whose run did not finish (ok=false) or whose wav files are missing."""
import argparse, json, shutil, sys, tempfile, zipfile
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]


def _check(d: Path) -> dict:
    m = json.loads((d / "manifest.json").read_text(encoding="utf-8"))
    missing = [l["file"] for l in m.get("lines", []) if not (d / l["file"]).exists()]
    if not m.get("lines") or missing:
        raise SystemExit(f"{d.name}: no lines or missing wavs {missing}")
    return m


def import_zip(zp: Path, topic: str, dest_root: Path, force: bool = False) -> list[Path]:
    out = []
    with tempfile.TemporaryDirectory() as td:
        t = Path(td); zipfile.ZipFile(zp).extractall(t)
        runs = json.loads((t / "runs.json").read_text(encoding="utf-8")) if (t / "runs.json").exists() else {}
        if runs.get("kind") == "lines-by-lang":
            items = []
            for r in runs["runs"]:
                if not r.get("ok"):
                    raise SystemExit(f"{r['lang']}: Kaggle run not ok ({r.get('lines_done')}/{r.get('lines_expected')} lines); re-run it")
                items.append((r["lang"], t / r["lang"]))
        else:
            if not (t / "manifest.json").exists():
                if not runs: raise SystemExit("zip has neither runs.json nor manifest.json")
                (t / "runs.json").rename(t / "manifest.json")
            lang = json.loads((t / "manifest.json").read_text(encoding="utf-8")).get("lang")
            if not lang: raise SystemExit("manifest has no 'lang'")
            items = [(lang, t)]
        for lang, d in items:
            _check(d)
            dest = dest_root / f"{topic}-{lang}"
            if dest.exists():
                if not force: raise SystemExit(f"{dest} exists; use --force to replace")
                shutil.rmtree(dest)
            dest.mkdir(parents=True)
            for f in d.iterdir():
                if f.is_file() and (f.suffix == ".wav" or f.name == "manifest.json"):
                    shutil.copy2(f, dest / f.name)
            out.append(dest)
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("zip"); ap.add_argument("--topic", required=True); ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    for p in import_zip(Path(a.zip), a.topic, ROOT / "assets" / "wazobia", a.force):
        print("imported", p.relative_to(ROOT))
