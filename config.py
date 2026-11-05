"""에이블 설정: 실제 비밀값은 환경변수 또는 Streamlit Secrets에서만 읽습니다."""
import os
import streamlit as st


def get_setting(name, default=None):
    value = os.getenv(name)
    if value:
        return value
    try:
        return st.secrets.get(name, default)
    except (FileNotFoundError, KeyError):
        return default


def llm_model():
    return get_setting('OPENAI_MODEL', 'gpt-4.1-mini')


def stt_model():
    return get_setting('STT_MODEL', 'whisper-1')


def tts_model():
    return get_setting('TTS_MODEL', 'tts-1')
