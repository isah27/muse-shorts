# Creator guide: make a muse-shorts Short yourself

This is for the creator (no ML knowledge needed). You type commands in a terminal from the `muse-shorts` folder.
English Shorts need steps 1-4 only. **Pidgin (pcm), Yoruba (yo), Hausa (ha) and Igbo (ig)** Shorts also need steps 5-10, where the voice is recorded on Kaggle.

## 1. Start the app (two terminals)

Terminal 1, the backend (API on http://localhost:8000):

```bash
cd muse-shorts/backend
source ../.venv/bin/activate
uvicorn app.main:app --port 8000
```

Terminal 2, the website (http://localhost:3000):

```bash
cd muse-shorts/web
npm install        # first time only
npm run dev
```

API keys go in your own environment or `.env` file. Never paste them into chat, logs or commits.

## 2. Pick a topic and a language
Open http://localhost:3000, type a science topic (for example "How vaccines train the immune system"), and choose the language.

## 3. Generate
Press Generate. The agent finds sources, writes the script, fact-checks each claim, translates, and renders the video. That takes a few minutes. The finished run is saved in `outputs/<date>-<time>-<topic>-<lang>/`.

## 4. Review
Watch the video. Check the facts, the sound and the meaning. Then approve or reject it on the review page (it calls `POST /api/shorts/<id>/review`). Only approved Shorts show in the gallery and can be exported.
For English you're done here.

## 5. Export the lines to record (pcm / yo / ha / ig)

```bash
python scripts/export_lines.py --lang yo outputs/<your-yo-run> --notebook ../kaggle_wz
# several languages in one Kaggle run:
python scripts/export_lines.py --lang ha outputs/<ha-run> --lang ig outputs/<ig-run> --notebook ../kaggle_wz
```

This writes `../kaggle_wz/c_langs.html`, a page that holds the notebook code.

## 6. Open the Kaggle notebook
Go to https://www.kaggle.com/code/isahneziru/notebook1fee2be9d7/edit and sign in as isahneziru. Check that the accelerator is **GPU T4 x2** and that the `wazobia-bundle` dataset is attached.

## 7. Paste the code
Open `c_langs.html` in your browser, click in the text box, press Ctrl+A and then Ctrl+C.
In Kaggle, click inside the code cell and **select the whole cell** with Ctrl+Home and then Ctrl+Shift+End. Then paste with Ctrl+V. If you don't select everything first, the paste lands in the middle of the old code.

## 8. Run it
Click **Save Version**, then **Save & Run All (Commit)**, then Save. It takes about 45-60 minutes. You can close the tab while it runs.

## 9. Download and import the voice
When the version finishes, open it, go to **Output**, and download `wz_out.zip`. Then import it:

```bash
python scripts/import_wz.py ~/Downloads/wz_out.zip --topic vaccines     # add --force to replace an existing import
```

This puts each language in `assets/wazobia/<topic>-<lang>/`, with its wavs and `manifest.json`. It refuses to import a language whose run didn't finish.
To do it by hand instead: unzip the file, then copy each `<lang>/` folder to `assets/wazobia/<topic>-<lang>/`. For an old single-language zip, rename `runs.json` to `manifest.json`.

## 10. Re-voice, check, approve

```bash
cd backend && source ../.venv/bin/activate
PCM_ENGINE=wazobia python scripts/revoice.py <run-folder-name>   # folder name inside outputs/, not a path
```

This makes a new folder, `outputs/<date>-...-<lang>-revoice/`, that uses the Kaggle voice. Watch the new `video.mp4` and check the sound and meaning, then approve it in the UI (step 4). You can also approve it by setting `"status": "approved"` and adding `"review": {"decision": "approve", "reviewer": "Isah"}` in its `share.json`.

## Troubleshooting

| Problem | What to do |
|---|---|
| **"Kernel died"** on Kaggle | Each language runs in its own worker, so the other languages are kept. The importer will refuse the failed language. Run steps 5-9 again for just that language. |
| **Re-voice STOPS with "missing pre-rendered line"** | The script text changed after you exported, or that language wasn't imported. Run steps 5-9 again for that run. The app never falls back to another voice for yo/ha/ig. |
| **Garbled letters (ẹ ọ ƙ ɗ ị ụ show as junk)** | The code page lost its UTF-8 setting. Make the page again with `export_lines.py`, which adds `<meta charset="utf-8">` itself, and don't copy from a page that looks garbled. |
| **IndentationError on Kaggle** | The paste went into the middle of the old code. Select the whole cell (step 7) and paste again. |
| **Notebook stuck at "loading model"** | Re-run it. The notebook copies the model to local disk first, and loading normally takes about 15 seconds. |
| **Video is longer than 75 s** | This is allowed when every claim is verified (`all_verified`). The hard cap is 100 s. The Kaggle voice is slower than the planned pacing and doesn't follow the speed setting. Shorten the script if you want it under 75 s. |
| **Clip ends with long silence** | Already handled: the notebook trims silence below -50 dB. |

## Why the 86 s Igbo Short passed the length check
The final check (`backend/app/agent/orchestrator.py`, `finish_short`) accepts a video longer than `IDEAL_MAX_SECONDS` (75 s) when every claim is verified (`proof.all_verified`), up to `MAX_SECONDS` (100 s). The Igbo run had `all_verified=true` and 86.3 s, so it passed by design. That matches the rule "longer is fine when the facts support it".
The length estimate said 48 s, because it assumes about 2.7 words per second. The pre-recorded ngozi audio is slower than that and ignores `voice_speed`, which explains the gap. This is not a bug, so the behaviour was left unchanged.
