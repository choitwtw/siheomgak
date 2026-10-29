"""배포된 앱을 방문해 잠들지 않게 하고, 잠들어 있으면 깨운다 (GitHub Actions에서 6시간마다 실행).

Streamlit Community Cloud 는 12시간 동안 방문이 없으면 앱을 재운다. 심사 기간 동안 심사위원이
'앱 깨우기' 버튼을 누르고 기다리지 않도록 주기적으로 방문한다.
실행: python scripts/keep_awake.py [앱 주소]   (playwright 필요)
"""
import re
import sys

from playwright.sync_api import sync_playwright

URL = sys.argv[1] if len(sys.argv) > 1 else "https://siheomgak.streamlit.app/"


def page_text(page) -> str:
    out = []
    for f in page.frames:
        try:
            out.append(f.locator("body").inner_text(timeout=5000))
        except Exception:
            pass
    return re.sub(r"\s+", " ", " ".join(out))


with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page()
    page.goto(URL, wait_until="domcontentloaded", timeout=120_000)
    page.wait_for_timeout(15_000)
    wake = page.get_by_role("button", name=re.compile("get this app back up", re.I))
    if wake.count():
        print("앱이 잠들어 있어 깨웁니다.")
        wake.first.click()
        page.wait_for_timeout(90_000)
    text = ""
    for _ in range(12):   # 첫 배정이 끝나 화면이 나올 때까지 최대 2분
        text = page_text(page)
        if "학과 우선순위" in text:
            break
        page.wait_for_timeout(10_000)
    browser.close()

ok = "학과 우선순위" in text
print("상태:", "정상" if ok else "확인 필요")
print(text[:800])
sys.exit(0 if ok else 1)
