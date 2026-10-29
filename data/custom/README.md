# 사용자 데이터 (기본 데이터로 쓰기)

이 폴더에 아래 이름의 CSV를 넣으면, 앱을 열 때 가상 데이터 대신 이 데이터를 **기본 데이터**로 씁니다.

- `students.csv`, `enrollments.csv`, `courses.csv`, `professors.csv`, `rooms.csv` 중 **있는 것만** 바꿉니다.
  없는 표는 가상 데이터(시드 42)를 그대로 씁니다.
  - 예: KHU CHAT으로 학생 데이터만 만들었다면 `students.csv` + `enrollments.csv` 두 개만 넣으면 됩니다.
    이때 `enrollments.csv`의 과목코드는 가상 데이터 과목코드(`data/sample/courses.csv`)를 써야 합니다.
- 컬럼 형식은 `data/templates/README.md` 참고. 업로드 화면과 같은 검사를 거칩니다.
- 오류가 있으면 앱은 멈추지 않고 가상 데이터로 시작하며, 관리자 대시보드 → 데이터 준비 탭에 무엇이 틀렸는지 한국어로 보여 줍니다.
