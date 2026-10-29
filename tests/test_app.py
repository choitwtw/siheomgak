"""앱 전체 실행 테스트 (Streamlit AppTest)."""
import os

from streamlit.testing.v1 import AppTest

APP = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app.py")


def test_app_recovers_from_old_session_state():
    """새 버전이 배포될 때 열려 있던 탭에는 옛 구조의 세션 상태가 남아 있다.
    이때도 오류 없이 새 상태로 다시 시작해야 한다 (배포 직후 AttributeError 재발 방지)."""
    at = AppTest.from_file(APP, default_timeout=120)

    class OldSettings:          # 옛 버전 설정 객체 (period_label 등 새 기능 없음)
        semester = "26-2"

    at.session_state["ds"] = object()
    at.session_state["settings"] = OldSettings()
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    assert type(at.session_state["settings"]).__name__ == "Settings"
