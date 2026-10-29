from core.csvio import assemble, dataset_zip_bytes, parse_table, read_zip, to_csv_bytes
from core.datagen import GenConfig, generate
from core.priority import dept_weights, priority_order


def test_generator_default_scale(default_data):
    s = default_data.summary()
    sci = default_data.courses[default_data.courses.department != "교양"]
    gen = default_data.courses[default_data.courses.department == "교양"]
    assert s["학생"] == 500 and len(sci) == 40 and len(gen) == 8 and s["강의실"] >= 40
    profs = default_data.professors
    assert (profs.department != "교양").sum() == 25
    assert tuple(sci.exam_type.value_counts()[["수업시간", "별도", "없음"]]) == (14, 22, 4)
    assert set(gen.exam_type) == {"없음"}      # 교양은 정규 수업 시간을 막아 두기만 한다
    per_student = default_data.enrollments.groupby("student_id").size()
    assert per_student.min() >= 5 and per_student.max() <= 7
    multi = sci["target_grades"].str.contains(",").mean()
    assert 0.25 <= multi <= 0.35
    assert set(sci["exam_minutes"]) <= {60, 75, 90, 120}


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


def test_generator_same_across_processes():
    """파이썬 해시 시드가 달라도(=실행할 때마다) 같은 데이터가 나와야 한다"""
    import os
    import subprocess
    import sys
    code = ("from core.datagen import generate; import hashlib; ds = generate(); "
            "print(hashlib.md5(''.join(t.to_csv() for t in ds.tables().values()).encode()).hexdigest())")
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    outs = {subprocess.run([sys.executable, "-c", code], cwd=root, capture_output=True, text=True,
                           env={**os.environ, "PYTHONHASHSEED": str(h)}).stdout for h in (1, 2, 3)}
    assert len(outs) == 1 and len(next(iter(outs))) > 10


def test_rooms_exam_capacity_csv(default_data):
    """시험좌석 컬럼: 비우면 좌석의 2/3, 좌석보다 크면 오류"""
    rooms = default_data.rooms.astype(str)
    rooms.loc[0, "exam_capacity"] = ""
    df, res = parse_table("rooms", to_csv_bytes(rooms))
    assert res.ok
    from core.dataset import Dataset
    ds = Dataset(default_data.students, default_data.courses, default_data.professors, df, default_data.enrollments)
    r0 = ds.room_map[df.loc[0, "room_id"]]
    assert r0.exam_capacity == int(r0.capacity * 2 / 3)
    rooms.loc[1, "exam_capacity"] = str(int(rooms.loc[1, "capacity"]) + 10)
    df, res = parse_table("rooms", to_csv_bytes(rooms))
    assert df is None and "시험좌석" in res.errors[0]


def test_custom_dataset_folder(tmp_path, monkeypatch, default_data):
    """data/custom 에 넣은 CSV 가 기본 데이터가 되고, 오류가 있으면 가상 데이터로 시작한다"""
    from ui import state
    monkeypatch.setattr(state, "CUSTOM_DIR", tmp_path)
    ds, msg = state.load_default_dataset()
    assert msg is None and ds.meta["source"] == "가상 데이터"
    st_ = default_data.students.head(120)
    en = default_data.enrollments[default_data.enrollments.student_id.isin(st_.student_id)]
    (tmp_path / "students.csv").write_bytes(to_csv_bytes(st_))
    (tmp_path / "enrollments.csv").write_bytes(to_csv_bytes(en))
    ds, msg = state.load_default_dataset()
    assert msg[0] == "ok" and len(ds.students) == 120 and "사용자 데이터" in ds.meta["source"]
    bad = st_.astype(str)
    bad.loc[bad.index[0], "grade"] = "다섯"
    (tmp_path / "students.csv").write_bytes(to_csv_bytes(bad))
    ds, msg = state.load_default_dataset()
    assert msg[0] == "error" and "학년" in msg[1][0] and ds.meta["source"] == "가상 데이터"
