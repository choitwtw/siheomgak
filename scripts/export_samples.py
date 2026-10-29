"""data/templates (빈 템플릿) 와 data/sample (기본 가상 데이터) CSV를 다시 만든다.

실행: python scripts/export_samples.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.csvio import template_csv, write_dataset  # noqa: E402
from core.datagen import generate  # noqa: E402
from core.dataset import SCHEMAS  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

if __name__ == "__main__":
    tdir = os.path.join(ROOT, "data", "templates")
    os.makedirs(tdir, exist_ok=True)
    for t in SCHEMAS:
        with open(os.path.join(tdir, f"{t}.csv"), "wb") as f:
            f.write(template_csv(t))
    write_dataset(generate(), os.path.join(ROOT, "data", "sample"))
    print("템플릿과 샘플 데이터를 만들었습니다.")
