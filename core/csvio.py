"""CSV 업로드·다운로드와 컬럼/값 검증 (오류 메시지는 한국어)."""
from __future__ import annotations

import io
import zipfile
from dataclasses import dataclass, field

import pandas as pd

from .config import DEPARTMENTS, GENERAL_DEPT
from .dataset import EXAM_TYPE_ALIASES, SCHEMAS, TABLE_LABELS, Dataset, columns
from .timeutil import hm_to_min, parse_days, parse_windows


@dataclass
class CheckResult:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    def extend(self, other: "CheckResult"):
        self.errors += other.errors
        self.warnings += other.warnings


# ---------------------------------------------------------------------------
# 다운로드
# ---------------------------------------------------------------------------
def to_csv_bytes(df: pd.DataFrame) -> bytes:
    """엑셀에서 한글이 깨지지 않도록 UTF-8 BOM 포함"""
    return df.to_csv(index=False).encode("utf-8-sig")


def dataset_zip_bytes(ds: Dataset, extra: dict[str, pd.DataFrame] | None = None) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, df in ds.tables().items():
            z.writestr(f"{name}.csv", to_csv_bytes(df))
        for name, df in (extra or {}).items():
            z.writestr(f"{name}.csv", to_csv_bytes(df))
    return buf.getvalue()


def write_dataset(ds: Dataset, folder: str):
    import os
    os.makedirs(folder, exist_ok=True)
    for name, df in ds.tables().items():
        with open(os.path.join(folder, f"{name}.csv"), "wb") as f:
            f.write(to_csv_bytes(df))


# ---------------------------------------------------------------------------
# 업로드 (단일 테이블)
# ---------------------------------------------------------------------------
def _read_csv(raw: bytes) -> pd.DataFrame:
    last = None
    for enc in ("utf-8-sig", "cp949", "euc-kr"):
        try:
            return pd.read_csv(io.BytesIO(raw), dtype=str, keep_default_na=False, encoding=enc)
        except UnicodeDecodeError as e:
            last = e
    raise ValueError(f"파일 인코딩을 읽을 수 없습니다 (UTF-8 또는 CP949로 저장해 주세요): {last}")


def parse_table(table: str, raw: bytes) -> tuple[pd.DataFrame | None, CheckResult]:
    """CSV 바이트 → 정규화된 DataFrame. 실패하면 (None, 오류목록)."""
    res = CheckResult()
    label = TABLE_LABELS[table]
    try:
        df = _read_csv(raw)
    except Exception as e:  # noqa: BLE001
        res.errors.append(f"[{label}] CSV 파일을 읽지 못했습니다: {e}")
        return None, res

    schema = SCHEMAS[table]
    alias = {}
    for col, kor, *_ in schema:
        alias[col] = col
        alias[kor] = col
        alias[col.lower()] = col
    df.columns = [str(c).strip() for c in df.columns]
    rename = {c: alias[c] for c in df.columns if c in alias}
    unknown = [c for c in df.columns if c not in alias]
    df = df.rename(columns=rename)
    if unknown:
        res.warnings.append(f"[{label}] 알 수 없는 컬럼은 무시합니다: {', '.join(unknown)}")

    missing = [f"{kor}({col})" for col, kor, _t, req, *_ in schema if req and col not in df.columns]
    if missing:
        expected = ", ".join(f"{col}" for col, *_ in schema)
        res.errors.append(f"[{label}] 필수 컬럼이 없습니다: {', '.join(missing)}. 필요한 컬럼: {expected}")
        return None, res
    for col, _k, _t, req, *_ in schema:
        if col not in df.columns:
            df[col] = ""
    df = df[columns(table)].copy()
    for c in df.columns:
        df[c] = df[c].astype(str).str.strip()
    if df.empty:
        res.errors.append(f"[{label}] 데이터 행이 없습니다.")
        return None, res

    def row_err(i: int, msg: str):
        if len(res.errors) < 30:
            res.errors.append(f"[{label}] {i + 2}행: {msg}")

    # 필수값 비어 있음
    for col, kor, _t, req, *_ in schema:
        if req:
            for i in df.index[df[col] == ""]:
                row_err(i, f"'{kor}({col})' 값이 비어 있습니다.")
    # 정수 컬럼
    for col, kor, typ, req, *_ in schema:
        if typ != "int":
            continue
        for i, v in df[col].items():
            if v == "" and not req:
                continue
            try:
                int(float(v))
            except ValueError:
                row_err(i, f"'{kor}({col})' 값은 숫자여야 합니다: '{v}'")

    if res.errors:
        return None, res

    # 테이블별 세부 검증
    if table == "students":
        _check_unique(df, "student_id", "학번", res, label)
        df["grade"] = df["grade"].map(lambda v: int(float(v)))
        for i, r in df.iterrows():
            if r["major"] not in DEPARTMENTS:
                row_err(i, f"주전공 '{r['major']}'은(는) 이과대학 학과가 아닙니다. 가능: {', '.join(DEPARTMENTS)}")
            if not 1 <= r["grade"] <= 4:
                row_err(i, f"학년은 1~4여야 합니다: {r['grade']}")
            for col, kor in (("double_major", "복수전공"), ("minor", "부전공")):
                if r[col] and r[col] not in DEPARTMENTS:
                    res.warnings.append(f"[{label}] {i + 2}행: {kor} '{r[col]}'은(는) 이과대학 학과가 아니라서 무시합니다.")
    elif table == "courses":
        _check_unique(df, "course_code", "과목코드", res, label)
        for i, r in df.iterrows():
            et = EXAM_TYPE_ALIASES.get(r["exam_type"].strip().lower(), EXAM_TYPE_ALIASES.get(r["exam_type"].strip()))
            if et is None:
                row_err(i, f"시험방식 '{r['exam_type']}'을(를) 알 수 없습니다. 수업시간 / 별도 / 없음 중 하나로 적어 주세요.")
            else:
                df.at[i, "exam_type"] = et
            if r["department"] not in DEPARTMENTS + [GENERAL_DEPT]:
                row_err(i, f"개설학과 '{r['department']}'은(는) 이과대학 학과가 아닙니다. (다른 단과대 과목은 '{GENERAL_DEPT}')")
            try:
                parse_days(r["class_days"])
                s, e = hm_to_min(r["class_start"]), hm_to_min(r["class_end"])
                if e <= s:
                    row_err(i, "수업종료가 수업시작보다 늦어야 합니다.")
            except ValueError as ex:
                row_err(i, str(ex))
            m = int(float(r["exam_minutes"]))
            if m < 30 or m > 240 or m % 15:
                row_err(i, f"시험시간은 30~240분, 15분 단위여야 합니다: {m}")
            grades = [g for g in r["target_grades"].replace(" ", "").split(",") if g]
            if not grades or any(g not in "1234" for g in grades):
                row_err(i, f"대상학년은 1~4를 쉼표로 구분해 적어 주세요: '{r['target_grades']}'")
        if not res.errors:
            df["exam_minutes"] = df["exam_minutes"].map(lambda v: int(float(v)))
            df["enrollment"] = df["enrollment"].map(lambda v: int(float(v)) if v != "" else 0)
    elif table == "professors":
        _check_unique(df, "professor_id", "교수ID", res, label)
        for i, r in df.iterrows():
            for col, kor in (("unavailable", "불가시간"), ("preferred", "선호시간")):
                try:
                    parse_windows(r[col])
                except ValueError as ex:
                    row_err(i, f"{kor}: {ex}")
    elif table == "rooms":
        _check_unique(df, "room_id", "강의실ID", res, label)
        df["capacity"] = df["capacity"].map(lambda v: int(float(v)))
        for i, r in df.iterrows():
            if r["capacity"] <= 0:
                row_err(i, "수용인원은 1 이상이어야 합니다.")
            if r["exam_capacity"] not in ("", "nan"):
                ec = int(float(r["exam_capacity"]))
                if not 0 < ec <= r["capacity"]:
                    row_err(i, f"시험좌석({ec})은 1 이상, 수용인원({r['capacity']}) 이하여야 합니다.")
            deps = [d.strip() for d in r["departments"].split(",") if d.strip()]
            bad = [d for d in deps if d not in DEPARTMENTS and d not in ("전체", "공용", GENERAL_DEPT)]
            if bad:
                row_err(i, f"사용학과에 알 수 없는 학과가 있습니다: {', '.join(bad)} ('전체' 또는 학과명)")
    elif table == "enrollments":
        dup = df.duplicated(keep="first")
        if dup.any():
            res.warnings.append(f"[{label}] 중복된 수강 내역 {int(dup.sum())}건을 제거했습니다.")
            df = df[~dup].reset_index(drop=True)

    if res.errors:
        return None, res
    return df, res


def _check_unique(df, col, kor, res: CheckResult, label: str):
    dup = df[col][df[col].duplicated()].unique().tolist()
    if dup:
        res.errors.append(f"[{label}] {kor}가 중복됩니다: {', '.join(map(str, dup[:10]))}")


# ---------------------------------------------------------------------------
# 테이블 간 교차 검증 → Dataset 조립
# ---------------------------------------------------------------------------
def assemble(tables: dict[str, pd.DataFrame], source: str = "CSV 업로드") -> tuple[Dataset | None, CheckResult]:
    res = CheckResult()
    missing = [TABLE_LABELS[t] for t in SCHEMAS if t not in tables]
    if missing:
        res.errors.append(f"다음 테이블이 없습니다: {', '.join(missing)}")
        return None, res
    st, co, pr, ro, en = (tables[t].copy() for t in ("students", "courses", "professors", "rooms", "enrollments"))

    sids, codes, pids, rids = set(st["student_id"]), set(co["course_code"]), set(pr["professor_id"]), set(ro["room_id"])
    bad_p = co[~co["professor_id"].isin(pids)]
    for r in bad_p.itertuples():
        res.errors.append(f"[과목] {r.course_code}의 담당교수 '{r.professor_id}'가 교수 표에 없습니다.")
    bad_r = co[~co["class_room"].isin(rids)]
    for r in bad_r.itertuples():
        res.errors.append(f"[과목] {r.course_code}의 정규강의실 '{r.class_room}'이(가) 강의실 표에 없습니다.")
    bad_es = ~en["student_id"].isin(sids)
    bad_ec = ~en["course_code"].isin(codes)
    if bad_es.any():
        res.warnings.append(f"[수강 내역] 학생 표에 없는 학번 {int(bad_es.sum())}건을 제외했습니다 (예: {en.loc[bad_es, 'student_id'].iloc[0]}).")
    if bad_ec.any():
        res.warnings.append(f"[수강 내역] 과목 표에 없는 과목코드 {int(bad_ec.sum())}건을 제외했습니다 (예: {en.loc[bad_ec, 'course_code'].iloc[0]}).")
    en = en[~bad_es & ~bad_ec].reset_index(drop=True)
    if res.errors:
        return None, res

    # 수강인원은 수강 내역 기준으로 다시 계산
    actual = en.groupby("course_code").size()
    changed = []
    for i, r in co.iterrows():
        a = int(actual.get(r["course_code"], 0))
        if int(r["enrollment"]) not in (0, a):
            changed.append(f"{r['course_code']}({r['enrollment']}→{a})")
        co.at[i, "enrollment"] = a
    if changed:
        res.warnings.append(f"[과목] 수강인원을 수강 내역 기준으로 다시 계산했습니다: {', '.join(changed[:8])}"
                            + (" 외" if len(changed) > 8 else ""))
    empty = co[co["enrollment"] == 0]["course_code"].tolist()
    if empty:
        res.warnings.append(f"[과목] 수강생이 없는 과목은 배정에서 제외됩니다: {', '.join(empty)}")
        co = co[co["enrollment"] > 0].reset_index(drop=True)

    # 교수 담당과목 컬럼은 과목 표 기준으로 재계산
    pc = co.groupby("professor_id")["course_code"].apply(lambda s: ",".join(s))
    pr["courses"] = pr["professor_id"].map(lambda p: pc.get(p, ""))

    ds = Dataset(st, co, pr, ro, en, meta={"source": source})
    # 정합성 경고 (배정이 불가능해질 수 있는 상황)
    res.extend(sanity_warnings(ds))
    return ds, res


def sanity_warnings(ds: Dataset) -> CheckResult:
    res = CheckResult()
    rooms = ds.room_map
    for c in ds.course_map.values():
        r = rooms.get(c.room)
        if r and r.capacity < c.enrollment:
            res.warnings.append(f"[과목] {c.code} {c.name}: 정규강의실 수용인원({r.capacity})이 수강인원({c.enrollment})보다 작습니다.")
        if c.exam_type == "별도" and not any(rm.exam_capacity >= c.enrollment and rm.allows(c.dept) for rm in rooms.values()):
            res.warnings.append(f"[과목] {c.code} {c.name}: 수강인원 {c.enrollment}명을 시험 좌석 기준으로 수용할 강의실이 없습니다.")
    # 학생 정규 수업 겹침 (수강신청 데이터 오류)
    cm = ds.course_map
    bad = 0
    for sid, codes in ds.courses_of.items():
        blocks = [(b, code) for code in codes for b in cm[code].class_blocks()]
        for i in range(len(blocks)):
            for j in range(i + 1, len(blocks)):
                (d1, s1, e1), c1 = blocks[i]
                (d2, s2, e2), c2 = blocks[j]
                if c1 != c2 and d1 == d2 and s1 < e2 and s2 < e1:
                    bad += 1
    if bad:
        res.warnings.append(f"[수강 내역] 학생 정규 수업 시간이 서로 겹치는 경우가 {bad}건 있습니다. "
                            "수업시간 시험/시험 없음 과목끼리 겹치면 배정이 불가능할 수 있습니다.")
    return res


def read_zip(raw: bytes) -> tuple[dict[str, pd.DataFrame], CheckResult]:
    res = CheckResult()
    out = {}
    try:
        z = zipfile.ZipFile(io.BytesIO(raw))
    except zipfile.BadZipFile:
        res.errors.append("ZIP 파일을 열 수 없습니다.")
        return out, res
    names = {n.split("/")[-1].lower(): n for n in z.namelist() if n.lower().endswith(".csv")}
    for t in SCHEMAS:
        if f"{t}.csv" in names:
            df, r = parse_table(t, z.read(names[f"{t}.csv"]))
            res.extend(r)
            if df is not None:
                out[t] = df
    if not out and not res.errors:
        res.errors.append("ZIP 안에서 students.csv, courses.csv, professors.csv, rooms.csv, enrollments.csv 를 찾지 못했습니다.")
    return out, res


def template_csv(table: str) -> bytes:
    return to_csv_bytes(pd.DataFrame(columns=columns(table)))
