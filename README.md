# 에이블 (AIVLE) | AI 업무비서

## 개요
회의록 TXT + 회의 녹음(MP3/M4A/WAV 등) + 화이트보드 PNG/JPG를 통합 분석해 결정사항, 담당자별 업무, 자료 간 차이를 추출합니다. 업무 긴급도와 중요도를 계산하고 오늘 할 일 브리핑, 텍스트/음성 대화, 이메일 공유 기능을 제공합니다.

## 기술 및 구조
- `app.py`: Streamlit 화면, 세션 및 버튼 이벤트
- `config.py`: 비밀값/모델 설정
- `services/meeting_service.py`: 이미지+텍스트 통합 AI 분석, 최종 회의록
- `services/task_service.py`: 업무 순위, 완료 상태 및 브리핑
- `services/speech_service.py`: STT/TTS
- `services/email_service.py`: Gmail SMTP 발송
- `services/history_service.py`: 회의·일정·대화 JSON 백업 및 복원
- `services/calendar_service.py`: 월간 달력, 수동 일정 등록·수정·삭제, 업무 마감일 통합
- `prompts/system_prompts.py`: AI 지시문
- `tests/test_task_service.py`: 순수 Python 점수 로직 테스트

## 로컬 실행
1. Python 3.10 이상 환경에서 `pip install -r requirements.txt`
2. `.streamlit/secrets.toml.example`를 `.streamlit/secrets.toml`로 복사하고 **실제 키는 로컬에서만** 작성
3. `streamlit run app.py`
4. 업무 이름은 회의록의 담당자 표기에 맞춰 사이드바에서 입력

## 비밀값
Streamlit Community Cloud 앱의 **Settings → Secrets**에 다음 최상위 값을 설정합니다.
`OPENAI_API_KEY`, `GMAIL_ADDRESS`, `GMAIL_APP_PASSWORD`.
선택: `OPENAI_MODEL`, `STT_MODEL`, `TTS_MODEL`.
이메일은 실제 Gmail 주소와 앱 비밀번호가 필요하며, SMTP 정책/네트워크로 인해 거부될 수 있습니다. 인증 실패 및 수신자 거부는 앱 화면에서 유형별 안내를 제공합니다.
키/앱 비밀번호는 GitHub에 올리지 않습니다. `.gitignore`에 실제 Secrets가 제외되어 있습니다.

## GitHub · Streamlit 배포
1. 기존 Colab 노트북의 `%%writefile` 셀을 순서대로 실행하여 여러 파일을 생성합니다.
2. 저장소 `my-streamlit-app`에 파일과 폴더 구조를 업로드하고 commit/push합니다.
3. Streamlit Community Cloud에서 GitHub 저장소, 브랜치와 메인 파일 `app.py`를 지정합니다.
4. Secrets 등록 후 **Reboot app**을 실행하고 TXT+이미지 분석, 대화, 음성, 메일을 순서대로 확인합니다.

## 작동 및 제한
- 입력: TXT 1MB, PNG/JPG 8MB 이하. 모델 사용량에 따라 API 비용이 발생합니다.
- 회의 분석, 업무 및 대화는 **현재 Streamlit 세션에만 보관**되며 앱 재시작, 세션 종료 시 사라질 수 있습니다.
- 최근 **10개 질의응답(20메시지)**만 모델 맥락 및 화면 기록에 남습니다.
- 새 회의 분석 시 이전 회의는 **회의 기록** 메뉴에 보관됩니다(세션 내 최대 50건). 회의록/담당 업무/전사 텍스트를 다시 열 수 있습니다.
- 세션 종료 시 기록이 사라질 수 있으므로 **회의 기록 → JSON 백업**을 사용하고, 새 세션에서 **백업 불러오기**로 복원합니다. 대화 최근 10개도 백업에 포함됩니다.
- 원본 오디오/사진은 회의 기록 백업에 포함되지 않습니다. 비밀 회의록은 백업 파일 보관에 유의하세요.
- 회의 중 마이크 녹음 버튼은 `st.audio_input` 기반으로 **녹음 종료 후** 분석합니다. 실시간 스트리밍 전사나 무제한 회의 녹음은 지원하지 않으며 긴 회의는 녹음 파일을 업로드해야 합니다.
- 업무는 담당자 이름 일치 기준으로 필터링합니다. 완료 상태/순위는 새로 계산되지만 영구 저장되지 않습니다.
- 이메일은 명시적으로 초안 작성 후 실제 확인 버튼을 눌러야 발송됩니다. Gmail SMTP 포트 587 차단, 인증 실패, 수신자 거부가 발생할 수 있습니다.
- 오디오 자동 재생 대신 사용자가 음성 듣기 버튼을 클릭합니다.
- 회의록/이미지의 기밀 및 개인정보는 업로드 전에 제거해 주세요. 중요한 AI 분석 결과는 원문과 대조해 확인하세요.

## 테스트
`python -m unittest discover -s tests -v`
실제 API/Streamlit Cloud 사용 및 Gmail 발송 성공 여부는 키와 배포 환경에서 별도 실험이 필요합니다.
TXT+이미지 → 회의 요약/업무 → 상태 변경/순위 → 브리핑 → 멀티턴 → 음성 → 메일의 순서로 수동 검증합니다.
TXT·이미지·녹음 중 모두 없으면 한국어 안내가 표시됩니다.
TXT는 UTF-8 저장을 권장합니다.
TXT에 포함된 악성 지시문은 시스템 명령이 아닌 자료로 취급하지만 모든 공격을 완벽히 방지한다고 보장할 수는 없습니다.

## 개인비서 마스코트 이미지와 화이트보드 미리보기
- `project03/assistant_main.png`, `project03/assistant_side.png`를 Colab의 이미지 준비 셀이 `assets/`로 복사합니다.
- `assets/` 폴더를 GitHub에 함께 올려야 배포된 앱에서도 로봇 이미지가 나타납니다.
- 화이트보드 업로드 시 `getvalue()`로 원본을 한 번 읽고 Pillow로 미리보기·검증 후 동일 바이트를 이미지 분석 요청에 전달합니다.

## 캘린더 기능
- 사이드바 **캘린더**에서 월간 달력으로 수동 일정(파란색)과 회의에서 추출된 업무 마감(노란색)을 확인합니다.
- **새 일정 추가**에서 날짜, 제목, 선택적 시간/메모를 등록하고, **일정 수정·삭제**에서 변경할 수 있습니다.
- 회의 기록으로 저장된 모든 회의의 마감일을 달력에 표시하고, 동일한 활성 회의는 중복 표시하지 않습니다.
- 직접 등록 일정은 최대 200건까지 현재 세션에 유지됩니다.
- **회의 기록 → JSON 백업/복원**에 직접 등록 일정도 포함되며, 기존 버전의 일정이 없는 백업도 복원할 수 있습니다.
- Google Calendar와 자동 동기화되지는 않으며, 알림 푸시/영구 서버 저장도 아직 제공하지 않습니다.
