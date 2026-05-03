from pathlib import Path
from urllib.parse import quote
from playwright.sync_api import sync_playwright

output_dir = Path("output")
output_dir.mkdir(exist_ok=True)

query = "용인시 신규사업자"
url = f"https://search.naver.com/search.naver?query={quote(query)}"

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width": 1440, "height": 2200})
    page.goto(url, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(5000)  # 5초 기다리기
    page.screenshot(path=str(output_dir / "naver_search.png"), full_page=True)
    browser.close()

print("Done")
