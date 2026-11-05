"""음성 파일 STT / 한국어 TTS (OpenAI)."""
import re
from pathlib import Path

SUPPORTED_AUDIO = {'.mp3', '.m4a', '.mp4', '.mpeg', '.mpga', '.wav', '.webm'}
MAX_AUDIO_BYTES = 24 * 1024 * 1024  # API 크기 제한보다 여유 있게 설정


def transcribe_audio(client, model, audio_bytes, filename='voice.wav'):
    """녹음 또는 업로드된 음성을 텍스트로 변환합니다."""
    extension = Path(filename).suffix.lower()
    if extension not in SUPPORTED_AUDIO:
        raise ValueError('음성 파일은 MP3, M4A, MP4, MPEG, MPGA, WAV, WEBM 형식만 지원합니다.')
    if not audio_bytes:
        raise ValueError('음성 파일이 비어 있습니다.')
    if len(audio_bytes) > MAX_AUDIO_BYTES:
        raise ValueError('음성 파일은 24MB 이하로 업로드해 주세요. 긴 녹음은 분할해야 합니다.')
    result = client.audio.transcriptions.create(
        model=model,
        file=(filename, audio_bytes),
    )
    transcript = (result.text or '').strip()
    if not transcript:
        raise ValueError('음성에서 텍스트를 인식하지 못했습니다.')
    return transcript


def prepare_speech_text(text, max_chars=3500):
    """Markdown 기호를 줄여 음성으로 읽기 좋게 변환합니다."""
    if not text or not text.strip():
        raise ValueError('음성으로 변환할 텍스트가 없습니다.')
    cleaned = re.sub(r'```[\s\S]*?```', '코드 블록은 화면을 확인해 주세요.', text)
    cleaned = re.sub(r'[#*`_>~]', '', cleaned)
    cleaned = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', cleaned)
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    return cleaned[:max_chars]


def make_speech(client, model, text):
    """TTS가 만든 MP3 바이트를 반환합니다. 실패 시 호출자에게 오류 전달."""
    prompt = prepare_speech_text(text)
    response = client.audio.speech.create(
        model=model, voice='alloy', input=prompt, response_format='mp3'
    )
    audio = response.content
    if not audio or len(audio) < 100:
        raise ValueError('음성 데이터 생성에 실패했습니다. 다시 시도해 주세요.')
    return audio
