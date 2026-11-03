
import os
import streamlit as st
from openai import OpenAI

# OpenAI 클라이언트 생성
client = OpenAI()

# 역할 부여
sys_role = """
당신은 '김 대리'의 개인 비서 '에이블'입니다.
김대리가 요청한 업무를 최선을 다해 처리합니다.
미팅 내용을 정확하게 요약하고 핵심 내용을 정리합니다.
김대리에게 배정된 업무가 있다면 담당 업무와 세부 내용을 자세히 알려줍니다.
"""

# 페이지 설정
st.subheader("🎙️ 음성으로 미팅 내용 요약")

# 미팅 파일 업로드
uploaded_file = st.file_uploader("미팅 파일을 업로드하세요", type=["txt"])

# 음성 파일 업로드
audio_file = st.file_uploader("음성 파일을 업로드하세요", type=["m4a", "mp3", "wav"])

if uploaded_file is not None and audio_file is not None:

    # 미팅 내용 읽어오기 → meeting_text
    meeting_text = uploaded_file.read().decode("utf-8")

    # 음성 메시지 확인(STT) → transcript
    with st.spinner("음성 인식 중입니다..."):
        transcript = client.audio.transcriptions.create(
            model="whisper-1",
            file=audio_file
        )

    # 추출된 텍스트 확인
    st.write(transcript.text)

    # 프롬프트 구성
    prompt = f"""
{transcript.text}

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
