"""배포된 앱을 방문해 잠들지 않게 하고, 잠들어 있으면 깨운다 (GitHub Actions에서 매시간 실행).

Streamlit Community Cloud 는 12시간 동안 방문이 없으면 앱을 재운다. 심사 기간 동안 심사위원이
'앱 깨우기' 버튼을 누르고 기다리지 않도록 주기적으로 방문한다.
GitHub 예약 실행은 몇 시간씩 밀리거나 빠지기도 해서 매시간 돌리고, 잠든 앱은 깨어날 때까지 기다린다.
실행: python scripts/keep_awake.py [앱 주소]   (playwright 필요)
"""
import re
import sys
import time

from playwright.sync_api import sync_playwright

URL = sys.argv[1] if len(sys.argv) > 1 else "https://siheomgak.streamlit.app/"
READY = "학과 우선순위"            # 관리자 대시보드가 다 그려지면 보이는 문구
WAKE = re.compile(r"back up|wake", re.I)   # 잠든 앱 화면의 'Yes, get this app back up!' 버튼
ATTEMPTS, WAIT_SEC = 3, 240


def page_text(page) -> str:
    out = []
    for f in page.frames:
        try:
            out.append(f.locator("body").inner_text(timeout=5000))
        except Exception:
            pass
    return re.sub(r"\s+", " ", " ".join(out))


def click_wake(page) -> bool:
    """잠든 앱 화면이면 (어느 프레임에 있든) 깨우기 버튼을 누른다."""
    for f in page.frames:
        try:
            btn = f.get_by_role("button", name=WAKE)
            if btn.count():
                btn.first.click()
                return True
        except Exception:
            pass
    return False


ok, text = False, ""
with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page()
    for attempt in range(1, ATTEMPTS + 1):
        try:
            page.goto(URL, wait_until="domcontentloaded", timeout=120_000)
        except Exception as e:
            print(f"{attempt}회차: 접속 실패 ({e})")
            continue
        deadline = time.time() + WAIT_SEC
        while time.time() < deadline:
            page.wait_for_timeout(10_000)
            if click_wake(page):
                print(f"{attempt}회차: 잠든 앱을 깨웁니다.")
            text = page_text(page)
            if READY in text:
                ok = True
                break
        if ok:
            break
        print(f"{attempt}회차: 앱이 아직 뜨지 않아 다시 시도합니다.")
    browser.close()

print("상태:", "정상" if ok else "확인 필요")
print(text[:800])
sys.exit(0 if ok else 1)
