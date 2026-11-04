"""배포 앱의 화면 파일(static js)을 동시에 몇 개씩 받느냐에 따라 500 오류가 달라지는지 잰다 (진단용, 수동 실행).
실행: python scripts/diag_static.py https://siheomgak.streamlit.app/
"""
import re
import sys
import time
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

BASE = (sys.argv[1] if len(sys.argv) > 1 else "https://siheomgak.streamlit.app").rstrip("/") + "/~/+/"
UA = {"User-Agent": "Mozilla/5.0 (siheomgak keep-awake diagnostic)"}


def get(url):
    t = time.time()
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
            r.read()
            return r.status, time.time() - t
    except urllib.error.HTTPError as e:
        return e.code, time.time() - t
    except Exception as e:  # noqa: BLE001
        return type(e).__name__, time.time() - t


status, _ = get(BASE)
print("index", status)
html = urllib.request.urlopen(urllib.request.Request(BASE, headers=UA), timeout=60).read().decode()
files = sorted(set(re.findall(r'(?:src|href)="\./(static/[^"]+\.(?:js|css))"', html)))
print("index.html 이 바로 받는 파일:", len(files))
if not files:
    print(html[:500])
    sys.exit(1)

for workers in (1, 4, 16, 64):
    for rnd in range(3):
        urls = [BASE + f + f"?d={workers}-{rnd}-{time.time():.0f}" for f in files]   # 매번 새 요청 (캐시 피함)
        t = time.time()
        with ThreadPoolExecutor(workers) as ex:
            res = list(ex.map(get, urls))
        c = Counter(s for s, _ in res)
        slow = max(d for _, d in res)
        print(f"동시 {workers:>2}개 · {rnd + 1}회차: {dict(c)}  최장 {slow:.1f}초  전체 {time.time() - t:.1f}초")
    time.sleep(3)

for p in ("_stcore/health",) * 10:
    print("health", get(BASE + p))
