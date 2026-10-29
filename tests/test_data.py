from core.csvio import assemble, dataset_zip_bytes, parse_table, read_zip, to_csv_bytes
from core.datagen import GenConfig, generate
from core.priority import dept_weights, priority_order


def test_generator_default_scale(default_data):
    s = default_data.summary()
    assert s["학생"] == 500 and s["과목"] == 40 and s["교수"] == 25 and s["강의실"] >= 40
    assert (s["수업시간 시험"], s["별도 시험"], s["시험 없음"]) == (14, 22, 4)
    per_student = default_data.enrollments.groupby("student_id").size()
    assert per_student.min() >= 5 and per_student.max() <= 7
    multi = default_data.courses["target_grades"].str.contains(",").mean()
    assert 0.25 <= multi <= 0.35
    assert set(default_data.courses["exam_minutes"]) <= {60, 75, 90, 120}


def test_generator_reproducible():
    a, b = generate(GenConfig(seed=11)), generate(GenConfig(seed=11))
    assert a.enrollments.equals(b.enrollments) and a.courses.equals(b.courses)


def test_student_classes_never_overlap(default_data):
    cm = default_data.course_map
    for sid, codes in default_data.courses_of.items():
        blocks = [b for c in codes for b in cm[c].class_blocks()]
        for i in range(len(blocks)):
            for j in range(i + 1, len(blocks)):
                (d1, s1, e1), (d2, s2, e2) = blocks[i], blocks[j]
                assert not (d1 == d2 and s1 < e2 and s2 < e1), sid


def test_csv_roundtrip(default_data):
    tables, res = read_zip(dataset_zip_bytes(default_data))
    assert res.ok
    ds, res = assemble(tables)
    assert res.ok and ds.summary() == default_data.summary()


def test_csv_errors_are_korean(default_data):
    bad = default_data.courses.drop(columns=["exam_type"])
    df, res = parse_table("courses", to_csv_bytes(bad))
    assert df is None and "필수 컬럼이 없습니다" in res.errors[0] and "시험방식" in res.errors[0]
    bad = default_data.rooms.astype(str)
    bad.loc[0, "capacity"] = "많음"
    df, res = parse_table("rooms", to_csv_bytes(bad))
    assert df is None and "2행" in res.errors[0] and "숫자" in res.errors[0]


def test_csv_accepts_korean_headers(default_data):
    kor = default_data.students.rename(columns={"student_id": "학번", "name": "이름", "major": "주전공", "grade": "학년"})
    df, res = parse_table("students", to_csv_bytes(kor))
    assert res.ok and list(df.columns)[:2] == ["student_id", "name"]


def test_priority_rotation():
    assert priority_order("26-1")[0] == "물리학과"
    assert priority_order("26-2")[0] == "수학과"
    assert priority_order("27-1")[0] == "생물학과"
    assert priority_order("29-1")[0] == "물리학과"   # 6학기 주기
    assert priority_order("25-2")[0] == "화학과"
    w = dept_weights("26-2")
    assert w["수학과"] == 6 and w["물리학과"] == 1
