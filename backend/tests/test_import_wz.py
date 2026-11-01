import json, sys, zipfile
from pathlib import Path
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from import_wz import import_zip


def _zip(tmp, files):
    zp = tmp / "wz_out.zip"
    with zipfile.ZipFile(zp, "w") as z:
        for n, c in files.items(): z.writestr(n, c)
    return zp


def _man(lang): return json.dumps({"lang": lang, "lines": [{"index": 0, "hash": "a" * 16, "file": "00_a.wav", "text": "x"}]})


def test_multi_lang(tmp_path):
    runs = {"kind": "lines-by-lang", "runs": [{"lang": "ha", "ok": True}, {"lang": "ig", "ok": True}]}
    zp = _zip(tmp_path, {"runs.json": json.dumps(runs), "ha/manifest.json": _man("ha"), "ha/00_a.wav": b"R",
                         "ig/manifest.json": _man("ig"), "ig/00_a.wav": b"R"})
    out = import_zip(zp, "vaccines", tmp_path / "assets")
    assert [p.name for p in out] == ["vaccines-ha", "vaccines-ig"]
    assert (tmp_path / "assets/vaccines-ig/manifest.json").exists()
    with pytest.raises(SystemExit): import_zip(zp, "vaccines", tmp_path / "assets")   # no overwrite without force
    import_zip(zp, "vaccines", tmp_path / "assets", force=True)


def test_single_runs_json_becomes_manifest(tmp_path):
    zp = _zip(tmp_path, {"runs.json": _man("pcm"), "00_a.wav": b"R"})
    out = import_zip(zp, "t", tmp_path / "a")
    assert (out[0] / "manifest.json").exists() and out[0].name == "t-pcm"


def test_failed_run_and_missing_wav(tmp_path):
    zp = _zip(tmp_path, {"runs.json": json.dumps({"kind": "lines-by-lang", "runs": [{"lang": "yo", "ok": False}]})})
    with pytest.raises(SystemExit): import_zip(zp, "v", tmp_path / "a")
    zp = _zip(tmp_path, {"runs.json": _man("yo")})
    with pytest.raises(SystemExit): import_zip(zp, "v", tmp_path / "b")
