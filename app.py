
import os
import json
import smtplib
import streamlit as st
from openai import OpenAI
from email.mime.text import MIMEText

# OpenAI 클라이언트 생성
client = OpenAI()

# 페이지 설정
st.subheader("✉️ 미팅 내용 이메일 발송")

# 도구 정의
tools = [{
    "type": "function",
    "name": "send_email",
    "description": "이메일을 발송합니다.",
    "parameters": {
        "type": "object",
        "properties": {
            "to": {
                "type": "string",
                "description": "이메일 수신자"
            },
            "subject": {
                "type": "string",
                "description": "이메일 제목"
            },
            "body": {
                "type": "string",
                "description": "이메일 본문"
            }
        },
        "required": ["to", "subject", "body"],
        "additionalProperties": False
    },
    "strict": True
}]

# 함수 만들기
def send_email(to, subject, body):
    sender = os.getenv("GMAIL_ADDRESS")
    password = os.getenv("GMAIL_APP_PASSWORD")

    # 메일 구성
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = to

    # 메일 보내기
    try:
        with smtplib.SMTP("smtp.gmail.com", 587) as s:
            s.starttls()
            s.login(sender, password)
            s.sendmail(sender, to, msg.as_string())
        return {"status": "success"}
    except Exception as e:
        return {"status": "failed", "error": str(e)}

# 역할 부여
sys_role = """
당신은 김대리의 개인 비서 '에이블'입니다.
김대리가 요청한 업무를 최선을 다해 처리합니다.
미팅 내용을 정확하게 요약하고 핵심 내용을 정리합니다.
김대리에게 배정된 업무가 있다면 담당 업무와 세부 내용을 자세히 알려줍니다.
이메일 발송 요청이 있을 경우에만 send_email 도구를 사용합니다.
이메일 수신자는 사용자가 입력한 주소를 사용합니다.
"""

# 미팅 내용 읽어오기 → meeting_text
uploaded_file = st.file_uploader("미팅 파일을 업로드하세요.", type=["txt"])

# 이메일 주소 입력
email = st.text_input(
    "이메일 주소",
    placeholder="이메일 주소를 입력하세요.",
    label_visibility="collapsed"
)

if uploaded_file is not None:
    meeting_text = uploaded_file.read().decode("utf-8")

    # 프롬프트 구성
    prompt = f"""
에이블, 김대리입니다.
다음 미팅 내용을 요약해 이메일로 보내주세요.
혹시 나에게 배정된 업무가 있으면 자세히 적어주세요.
제 이메일 주소는 {email} 입니다.

[미팅 내용]
{meeting_text}
"""

    # 이메일 보내기 버튼
    if st.button("이메일 보내기"):
        if not email.strip():
            st.warning("이메일 주소를 입력하세요.")
        elif "@" not in email or "." not in email.split("@")[-1]:
            st.warning("올바른 이메일 주소를 입력하세요.")
        else:

            # LLM 호출
            with st.spinner("이메일 발송 중입니다..."):
                response = client.responses.create(
                    model="gpt-4o-mini",
                    input=[
                        {"role": "system", "content": sys_role},
                        {"role": "user", "content": prompt}
                    ],
                    tools=tools
                )

                # 도구 필요 여부 확인
                tool_calls = [
                    item for item in response.output
                    if item.type == "function_call"
                ]

                if not tool_calls:
                    # 도구가 필요 없으면 답변 출력
                    st.write(response.output_text)

                else:
                    # 모델이 요청한 tool 실행
                    tool_outputs = []

                    for item in tool_calls:
                        if item.name == "send_email":
                            args = json.loads(item.arguments)
                            args["to"] = email.strip()
                            result = send_email(**args)

                            tool_outputs.append({
                                "type": "function_call_output",
                                "call_id": item.call_id,
                                "output": json.dumps(result, ensure_ascii=False)
                            })

                    # tool 결과를 모델에 다시 전달
                    final_response = client.responses.create(
                        model="gpt-4o-mini",
                        previous_response_id=response.id,
                        input=tool_outputs
                    )

                    # 응답 확인
                    st.write(final_response.output_text)


