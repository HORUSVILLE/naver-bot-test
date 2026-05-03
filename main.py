from pathlib import Path
from playwright.sync_api import sync_playwright

output_dir = Path("output")
output_dir.mkdir(exist_ok=True)

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()
    page.goto("https://www.naver.com", wait_until="domcontentloaded", timeout=60000)
    page.screenshot(path=str(output_dir / "naver_home.png"), full_page=True)
    browser.close()

print("Done")
