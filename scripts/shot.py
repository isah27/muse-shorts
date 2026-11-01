"""Screenshot helper: shot.py <url> <out.png> [width height] [full] [click-text] [wait-ms]"""
import sys
from playwright.sync_api import sync_playwright
url, out = sys.argv[1], sys.argv[2]
w, h = (int(sys.argv[3]), int(sys.argv[4])) if len(sys.argv) > 4 else (1440, 900)
full = len(sys.argv) > 5 and sys.argv[5] == "full"
wait = int(sys.argv[7]) if len(sys.argv) > 7 else 3000
with sync_playwright() as p:
    b = p.chromium.launch(executable_path="/usr/bin/google-chrome", args=["--no-sandbox"])
    pg = b.new_page(viewport={"width": w, "height": h}, device_scale_factor=2 if w < 600 else 1)
    pg.goto(url); pg.wait_for_timeout(wait)
    if len(sys.argv) > 6 and sys.argv[6] != "-":
        pg.get_by_text(sys.argv[6], exact=False).first.click(); pg.wait_for_timeout(1200)
    pg.screenshot(path=out, full_page=full); b.close()
