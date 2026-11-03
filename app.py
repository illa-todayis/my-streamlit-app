
import os
import streamlit as st
from openai import OpenAI

# OpenAI 클라이언트 생성
client = OpenAI()

# 역할 부여
sys_role = """
당신은 '김 대리'의 개인 비서 '에이블'입니다.
김대리가 요청한 업무를 최선을 다해 처리합니다.
미팅 내용을 정확하게 요약하고 담당 업무를 정리합니다.
이메일 발송 요청이 있을 경우에만 send_email 도구를 사용합니다.
"""

# 미팅 내용 읽어오기 → meeting_text
uploaded_file = st.file_uploader("미팅 파일을 업로드하세요.", type=["txt"])

if uploaded_file is not None:
    meeting_text = uploaded_file.read().decode("utf-8")

    # 프롬프트 구성
    prompt = f"""
에이블, 김대리입니다.
다음 미팅 내용을 요약해 이메일로 보내주세요.
혹시 나에게 배정된 업무가 있으면 자세히 적어주세요.
제 이메일 주소는 python2ran@gmail.com 입니다.

[미팅 내용]
{meeting_text}
"""

    if st.button("이메일 보내기"):

        # LLM 호출
        with st.spinner("이메일 발송을 처리 중입니다..."):
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

