
import os
import json
import smtplib
import streamlit as st
from openai import OpenAI
from email.mime.text import MIMEText

# 페이지 설정
st.set_page_config(page_title="비서 에이블", page_icon="🪄", layout="centered")
st.markdown("""
<style>
.stApp {background: #FFFBFF;}
[data-testid="stSidebar"] {background: #F7F0FC;}
h1, h2, h3 {color: #78549D;}
div.stButton > button[kind="primary"] {
    background: #A781C7;
    border: 0;
    border-radius: 12px;
}
div.stButton > button {border-radius: 12px;}
</style>
""", unsafe_allow_html=True)

# OpenAI 클라이언트 생성
client = OpenAI()

# 역할 부여
sys_role = """
당신은 KT AIVLE SCHOOL 출신으로 데이터 분석과 AI 개발 역량을 갖춘
마케팅팀 김대리의 친절한 AI 개인비서 '에이블'입니다.
사용자의 요청에 정확하고 이해하기 쉽게 답변합니다.
"""

meeting_role = sys_role + """
미팅 기록을 분석할 때 반드시 다음 순서로 보고합니다.
1. 김 대리의 담당 업무: 수행 내용, 세부 지시, 명시된 기한
2. 미팅 내용 요약: 주요 안건, 논의, 결정 사항, 향후 계획
회의록에 없는 내용이나 기한은 추측하지 않습니다.
"""

# 이메일 발송 도구 정의
tools = [{
    "type": "function",
    "name": "send_email",
    "description": "사용자가 요청한 내용을 이메일로 발송합니다.",
    "parameters": {
        "type": "object",
        "properties": {
            "to": {"type": "string", "description": "이메일 수신자"},
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

# 대화 기록 및 미팅 결과
if "history" not in st.session_state:
    st.session_state.history = []

if "meeting_result" not in st.session_state:
    st.session_state.meeting_result = None

# 사이드바 메뉴
with st.sidebar:
    st.title("🪄 에이블")
    menu = st.radio("MENU", ["💬 일반 채팅", "📄 미팅 업무"])
    st.divider()

    st.caption("최근 질문 5개")
    for i, item in enumerate(reversed(st.session_state.history[-5:]), 1):
        st.caption(f"{i}. {item['question'][:32]}")

    if st.button("대화 기록 지우기"):
        st.session_state.history = []
        st.rerun()

st.title("비서 에이블 🪄")
st.caption("김 대리의 작은 AI 업무 파트너 · AIVLE")

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
        with st.spinner("답변을 작성 중입니다..."):
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

# 미팅 업무
else:
    st.subheader("📄 미팅 업무")
    st.caption("파일을 올리고 필요한 기능만 체크해 주세요.")

    # 미팅 파일 업로드
    uploaded_file = st.file_uploader(
        "미팅 기록 (TXT)", type=["txt"]
    )

    # 음성 파일 업로드
    audio_file = st.file_uploader(
        "음성 요청 (M4A / MP3 / WAV)",
        type=["m4a", "mp3", "wav"]
    )

    # 기능 선택
    st.markdown("**✨ 실행할 기능**")
    col1, col2 = st.columns(2)

    with col1:
        show_summary = st.checkbox("📄 회의록 요약", value=True)
        use_voice = st.checkbox("🎙️ 음성 요청 인식")

    with col2:
        use_tts = st.checkbox("🔊 음성 출력")
        use_email = st.checkbox("✉️ 이메일 발송")

    # 이메일 주소 입력
    email = st.text_input(
        "수신 이메일",
        placeholder="example@gmail.com"
    ) if use_email else ""

    if use_email:
        st.caption("이메일은 실행 버튼을 눌렀을 때만 발송됩니다.")

    # 선택 기능 실행
    if st.button("✨ 선택한 기능 실행하기",
                 type="primary", use_container_width=True):

        if not any([show_summary, use_voice, use_tts, use_email]):
            st.warning("실행할 기능을 하나 이상 선택하세요.")

        elif uploaded_file is None:
            st.warning("미팅 기록 TXT 파일을 업로드하세요.")

        elif use_voice and audio_file is None:
            st.warning("음성 파일을 업로드하세요.")

        elif use_email and (
            not email.strip()
            or email.count("@") != 1
            or "." not in email.split("@")[-1]
        ):
            st.warning("올바른 이메일 주소를 입력하세요.")

        else:
            # 미팅 내용 읽어오기 → meeting_text
            meeting_text = uploaded_file.getvalue().decode("utf-8-sig")

            if not meeting_text.strip():
                st.warning("미팅 기록이 비어 있습니다.")
            else:
                st.session_state.meeting_result = None
                transcript_text = ""

                # 음성 메시지 확인(STT) → transcript
                if use_voice:
                    with st.spinner("음성을 인식 중입니다..."):
                        transcript = client.audio.transcriptions.create(
                            model="whisper-1",
                            file=audio_file
                        )
                    transcript_text = transcript.text

                # 프롬프트 구성
                prompt = f"""
에이블, 김 대리입니다.
다음 미팅 내용을 분석하고 보고해 주세요.
{transcript_text}

[미팅 내용]
{meeting_text}
"""

                # LLM 호출
                with st.spinner("미팅 내용을 분석 중입니다..."):
                    response = client.responses.create(
                        model="gpt-4o-mini",
                        input=[
                            {"role": "system", "content": meeting_role},
                            {"role": "user", "content": prompt}
                        ]
                    )

                # 결과 저장
                result = {
                    "summary": response.output_text,
                    "transcript": transcript_text,
                    "show_summary": show_summary,
                    "audio": None,
                    "email_status": None
                }

                # 텍스트를 음성으로 변환 → speech_response
                if use_tts:
                    with st.spinner("음성을 생성 중입니다..."):
                        speech_response = client.audio.speech.create(
                            model="gpt-4o-mini-tts",
                            voice="nova",
                            input=response.output_text
                        )

                    # 음성 출력
                    result["audio"] = speech_response.content

                # 이메일 발송
                if use_email:
                    with st.spinner("이메일을 발송 중입니다..."):
                        # 도구를 포함하여 LLM 호출
                        mail_response = client.responses.create(
                            model="gpt-4o-mini",
                            input=[
                                {
                                    "role": "system",
                                    "content": "send_email 도구로 지정된 요약을 그대로 한 통 이메일로 보내세요."
                                },
                                {
                                    "role": "user",
                                    "content": f"""받는 사람: {email}
제목: 미팅 내용 요약
본문:
{response.output_text}"""
                                }
                            ],
                            tools=tools,
                            tool_choice={
                                "type": "function",
                                "name": "send_email"
                            }
                        )

                        # 도구 필요 여부 확인
                        tool_call = next(
                            (
                                x for x in mail_response.output
                                if x.type == "function_call"
                                and x.name == "send_email"
                            ),
                            None
                        )

                        if tool_call:
                            # 모델이 요청한 tool 실행
                            args = json.loads(tool_call.arguments)
                            send_result = send_email(
                                email.strip(),
                                args["subject"],
                                args["body"]
                            )

                            # tool 결과를 모델에 다시 전달
                            client.responses.create(
                                model="gpt-4o-mini",
                                previous_response_id=mail_response.id,
                                input=[{
                                    "type": "function_call_output",
                                    "call_id": tool_call.call_id,
                                    "output": json.dumps(
                                        send_result, ensure_ascii=False
                                    )
                                }]
                            )
                            result["email_status"] = send_result
                        else:
                            result["email_status"] = {
                                "status": "failed",
                                "error": "이메일 도구가 호출되지 않았습니다."
                            }

                st.session_state.meeting_result = result

    # 응답 확인
    result = st.session_state.meeting_result

    if result:
        if result["transcript"]:
            st.markdown("**🎙️ 인식된 음성 요청**")
            st.write(result["transcript"])

        if result["show_summary"]:
            st.markdown("**📄 분석 결과**")
            st.write(result["summary"])

        # 음성 듣기
        if result["audio"]:
            st.markdown("**🔊 음성으로 듣기**")
            st.audio(result["audio"], format="audio/mp3")

        # 이메일 발송 결과
        if result["email_status"]:
            if result["email_status"]["status"] == "success":
                st.success("이메일 한 통을 발송했습니다.")
            else:
                st.error(
                    "이메일 발송 실패: "
                    + result["email_status"]["error"]
                )
