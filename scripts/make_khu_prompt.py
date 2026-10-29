"""KHU CHAT(또는 다른 AI 도구)에 붙여 넣을 '학생 데이터 생성 요청문'을 만든다.

과목 시간표는 현재 기본 가상 데이터(data/sample/courses.csv)에서 가져온다.
실행: python scripts/make_khu_prompt.py  →  docs/KHU_CHAT_학생데이터_요청문.md
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.config import DEPARTMENTS, GENERAL_DEPT  # noqa: E402
from core.datagen import BASIC_COURSES, generate  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

ds = generate()
rows = []
for c in ds.course_map.values():
    days = "·".join("월화수목금"[d] for d in c.days)
    grades = "전 학년" if c.dept == GENERAL_DEPT else ",".join(map(str, c.grades)) + "학년"
    note = "1학년 공통 기초" if c.code in BASIC_COURSES else ("교양" if c.dept == GENERAL_DEPT else "")
    rows.append(f"| {c.code} | {c.name} | {c.dept} | {grades} | {days} {c.start // 60:02d}:{c.start % 60:02d}-{c.end // 60:02d}:{c.end % 60:02d} | {note} |")
table = "\n".join(rows)

doc = f"""# KHU CHAT 학생 데이터 생성 요청문

아래 **[요청문]** 전체를 복사해서 KHU CHAT에 붙여 넣으세요. 결과로 받은 `students.csv`, `enrollments.csv` 두 파일을
Claude에게 보내 주면 `data/custom/` 폴더에 넣어 앱의 기본 데이터로 반영합니다.

- 한 번에 500명을 다 만들면 답이 잘릴 수 있습니다. **100명씩 5번** 나눠 요청하세요
  (요청문 마지막 줄의 "학번 범위"만 바꿔서 다시 보내면 됩니다). 나눠 받은 파일은 그대로 보내 주시면 합쳐서 넣습니다.
- 과목 목록·시간은 앱의 현재 과목 데이터와 같아야 합니다. 과목을 바꾸고 싶으면 `courses.csv`도 함께 만들어 주세요.

---

## [요청문]

경희대학교 이과대학 기말고사 시험 일정 배정 프로그램에 넣을 **가상 학생 데이터**를 CSV로 만들어 줘.
실제 개인정보는 쓰지 말고 이름은 가상의 한국 이름으로 해 줘.

### 1. students.csv
컬럼(첫 줄 그대로): `student_id,name,major,grade,double_major,minor`
- student_id: 10자리 학번 = 입학연도 4자리 + 학과번호 2자리 + 일련번호 4자리 (예: 2025010001)
  - 학과번호: {", ".join(f"{d} {i + 1:02d}" for i, d in enumerate(DEPARTMENTS))}
  - 입학연도: 1학년 2026, 2학년 2025, 3학년 2024, 4학년 2023
- major: {", ".join(DEPARTMENTS)} 중 하나 (학과별 인원은 비슷하게)
- grade: 1~4
- double_major: 2학년 이상 중 약 15%만 다른 이과대학 학과 이름, 나머지는 빈칸
- minor: 2학년 이상 중 약 10%만 다른 이과대학 학과 이름, 나머지는 빈칸 (복수전공과 동시에 갖지 않음)

### 2. enrollments.csv
컬럼(첫 줄 그대로): `student_id,course_code`
- 학생 1명당 5~7과목. **아래 과목표의 과목코드만** 써.
- 한 학생이 듣는 과목끼리 **수업 요일·시간이 겹치면 안 돼** (실제 수강신청처럼). 이게 가장 중요해.
- 1학년은 1학년 공통 기초 과목 위주 + 주전공 1학년 과목, 2학년 이상은 주전공의 해당 학년 과목 위주로.
- 여러 학년 대상 과목(예: 2,3학년)은 해당 학년 누구나 들을 수 있어. 재수강으로 낮은 학년 과목을 듣는 학생도 조금 있어도 돼.
- 복수전공·부전공 학생은 그 학과 과목을 1~2개 포함.
- 교양 과목은 학생당 0~2개 (1학년은 2개 정도).
- 한 과목 수강생은 190명을 넘지 않게.

### 3. 과목표 (과목코드 | 과목명 | 개설학과 | 대상 | 수업 요일·시간 | 비고)

| 과목코드 | 과목명 | 개설학과 | 대상 | 수업 | 비고 |
|---|---|---|---|---|---|
{table}

### 4. 출력 형식
- `students.csv`와 `enrollments.csv`를 각각 코드 블록(```csv)으로, 설명 없이 CSV 내용만 출력해 줘.
- 첫 줄은 위에 적은 컬럼명 그대로, 쉼표 구분, 따옴표 없이.
- 이번에는 **학번 일련번호 0001~0100 (학과마다 고르게, 총 100명)** 만 만들어 줘.
"""
os.makedirs(os.path.join(ROOT, "docs"), exist_ok=True)
with open(os.path.join(ROOT, "docs", "KHU_CHAT_학생데이터_요청문.md"), "w", encoding="utf-8") as f:
    f.write(doc)
print("docs/KHU_CHAT_학생데이터_요청문.md 를 만들었습니다.")
