
import os
import io
import csv
import re
import json
import smtplib
import streamlit as st
from openai import OpenAI
from email.mime.text import MIMEText

# 페이지 설정
st.set_page_config(page_title="비서 에이블", page_icon="🪄")

# 화면 디자인
st.markdown("""
<style>
.stApp {background-color: #FFFBFF;}
[data-testid="stSidebar"] {background-color: #F7F0FC;}
h1, h2, h3 {color: #78549D;}
div.stButton > button {border-radius: 12px;}
div.stButton > button[kind="primary"] {
    background-color: #A781C7;
    color: white;
    border: none;
}
div.stButton > button[kind="primary"]:hover {
    background-color: #9366B9;
    color: white;
}
[data-testid="stAudioInput"] {
    background-color: #F7F0FC;
    border: 2px solid #D6B9EA;
    border-radius: 14px;
    padding: 16px;
}
[data-testid="stAudioInput"] button {
    border: 2px solid #9C72BF;
    border-radius: 12px;
    font-weight: 600;
}
</style>
""", unsafe_allow_html=True)

# OpenAI 클라이언트 생성
client = OpenAI()

# 역할 부여
sys_role = """
당신은 KT AIVLE SCHOOL 출신으로 데이터 분석과 AI 개발 능력을 갖춘
마케팅팀 김대리의 친절한 AI 개인비서 '에이블'입니다.
사용자의 요청을 정확하게 이해하고 답변합니다.
"""

meeting_role = sys_role + """
미팅 내용을 분석할 때 다음 순서로 보고합니다.

1. 김 대리의 담당 업무
- 수행 내용, 세부 지시사항, 명시된 업무 기한

2. 미팅 내용 요약
- 주요 안건, 논의 내용, 결정사항, 향후 진행 계획

[작성 규칙]
- 김 대리의 담당 업무를 가장 먼저 보고합니다.
- 항목별 제목을 구분합니다.
- 미팅 내용에 없는 정보는 임의로 추가하지 않습니다.
"""

# 도구 정의
tools = [{
    "type": "function",
    "name": "send_email",
    "description": "사용자가 승인한 요약본을 이메일로 발송합니다.",
    "parameters": {
        "type": "object",
        "properties": {
            "to": {"type": "string", "description": "수신자 이메일"},
            "subject": {"type": "string", "description": "이메일 제목"},
            "body": {"type": "string", "description": "이메일 본문"}
        },
        "required": ["to", "subject", "body"],
        "additionalProperties": False
    },
    "strict": True
}]

# 이메일 발송 함수
def send_email(to, subject, body):
    sender = os.getenv("GMAIL_ADDRESS")
    password = os.getenv("GMAIL_APP_PASSWORD")

    if not sender or not password:
        return {"status": "failed", "error": "Gmail 인증 정보가 없습니다."}

    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = to

    try:
        with smtplib.SMTP("smtp.gmail.com", 587, timeout=20) as s:
            s.starttls()
            s.login(sender, password)
            s.sendmail(sender, to, msg.as_string())
        return {"status": "success"}
    except Exception as e:
        return {"status": "failed", "error": str(e)}

# 이메일 주소 검사
def valid_email(email):
    return bool(re.fullmatch(
        r"[^@\s]+@[^@\s]+\.[^@\s]+", email.strip()
    ))

# 직원 CSV 읽기
def read_employees(file):
    data = file.getvalue()
    text = None

    for encoding in ["utf-8-sig", "cp949"]:
        try:
            text = data.decode(encoding)
            break
        except UnicodeDecodeError:
            continue

    if text is None:
        raise ValueError("CSV 파일의 인코딩을 확인하세요.")

    reader = csv.DictReader(io.StringIO(text))

    if not reader.fieldnames:
        raise ValueError("CSV에 헤더가 없습니다.")

    reader.fieldnames = [
        name.strip() for name in reader.fieldnames
    ]

    # CSV 열 이름 확인
    name_col = next(
        (x for x in ["사원", "사원명", "이름", "성명"]
         if x in reader.fieldnames), None
    )
    dept_col = next(
        (x for x in ["부서", "부서명"]
         if x in reader.fieldnames), None
    )
    email_col = next(
        (x for x in ["이메일주소", "이메일", "이메일 주소", "email"]
         if x in reader.fieldnames), None
    )

    if not all([name_col, dept_col, email_col]):
        raise ValueError(
            "CSV에 사원, 부서, 이메일주소 열이 필요합니다."
        )

    employees = []

    for row in reader:
        name = (row.get(name_col) or "").strip()
        dept = (row.get(dept_col) or "").strip()
        email = (row.get(email_col) or "").strip()

        if name and valid_email(email):
            employees.append({
                "name": name,
                "dept": dept,
                "email": email
            })

    return employees

# 대화 기록 및 미팅 결과
if "history" not in st.session_state:
    st.session_state.history = []

if "meeting_result" not in st.session_state:
    st.session_state.meeting_result = None

if "email_status" not in st.session_state:
    st.session_state.email_status = None

# 사이드바 메뉴
with st.sidebar:
    st.title("🪄 에이블")
    menu = st.radio(
        "메뉴",
        ["💬 일반 채팅", "📄 미팅 업무"],
        label_visibility="collapsed"
    )

# 페이지 제목
st.title("비서 에이블 🪄")
st.caption("김 대리의 AI 업무 파트너")

# 일반 채팅
if menu == "💬 일반 채팅":
    st.subheader("💬 일반 채팅")

    # 최근 대화 5개 출력
    for item in st.session_state.history[-5:]:
        with st.chat_message("user"):
            st.write(item["question"])
        with st.chat_message("assistant"):
            st.write(item["answer"])

    # 프롬프트
    prompt = st.chat_input("에이블에게 질문을 입력하세요")

    if prompt:
        # LLM 호출
        with st.spinner("답변 중입니다..."):
            messages = [{"role": "system", "content": sys_role}]

            for item in st.session_state.history[-5:]:
                messages.extend([
                    {"role": "user", "content": item["question"]},
                    {"role": "assistant", "content": item["answer"]}
                ])

            messages.append({"role": "user", "content": prompt})

            response = client.responses.create(
                model="gpt-4o-mini",
                input=messages
            )

        # 응답 확인 및 기록
        st.session_state.history.append({
            "question": prompt,
            "answer": response.output_text
        })
        st.session_state.history = st.session_state.history[-5:]
        st.rerun()

    # 대화 초기화
    if st.session_state.history:
        if st.button("대화 초기화"):
            st.session_state.history = []
            st.rerun()

# 미팅 업무
else:
    st.subheader("📄 미팅 업무")
    st.caption("미팅 기록을 분석하고 필요한 업무를 처리하세요.")

    # 미팅 파일 업로드
    uploaded_file = st.file_uploader(
        "회의록 파일",
        type=["txt"]
    )

    # 기능 선택
    st.markdown("**기능 선택**")
    col1, col2 = st.columns(2)

    with col1:
        show_summary = st.checkbox("회의록 요약", value=True)
        use_voice = st.checkbox("음성 요청 인식")

    with col2:
        use_tts = st.checkbox("요약 음성 듣기")
        use_email = st.checkbox("요약본 이메일 보내기")

    # 음성 요청 입력
    audio_file = None

    if use_voice:
        st.divider()
        st.markdown("**🎙️ 음성 요청**")

        voice_type = st.radio(
            "음성 입력 방식",
            ["직접 녹음", "파일 업로드"],
            horizontal=True
        )

        if voice_type == "직접 녹음":
            st.info("마이크 버튼을 눌러 녹음을 시작하고, 정지 버튼을 눌러 완료하세요.")

            audio_file = st.audio_input(
                "🎤 음성 녹음",
                sample_rate=16000,
                key="voice_recorder"
            )

        else:
            audio_file = st.file_uploader(
                "음성 파일",
                type=["m4a", "mp3", "wav"]
            )

        # 녹음한 음성 확인
        if audio_file is not None:
            st.caption("녹음 또는 업로드한 음성 확인")
            st.audio(audio_file)

    # 이메일 수신자 선택
    email = ""

    if use_email:
        st.divider()
        st.markdown("**✉️ 요약본 이메일 보내기**")

        recipient_type = st.radio(
            "수신자 선택",
            ["나에게 보내기", "직원 선택", "직접 입력"],
            horizontal=True
        )

        if recipient_type == "나에게 보내기":
            email = "moonstar7577@naver.com"
            st.info(f"받는 사람: {email}")

        elif recipient_type == "직원 선택":
            csv_file = st.file_uploader(
                "직원 목록 CSV",
                type=["csv"],
                help="사원, 부서, 이메일주소 열이 필요합니다."
            )

            if csv_file is not None:
                try:
                    employees = read_employees(csv_file)

                    if employees:
                        selected = st.selectbox(
                            "받는 직원",
                            employees,
                            format_func=lambda x: (
                                f"{x['name']} · {x['dept']} ({x['email']})"
                            )
                        )
                        email = selected["email"]

                        st.caption(f"선택한 이메일: {email}")
                    else:
                        st.warning("유효한 이메일 주소가 없습니다.")

                except ValueError as e:
                    st.error(str(e))

        else:
            email = st.text_input(
                "받는 이메일",
                placeholder="example@gmail.com"
            )

    # 기능 실행
    if st.button("실행", type="primary", use_container_width=True):

        needs_summary = show_summary or use_tts or use_email

        if not any([show_summary, use_voice, use_tts, use_email]):
            st.warning("기능을 선택하세요.")

        elif needs_summary and uploaded_file is None:
            st.warning("회의록 파일을 업로드하세요.")

        elif use_voice and audio_file is None:
            st.warning("음성을 녹음하거나 업로드하세요.")

        elif use_email and not valid_email(email):
            st.warning("올바른 수신 이메일을 선택하세요.")

        else:
            # 결과 초기화
            st.session_state.meeting_result = None
            st.session_state.email_status = None

            result = {
                "meeting_text": "",
                "transcript": "",
                "summary": "",
                "show_summary": show_summary,
                "audio": None,
                "email_enabled": use_email
            }

            # 미팅 내용 읽어오기 → meeting_text
            meeting_text = ""

            if uploaded_file is not None:
                try:
                    meeting_text = uploaded_file.getvalue().decode("utf-8-sig")
                except UnicodeDecodeError:
                    st.error("TXT 파일을 UTF-8로 저장해 주세요.")
                    st.stop()

            result["meeting_text"] = meeting_text

            if needs_summary and not meeting_text.strip():
                st.warning("회의록 내용이 비어 있습니다.")

            else:
                # 음성 메시지 확인(STT) → transcript
                if use_voice:
                    with st.spinner("음성 인식 중입니다..."):
                        transcript = client.audio.transcriptions.create(
                            model="whisper-1",
                            file=audio_file
                        )

                    # 추출된 텍스트 확인
                    result["transcript"] = transcript.text

                # 회의록 요약이 필요한 경우
                if needs_summary:

                    # 프롬프트 구성
                    prompt = f"""
에이블, 김 대리입니다.
다음 미팅 내용을 분석하고 보고해 주세요.

[음성 요청]
{result["transcript"]}

[미팅 내용]
{meeting_text}
"""

                    # LLM 호출
                    with st.spinner("회의록 요약 중입니다..."):
                        response = client.responses.create(
                            model="gpt-4o-mini",
                            input=[
                                {"role": "system", "content": meeting_role},
                                {"role": "user", "content": prompt}
                            ]
                        )

                    result["summary"] = response.output_text

                    # 텍스트를 음성으로 변환 → speech_response
                    if use_tts:
                        with st.spinner("요약 음성 생성 중입니다..."):
                            speech_response = client.audio.speech.create(
                                model="gpt-4o-mini-tts",
                                voice="nova",
                                input=response.output_text
                            )

                        # 음성 출력
                        result["audio"] = speech_response.content

                # 결과 저장
                st.session_state.meeting_result = result

    # 결과 출력
    result = st.session_state.meeting_result

    if result:
        # 회의록 원문 확인
        if result["meeting_text"]:
            with st.expander("📄 업로드한 회의록 원문"):
                st.text(result["meeting_text"])

        # 음성 인식 결과
        if result["transcript"]:
            st.subheader("🎙️ 음성 인식 텍스트")
            st.caption("사용자가 녹음하거나 업로드한 음성의 텍스트 변환 결과")
            st.write(result["transcript"])

        # AI 요약 결과
        if result["summary"] and result["show_summary"]:
            st.subheader("📝 AI 회의록 요약")
            st.write(result["summary"])

        # 음성 듣기
        if result["audio"]:
            st.subheader("🔊 AI 요약 음성")
            st.caption("AI가 작성한 요약 내용을 읽어주는 음성")
            st.audio(result["audio"], format="audio/mp3")

        # 이메일 발송
        if use_email and result["summary"]:
            st.divider()
            st.markdown("**✉️ 이메일 발송 확인**")

            if valid_email(email):
                st.write(f"**받는 사람:** {email}")
                st.write("**제목:** 미팅 내용 요약")

                # 이메일 본문 미리보기
                with st.expander("이메일 본문 미리보기"):
                    st.write(result["summary"])

                sent = st.session_state.email_status

                if sent and sent["status"] == "success":
                    st.success("요약본 이메일을 발송했습니다.")

                elif st.button(
                    "보내기",
                    type="primary",
                    disabled=bool(sent and sent["status"] == "success")
                ):
                    # LLM 호출
                    with st.spinner("이메일 발송 중입니다..."):
                        mail_response = client.responses.create(
                            model="gpt-4o-mini",
                            input=[
                                {
                                    "role": "system",
                                    "content": "send_email 도구를 사용해 이메일 발송을 요청하세요. 이메일은 한 통만 발송합니다."
                                },
                                {
                                    "role": "user",
                                    "content": f"""
수신자: {email}
제목: 미팅 내용 요약
본문:
{result["summary"]}
"""
                                }
                            ],
                            tools=tools,
                            tool_choice={
                                "type": "function",
                                "name": "send_email"
                            }
                        )

                        # 도구 필요 여부 확인
                        tool_calls = [
                            item for item in mail_response.output
                            if item.type == "function_call"
                            and item.name == "send_email"
                        ]

                        if tool_calls:
                            # 모델이 요청한 tool 실행
                            item = tool_calls[0]

                            send_result = send_email(
                                email.strip(),
                                "미팅 내용 요약",
                                result["summary"]
                            )

                            # tool 결과를 모델에 다시 전달
                            client.responses.create(
                                model="gpt-4o-mini",
                                previous_response_id=mail_response.id,
                                input=[{
                                    "type": "function_call_output",
                                    "call_id": item.call_id,
                                    "output": json.dumps(
                                        send_result,
                                        ensure_ascii=False
                                    )
                                }]
                            )

                            st.session_state.email_status = send_result

                            if send_result["status"] == "success":
                                st.success("요약본 이메일을 발송했습니다.")
                            else:
                                st.error(
                                    "이메일 발송 실패: "
                                    + send_result["error"]
                                )
                        else:
                            st.error("이메일 도구가 호출되지 않았습니다.")
