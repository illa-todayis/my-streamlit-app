
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
다음 미팅 내용을 분석하고 아래 순서에 따라 보고해 주세요.

1. 김 대리의 담당 업무
- 나에게 배정된 업무를 가장 먼저 보고해 주세요.
- 업무별로 수행해야 할 내용과 세부 지시사항을 자세히 정리해 주세요.
- 업무 기한이나 추가 요청사항이 있다면 함께 알려주세요.

2. 미팅 내용 요약
- 미팅의 주요 안건과 핵심 논의 내용을 요약해 주세요.
- 주요 결정사항과 향후 진행 계획을 정리해 주세요.

[작성 규칙]
- 반드시 김 대리의 담당 업무를 먼저 작성한 후 미팅 내용을 요약하세요.
- 항목별 제목을 구분하여 가독성 있게 작성하세요.
- 미팅 내용에 없는 정보는 임의로 추가하지 마세요.


[미팅 내용]
{meeting_text}
"""

    # LLM 호출
    with st.spinner("요약 중입니다..."):
        response = client.responses.create(
            model="gpt-4o-mini",
            input=[
                {"role": "system", "content": sys_role},
                {"role": "user", "content": prompt}
            ]
        )

    # 응답 확인
    st.write(response.output_text)

