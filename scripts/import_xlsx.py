"""학과 제공 형식의 엑셀(시트: 강의실·교수·과목·학생·수강내역)을 앱의 CSV 5종으로 바꿔 data/custom/ 에 저장한다.

실행: python scripts/import_xlsx.py <엑셀 파일>   (openpyxl 필요: pip install openpyxl)

변환 규칙
- 강의실: 강의실명 '공용강의실-A01' → 강의실ID 그대로, 건물 '공용강의실', 호실 'A01'. 공용여부 Y → 사용학과 '전체'.
  시험좌석은 좌석의 2/3(기본값), 대형강의실만 좌석 전체.
  과목의 정규강의실ID(R001 등)는 강의실명으로 바꿔 화면에서 알아보기 쉽게 한다.
- 교수 불가시간: '월 09:00-11:00|금 15:00-17:00' → '월 09:00-11:00; 금 15:00-17:00', '없음' → 빈칸.
- 과목 대상학년 '1|2' → '1,2'. 시험방식 별도시험/수업시간시험/시험없음은 앱이 그대로 인식한다.
- 학생 복수전공·부전공 '없음' → 빈칸.
"""
import os
import sys

import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data", "custom")


def none_blank(v: str) -> str:
    v = str(v).strip()
    return "" if v in ("없음", "nan", "-") else v


def convert(path: str) -> dict[str, pd.DataFrame]:
    x = pd.read_excel(path, sheet_name=None, dtype=str)
    x = {k.strip(): v.fillna("").apply(lambda s: s.str.strip()) for k, v in x.items()}

    r = x["강의실"]
    name_of = dict(zip(r["강의실ID"], r["강의실명"]))
    rooms = pd.DataFrame({
        "room_id": r["강의실명"],
        "building": r["강의실명"].str.rsplit("-", n=1).str[0],
        "room_no": r["강의실명"].str.rsplit("-", n=1).str[-1],
        "capacity": r["수용인원"],
        "departments": r["공용여부"].map(lambda v: "전체" if v.upper() == "Y" else v),
    })
    # 시험좌석: 기본은 좌석의 2/3(띄어 앉기). 단, 대형강의실은 좌석 전체를 쓴다 —
    # 2/3로는 145~155명 공통 과목 시험을 둘 강의실이 하나도 없기 때문.
    big = rooms["building"].str.contains("대형")
    rooms["exam_capacity"] = rooms["capacity"].where(big, "")

    p = x["교수"]
    professors = pd.DataFrame({
        "professor_id": p["교수ID"],
        "name": p["교수명"],
        "department": p["소속학과"],
        "unavailable": p["불가시간"].map(lambda v: "; ".join(s.strip() for s in none_blank(v).split("|") if s.strip())),
    })

    c = x["과목"]
    courses = pd.DataFrame({
        "course_code": c["과목ID"],
        "course_name": c["과목명"],
        "department": c["개설학과"],
        "target_grades": c["대상학년"].str.replace("|", ","),
        "professor_id": c["교수ID"],
        "class_days": c["정규수업요일"].str.replace("|", ","),
        "class_start": c["정규수업시작"],
        "class_end": c["정규수업종료"],
        "class_room": c["정규강의실ID"].map(lambda v: name_of.get(v, v)),
        "enrollment": c["수강인원"],
        "exam_type": c["시험방식"],
        "exam_minutes": c["시험시간분"],
    })

    s = x["학생"]
    students = pd.DataFrame({
        "student_id": s["학번"],
        "name": s["학생명"],
        "major": s["소속학과"],
        "grade": s["학년"],
        "double_major": s["복수전공학과"].map(none_blank),
        "minor": s["부전공학과"].map(none_blank),
    })

    e = x["수강내역"]
    enrollments = pd.DataFrame({"student_id": e["학번"], "course_code": e["과목ID"]})
    return dict(students=students, courses=courses, professors=professors, rooms=rooms, enrollments=enrollments)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    tables = convert(sys.argv[1])
    os.makedirs(OUT, exist_ok=True)
    for name, df in tables.items():
        df.to_csv(os.path.join(OUT, f"{name}.csv"), index=False, encoding="utf-8-sig")
        print(f"{name}.csv: {len(df)}행")
