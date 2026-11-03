
import os
import streamlit as st
from openai import OpenAI

# OpenAI 클라이언트 생성
client = OpenAI()

# 역할 부여
sys_role = """
당신은 김대리의 개인 비서 '에이블'입니다.
김대리가 요청한 업무를 최선을 다해 처리합니다.
미팅 내용을 정확하게 요약하고 핵심 내용을 정리합니다.
김대리에게 배정된 업무가 있다면 담당 업무와 세부 내용을 자세히 알려줍니다.
"""

st.subheader("📄 미팅 내용 요약")

# 미팅 내용 읽어오기 → meeting_text
uploaded_file = st.file_uploader("미팅 파일을 업로드하세요", type=["txt"])

if uploaded_file is not None:
    meeting_text = uploaded_file.read().decode("utf-8")

    # 프롬프트 구성
    prompt = f"""
에이블, 김 대리입니다.
다음 미팅 내용을 요약해 주세요.
혹시 나에게 배정된 업무가 있으면 자세히 알려주세요.

[미팅 내용]
{meeting_text}
"""

    # 요약 버튼
    if st.button("미팅 요약하기"):

        # LLM 호출
        response = client.responses.create(
            model="gpt-4o-mini",
            input=[
                {"role": "system", "content": sys_role},
                {"role": "user", "content": prompt}
            ]
        )

        # 응답 확인
        st.write(response.output_text)
