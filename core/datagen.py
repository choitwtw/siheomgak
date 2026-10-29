"""가상 데이터 생성기 (랜덤 시드 고정 → 항상 같은 데이터 재현).

생성 순서
1. 과목 카탈로그(이과대학 6개 학과, 40개) 와 교수 배정
2. 정규 수업 시간 패턴 배정 — 같은 학과·같은 학년 과목, 1학년 과목끼리, 같은 교수 과목끼리 겹치지 않게
3. 학생 생성 + 수강신청 — 학생 본인의 수업끼리 시간이 겹치지 않게 (실제 수강신청처럼)
4. 수강인원 집계 → 정규 강의실 배정 (수용인원·사용학과·시간 겹침 고려)
5. 시험 방식/시험 시간, 교수 불가·선호 시간
"""
from __future__ import annotations

import random
from dataclasses import dataclass

import pandas as pd

from .config import (
    DEFAULT_N_PROFESSORS,
    DEFAULT_N_STUDENTS,
    DEFAULT_SEED,
    DEPARTMENTS,
    EXAM_IN_CLASS,
    EXAM_NONE,
    EXAM_SEPARATE,
    GENERAL_DEPT,
    MAX_COURSE_ENROLLMENT,
)
from .dataset import Dataset, exam_seats
from .timeutil import min_to_hm

# (코드, 과목명, 학과, 대상학년)
CATALOG: list[tuple[str, str, str, list[int]]] = [
    ("PHY101", "일반물리학1", "물리학과", [1]),
    ("PHY201", "역학1", "물리학과", [2]),
    ("PHY202", "물리수학", "물리학과", [2]),
    ("PHY231", "전자기학1", "물리학과", [2, 3]),
    ("PHY301", "양자역학1", "물리학과", [3]),
    ("PHY341", "열및통계물리", "물리학과", [3, 4]),
    ("PHY401", "고체물리", "물리학과", [4]),
    ("MTH101", "미적분학1", "수학과", [1]),
    ("MTH121", "선형대수학", "수학과", [1, 2]),
    ("MTH201", "해석학1", "수학과", [2]),
    ("MTH231", "미분방정식", "수학과", [2, 3]),
    ("MTH301", "현대대수학1", "수학과", [3]),
    ("MTH302", "수치해석", "수학과", [3]),
    ("MTH341", "위상수학", "수학과", [3, 4]),
    ("BIO101", "일반생물학1", "생물학과", [1]),
    ("BIO201", "세포생물학", "생물학과", [2]),
    ("BIO202", "유전학", "생물학과", [2]),
    ("BIO231", "생태학", "생물학과", [2, 3]),
    ("BIO301", "분자생물학", "생물학과", [3]),
    ("BIO341", "생화학", "생물학과", [3, 4]),
    ("BIO401", "미생물학", "생물학과", [4]),
    ("GEO101", "지리학개론", "지리학과", [1]),
    ("GEO201", "지형학", "지리학과", [2]),
    ("GEO231", "기후학", "지리학과", [2, 3]),
    ("GEO301", "도시지리학", "지리학과", [3]),
    ("GEO341", "GIS와공간분석", "지리학과", [3, 4]),
    ("GEO401", "지역개발론", "지리학과", [4]),
    ("DSP101", "디스플레이공학개론", "정보디스플레이학과", [1]),
    ("DSP201", "반도체물리", "정보디스플레이학과", [2]),
    ("DSP202", "회로이론", "정보디스플레이학과", [2]),
    ("DSP231", "광전자공학", "정보디스플레이학과", [2, 3]),
    ("DSP301", "디스플레이소자", "정보디스플레이학과", [3]),
    ("DSP341", "박막공학", "정보디스플레이학과", [3, 4]),
    ("DSP401", "디스플레이회로설계", "정보디스플레이학과", [4]),
    ("CHM101", "일반화학1", "화학과", [1]),
    ("CHM201", "유기화학1", "화학과", [2]),
    ("CHM231", "분석화학", "화학과", [2, 3]),
    ("CHM301", "물리화학1", "화학과", [3]),
    ("CHM302", "무기화학", "화학과", [3]),
    ("CHM401", "고분자화학", "화학과", [4]),
]
# 교양 과목 (다른 단과대학 개설) — 학생 시간표에는 있지만 시험 일정은 이 시스템이 정하지 않는다
GENERAL_CATALOG = [
    ("GEN101", "대학영어"), ("GEN102", "글쓰기"), ("GEN103", "세계와 시민"), ("GEN104", "인간의 가치 탐색"),
    ("GEN105", "빅뱅에서 문명까지"), ("GEN106", "코딩과 컴퓨팅 사고"), ("GEN107", "철학과 비판적 사고"),
    ("GEN108", "생활 속의 통계"), ("GEN109", "현대 사회와 경제"), ("GEN110", "체육과 건강"),
]
# 이과대학 1학년 공통 기초 과목 (모든 학과 1학년이 듣는다 → 대형 강의)
BASIC_COURSES = {"PHY101", "MTH101", "BIO101", "CHM101"}
DEPT_PREFIX = {"물리학과": "PHY", "수학과": "MTH", "생물학과": "BIO", "지리학과": "GEO",
               "정보디스플레이학과": "DSP", "화학과": "CHM"}

PERIODS = [(540, 615), (630, 705), (720, 795), (810, 885), (900, 975), (990, 1065)]  # 1~6교시 (75분)
TIME_PATTERNS: list[tuple[list[int], int, int]] = (
    [([0, 2], s, e) for s, e in PERIODS]          # 월·수
    + [([1, 3], s, e) for s, e in PERIODS]        # 화·목
    + [([4], 540, 705), ([4], 810, 975)]           # 금 3시간 연강
)

SURNAMES = list("김이박최정강조윤장임한오서신권황안송류전홍고문양손배백허유남심노하곽성차주우구민진나지엄채원천방공현함변염여추도소석선설마길연위표명기반왕금옥육인맹제모탁국어은편용")
GIVEN = ["민준", "서연", "도윤", "서윤", "시우", "지우", "하준", "하은", "주원", "지호", "지유", "예준", "수아",
         "준우", "채원", "현우", "지민", "건우", "다은", "우진", "소율", "선우", "예린", "연우", "윤서", "유준",
         "수빈", "정우", "지원", "승현", "민서", "태윤", "가은", "은우", "시아", "재윤", "하린", "민재", "서진",
         "유나", "동현", "예서", "지훈", "나연", "성민", "혜원", "승우", "보은", "태민", "다인", "현서", "규리"]


@dataclass
class GenConfig:
    seed: int = DEFAULT_SEED
    n_students: int = DEFAULT_N_STUDENTS
    n_courses: int = 40
    n_professors: int = DEFAULT_N_PROFESSORS
    n_rooms: int = 42
    double_major_rate: float = 0.15
    minor_rate: float = 0.10
    multi_grade_rate: float = 0.30
    n_general: int = 8          # 교양 과목 수 (0이면 교양 없음)
    exam_type_ratio: tuple[float, float, float] = (0.35, 0.55, 0.10)  # 수업시간 / 별도 / 없음


def _blocks(pat) -> list[tuple[int, int, int]]:
    days, s, e = pat
    return [(d, s, e) for d in days]


def _overlap(b1, b2) -> bool:
    return any(d1 == d2 and s1 < e2 and s2 < e1 for d1, s1, e1 in b1 for d2, s2, e2 in b2)


def _unique_name(rng: random.Random, used: set[str]) -> str:
    for _ in range(200):
        n = rng.choice(SURNAMES) + rng.choice(GIVEN)
        if n not in used:
            used.add(n)
            return n
    n = rng.choice(SURNAMES) + rng.choice(GIVEN) + str(len(used))
    used.add(n)
    return n


def _build_catalog(cfg: GenConfig, rng: random.Random) -> list[dict]:
    cat = [dict(code=c, name=n, dept=d, grades=list(g)) for c, n, d, g in CATALOG]
    if cfg.n_courses < len(cat):
        # 학과별로 고르게 남긴다 (기초 과목 우선)
        by_dept = {d: [c for c in cat if c["dept"] == d] for d in DEPARTMENTS}
        keep: list[dict] = []
        i = 0
        while len(keep) < cfg.n_courses:
            d = DEPARTMENTS[i % len(DEPARTMENTS)]
            if by_dept[d]:
                keep.append(by_dept[d].pop(0))
            i += 1
        cat = keep
    k = 1
    while len(cat) < cfg.n_courses:  # 카탈로그보다 많이 요청하면 특론 과목 추가
        d = DEPARTMENTS[(k - 1) % len(DEPARTMENTS)]
        cat.append(dict(code=f"{DEPT_PREFIX[d]}5{k:02d}", name=f"{d[:-1]} 특론{k}", dept=d, grades=[3, 4]))
        k += 1
    # 여러 학년 과목 비율 조정 (기본 카탈로그는 12/40 = 30%)
    target_multi = round(cfg.multi_grade_rate * len(cat))
    multi = [c for c in cat if len(c["grades"]) > 1]
    single = [c for c in cat if len(c["grades"]) == 1 and c["code"] not in BASIC_COURSES]
    rng.shuffle(single)
    while len(multi) < target_multi and single:
        c = single.pop()
        g = c["grades"][0]
        c["grades"] = sorted({g, g + 1 if g < 4 else g - 1})
        multi.append(c)
    return cat


def generate(cfg: GenConfig | None = None) -> Dataset:
    cfg = cfg or GenConfig()
    rng = random.Random(cfg.seed)
    courses = _build_catalog(cfg, rng)
    for c in courses:
        c["basic"] = c["code"] in BASIC_COURSES

    # ---- 1. 교수 배정 ----
    n_prof = max(len(DEPARTMENTS), min(cfg.n_professors, len(courses)))
    dept_courses = {d: [c for c in courses if c["dept"] == d] for d in DEPARTMENTS}
    # 학과별 교수 수: 과목 수에 비례 (최소 1명, 과목 수 이하)
    prof_count = {d: 1 for d in DEPARTMENTS if dept_courses[d]}
    while sum(prof_count.values()) < n_prof:
        cand = [d for d in prof_count if prof_count[d] < len(dept_courses[d])]
        if not cand:
            break
        d = max(cand, key=lambda x: (len(dept_courses[x]) / prof_count[x], -DEPARTMENTS.index(x)))
        prof_count[d] += 1
    used_names: set[str] = set()
    professors = []
    pid = 1
    for d in DEPARTMENTS:
        if d not in prof_count:
            continue
        ids = []
        for _ in range(prof_count[d]):
            p = dict(pid=f"P{pid:02d}", name=_unique_name(rng, used_names), dept=d, courses=[])
            professors.append(p)
            ids.append(p)
            pid += 1
        cs = dept_courses[d][:]
        rng.shuffle(cs)
        for i, c in enumerate(cs):  # 모든 교수 최소 1과목
            p = ids[i % len(ids)]
            c["prof"] = p["pid"]
            p["courses"].append(c["code"])

    # ---- 2. 정규 수업 시간 패턴 ----
    def conflict(c1, c2) -> bool:
        if c1["prof"] == c2["prof"]:
            return True
        if 1 in c1["grades"] and 1 in c2["grades"]:
            return True
        return c1["dept"] == c2["dept"] and bool(set(c1["grades"]) & set(c2["grades"]))

    order = sorted(courses, key=lambda c: (-c["basic"], -len(c["grades"]), rng.random()))
    for c in order:
        pats = TIME_PATTERNS[:]
        rng.shuffle(pats)
        # 1학년 기초 과목은 2일 패턴(월수/화목) 우선
        pats.sort(key=lambda p: (len(p[0]) == 1) if c["basic"] else 0)
        chosen = None
        for p in pats:
            b = _blocks(p)
            if all(not _overlap(b, o["blocks"]) for o in courses if "blocks" in o and conflict(c, o)):
                chosen = p
                break
        if chosen is None:
            chosen = pats[0]
        c["pattern"] = chosen
        c["blocks"] = _blocks(chosen)

    # ---- 2-1. 교양 과목 (강사·수업 시간) ----
    gens = []
    for i, (code, name) in enumerate(GENERAL_CATALOG[:max(0, cfg.n_general)]):
        pat = rng.choice(TIME_PATTERNS)
        gens.append(dict(code=code, name=name, dept=GENERAL_DEPT, grades=[1, 2, 3, 4], prof=f"G{i + 1:02d}",
                         basic=False, pattern=pat, blocks=_blocks(pat), exam_type=EXAM_NONE, exam_minutes=60))

    # ---- 3. 학생 + 수강신청 ----
    code_map = {c["code"]: c for c in courses + gens}
    count = {c["code"]: 0 for c in courses + gens}
    students, enrollments = [], []
    seq = {d: 0 for d in DEPARTMENTS}
    for i in range(cfg.n_students):
        major = DEPARTMENTS[i % len(DEPARTMENTS)] if i < len(DEPARTMENTS) else rng.choice(DEPARTMENTS)
        grade = rng.choice([1, 2, 3, 4])
        seq[major] += 1
        sid = f"{2026 - grade + 1}{DEPARTMENTS.index(major) + 1:02d}{seq[major]:04d}"
        # 복수·부전공은 2학년 이상만. 전체 학생 대비 비율이 설정값이 되도록 보정 (2~4학년 = 75%)
        r = rng.random() * 0.75
        others = [d for d in DEPARTMENTS if d != major]
        double = rng.choice(others) if grade >= 2 and r < cfg.double_major_rate else ""
        minor = rng.choice(others) if grade >= 2 and cfg.double_major_rate <= r < cfg.double_major_rate + cfg.minor_rate else ""
        students.append(dict(student_id=sid, name=_unique_name(rng, set()), major=major, grade=grade,
                             double_major=double, minor=minor))

        k_total = rng.choice([5, 6, 7])
        n_gen = 0 if not gens else (2 if grade == 1 else rng.choice([0, 1, 1]))
        k = k_total - n_gen   # 이과대학 과목 수
        chosen: list[str] = []
        blocks: list = []

        def try_add(code: str) -> bool:
            c = code_map[code]
            if code in chosen or count[code] >= MAX_COURSE_ENROLLMENT or _overlap(c["blocks"], blocks):
                return False
            chosen.append(code)
            blocks.extend(c["blocks"])
            count[code] += 1
            return True

        # (1) 필수: 1학년은 기초 과목, 그 외는 주전공 해당 학년 과목
        must = [c["code"] for c in courses if c["dept"] == major and grade in c["grades"]]
        if grade == 1:
            must = [c for c in sorted(BASIC_COURSES) if c in code_map] + must   # 정렬: 실행마다 같은 순서
        rng.shuffle(must)
        for code in must:
            if len(chosen) >= k - (1 if (double or minor) else 0):
                break
            try_add(code)
        # (2) 복수전공·부전공 학과 과목 1~2개
        second = double or minor
        if second:
            pool = [c["code"] for c in courses if c["dept"] == second and grade in c["grades"]]
            pool += [c["code"] for c in courses if c["dept"] == second and c["code"] not in pool and min(c["grades"]) <= grade]
            want = rng.choice([1, 2])
            added = 0
            for code in pool:
                if added >= want:
                    break
                if try_add(code):
                    added += 1
        # (3) 나머지: 주전공 다른 학년 과목(재수강·선택) 가중치 3, 타 학과 같은 학년 과목 가중치 1
        pool = []
        for c in courses:
            if c["code"] in chosen:
                continue
            if c["dept"] == major and any(abs(g - grade) <= 1 for g in c["grades"]):
                pool.append((c["code"], 3.0))
            elif grade in c["grades"] and not c["basic"]:
                pool.append((c["code"], 1.0))
            elif c["basic"] and grade == 2:
                pool.append((c["code"], 0.4))  # 기초 과목 재수강
        while len(chosen) < k and pool:
            tot = sum(w for _, w in pool)
            x = rng.random() * tot
            for j, (code, w) in enumerate(pool):
                x -= w
                if x <= 0:
                    break
            code, _ = pool.pop(j)
            try_add(code)
        # (4) 교양: 시간이 겹치지 않는 교양 과목
        gen_pool = [g["code"] for g in gens]
        rng.shuffle(gen_pool)
        added = 0
        for code in gen_pool:
            if added >= n_gen:
                break
            if try_add(code):
                added += 1
        for code in chosen:
            enrollments.append(dict(student_id=sid, course_code=code))

    # ---- 4. 강의실 생성 + 정규 강의실 배정 ----
    rooms = _make_rooms(cfg, rng)
    room_blocks: dict[str, list] = {r["room_id"]: [] for r in rooms}
    for c in sorted(courses, key=lambda c: -count[c["code"]]):
        need = max(count[c["code"]], 1)
        cands = [r for r in rooms if r["capacity"] >= need
                 and (r["departments"] == "전체" or c["dept"] in r["departments"].split(","))
                 and not _overlap(c["blocks"], room_blocks[r["room_id"]])]
        if not cands:
            raise RuntimeError(f"{c['name']} 정규 강의실을 배정할 수 없습니다 (강의실 수를 늘려 주세요)")
        cands.sort(key=lambda r: (r["capacity"], r["departments"] == "전체", rng.random()))
        room = cands[0]
        c["room"] = room["room_id"]
        room_blocks[room["room_id"]].extend(c["blocks"])

    # 교양관 강의실 (교양 전용 — 이과대학 시험에는 쓰지 않음)
    for j, g in enumerate(sorted(gens, key=lambda g: -count[g["code"]])):
        cap = next(x for x in (40, 60, 80, 120, 150, 200, 300) if x >= count[g["code"]])
        no = f"{(j // 6) + 1}{(j % 6) + 1:02d}"
        rooms.append(dict(room_id=f"교양관-{no}", building="교양관", room_no=no, capacity=cap,
                          departments=GENERAL_DEPT, exam_capacity=exam_seats(cap)))
        g["room"] = f"교양관-{no}"

    # ---- 5. 시험 방식 · 시험 시간 ----
    n = len(courses)
    n_a = round(cfg.exam_type_ratio[0] * n)
    n_c = round(cfg.exam_type_ratio[2] * n)
    types = [EXAM_IN_CLASS] * n_a + [EXAM_NONE] * n_c + [EXAM_SEPARATE] * (n - n_a - n_c)
    rng.shuffle(types)
    for c, t in zip(courses, types):
        c["exam_type"] = t
        days, s, e = c["pattern"]
        if t == EXAM_IN_CLASS:
            options = [m for m in (60, 75, 90, 120) if m <= e - s]
            c["exam_minutes"] = rng.choice(options)
        else:
            c["exam_minutes"] = rng.choices([60, 75, 90, 120], weights=[2, 3, 3, 2])[0]

    # ---- 6. 교수 불가·선호 시간 ----
    for p in professors:
        fixed_blocks = []
        for code in p["courses"]:
            c = code_map[code]
            if c["exam_type"] in (EXAM_IN_CLASS, EXAM_NONE):
                fixed_blocks += c["blocks"]
        unav = []
        if rng.random() < 0.45:
            for _ in range(rng.choice([1, 1, 2])):
                for _try in range(10):
                    d = rng.randrange(5)
                    s, e = rng.choice([(540, 720), (780, 1080), (840, 1080), (540, 780)])
                    if not _overlap([(d, s, e)], fixed_blocks) and all(u[0] != d for u in unav):
                        unav.append((d, s, e))
                        break
        p["unavailable"] = "; ".join(f"{'월화수목금'[d]} {min_to_hm(s)}-{min_to_hm(e)}" for d, s, e in sorted(unav))
        pref = ""
        if rng.random() < 0.5:
            pref = rng.choice([
                "매일 09:00-12:00",
                "매일 13:00-18:00",
                "화 09:00-18:00; 목 09:00-18:00",
                "월 09:00-18:00; 수 09:00-18:00",
                "매일 10:00-15:00",
            ])
        p["preferred"] = pref

    # ---- DataFrame 변환 ----
    df_students = pd.DataFrame(students)
    df_courses = pd.DataFrame([
        dict(course_code=c["code"], course_name=c["name"], department=c["dept"],
             target_grades=",".join(map(str, c["grades"])), professor_id=c["prof"],
             class_days=",".join("월화수목금"[d] for d in c["pattern"][0]),
             class_start=min_to_hm(c["pattern"][1]), class_end=min_to_hm(c["pattern"][2]),
             class_room=c["room"], enrollment=count[c["code"]],
             exam_type=c["exam_type"], exam_minutes=c["exam_minutes"])
        for c in courses + gens
    ])
    gen_profs = [dict(pid=g["prof"], name=_unique_name(rng, used_names) + " 강사", dept=GENERAL_DEPT,
                      courses=[g["code"]], unavailable="", preferred="") for g in gens]
    df_prof = pd.DataFrame([
        dict(professor_id=p["pid"], name=p["name"], department=p["dept"], courses=",".join(p["courses"]),
             unavailable=p["unavailable"], preferred=p["preferred"])
        for p in professors + gen_profs
    ])
    df_rooms = pd.DataFrame(rooms)
    df_enr = pd.DataFrame(enrollments)
    # 수강생이 0명인 과목은 제거 (작은 규모 설정 시)
    empty = [c for c, v in count.items() if v == 0]
    if empty:
        df_courses = df_courses[~df_courses["course_code"].isin(empty)].reset_index(drop=True)
        df_prof["courses"] = df_prof["courses"].map(lambda s: ",".join(x for x in s.split(",") if x not in empty))
    return Dataset(df_students, df_courses, df_prof, df_rooms, df_enr,
                   meta={"source": "가상 데이터", "seed": cfg.seed})


def _make_rooms(cfg: GenConfig, rng: random.Random) -> list[dict]:
    n = cfg.n_rooms
    # 수용인원 분포 (기본 42실: 30석 8, 50석 12, 80석 9, 120석 6, 200석 5, 300석 대강의실 2)
    base = [30] * 8 + [50] * 12 + [80] * 9 + [120] * 6 + [200] * 5 + [300] * 2
    caps = [base[int(i * len(base) / n)] for i in range(n)]
    big = [c for c in caps if c >= 120]
    small = [c for c in caps if c < 120]
    rng.shuffle(small)
    rooms = []
    groups = [
        ["물리학과", "수학과", "화학과"],
        ["물리학과", "정보디스플레이학과"],
        ["수학과", "지리학과"],
        ["생물학과", "화학과"],
        ["생물학과", "지리학과", "정보디스플레이학과"],
        ["화학과", "정보디스플레이학과"],
        ["물리학과", "생물학과"],
        ["수학과", "정보디스플레이학과", "지리학과"],
    ]
    counter = {"공동강의동": 0, "이과대학": 0, "과학관": 0}

    def add(bld: str, cap: int, deps: str):
        j = counter[bld]
        counter[bld] += 1
        no = f"{(j // 6) + 1}{(j % 6) + 1:02d}"
        rooms.append(dict(room_id=f"{bld}-{no}", building=bld, room_no=no, capacity=cap, departments=deps,
                          exam_capacity=exam_seats(cap)))

    # 대형 강의실(120석 이상)은 공동강의동(전체 공용)
    for c in sorted(big, reverse=True):
        add("공동강의동", c, "전체")
    half = len(small) // 2
    n_shared = max(1, len(small) // 6)
    for i, c in enumerate(small):
        if i < half:
            add("이과대학", c, ",".join(groups[i % len(groups)]))
        elif i < half + n_shared:
            add("공동강의동", c, "전체")
        else:
            add("과학관", c, ",".join(groups[(i + 3) % len(groups)]))
    rooms.sort(key=lambda r: (r["building"], r["room_no"]))
    return rooms
