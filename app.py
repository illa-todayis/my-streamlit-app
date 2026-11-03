
import os
import streamlit as st
from openai import OpenAI

# OpenAI 클라이언트 생성
client = OpenAI()

# 페이지 설정
st.set_page_config(page_title="비서 에이블", page_icon="🪄")

# 제목
st.title("비서 에이블")
st.write("안녕하세요! 업무를 도와드리는 AI 개인비서 에이블입니다.")

# 역할 부여
sys_role = """
당신은 KT AIVLE SCHOOL 출신이며 탁월한 데이터 분석 및 AI 개발 능력을 보유하고 있으며
마케팅팀에서 근무하고 있는 김대리의 음성인식 AI 개인비서입니다.
업무 요청 시 '에이블'이라는 호칭으로 불립니다.
당신이 해야하는 일은 회의록 분석, 업무 지시추출, 다양한 질문에 대한 응답, 음성 인터페이스, 이메일 전송기능이 있습니다.
이를 도와주는 업무를 하며 친절한 AI비서입니다.
"""

# 프롬프트
prompt = st.text_input("질문을 입력하세요: ")

# 질문 버튼
if st.button("질문하기"):
    if prompt.strip() == "":
        st.warning("질문을 입력하세요.")
    else:
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
