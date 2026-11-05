"""에이블: 깔끔한 사이드바 메뉴 UI + 멀티모달 분석 + TTS."""
import io
import copy
import json
from datetime import datetime
from pathlib import Path
from uuid import uuid4
from zoneinfo import ZoneInfo

import streamlit as st
from openai import OpenAI
from PIL import Image, UnidentifiedImageError

from config import get_setting, llm_model, stt_model, tts_model
from prompts.system_prompts import CHAT_INSTRUCTIONS
from services.meeting_service import analyze_meeting, build_meeting_report
from services.task_service import STATUSES, make_briefing, personal_tasks, rank_tasks, with_ids
from services.speech_service import transcribe_audio, make_speech, SUPPORTED_AUDIO, MAX_AUDIO_BYTES
from services.email_service import parse_recipients, send_emails
from services.history_service import make_record, export_backup, import_backup, upsert_record
from services.calendar_service import save_event, deadline_entries, entries_for_day, month_html

st.set_page_config(page_title='에이블 | AI 업무비서', page_icon='🤖', layout='wide', initial_sidebar_state='expanded')
ASSET_DIR = Path(__file__).resolve().parent / 'assets'
MAIN_IMAGE = ASSET_DIR / 'assistant_main.png'
SIDE_IMAGE = ASSET_DIR / 'assistant_side.png'

# 원본 화면 시안의 다크 모드, 간결한 여백, 둥근 모서리를 반영한 스타일
st.markdown("""<style>
[data-testid="stAppViewContainer"] {background: #090a0c;}
[data-testid="stSidebar"] {background: #0c0d10; border-right: 1px solid #24262b;}
.block-container {max-width: 1040px; padding-top: 1.35rem; padding-bottom: 3rem;}
[data-testid="stHeader"] {background: rgba(9,10,12,.86);}
h1, h2, h3 {letter-spacing: -0.045em;}
h1 {font-size: 1.72rem !important;}
h2, h3 {font-size: 1.26rem !important;}
[data-testid="stVerticalBlockBorderWrapper"] > div {border-radius: 14px;}
[data-testid="stFileUploader"] {border-radius: 12px;}
[data-testid="stMetric"] {background: #121417; border: 1px solid #26282c; border-radius: 12px; padding: .8rem 1rem;}
div.stButton > button[kind="primary"] {background: #12b8ae; color: #061313; border: 0;}
div.stButton > button {border-radius: 10px;}
[data-testid="stSidebar"] [role="radiogroup"] label {padding: .35rem .25rem;}
 </style>""", unsafe_allow_html=True)

DEFAULTS = {
    'analysis': None, 'tasks': [], 'messages': [], 'pending_email': None,
    'brief_audio': None, 'brief_audio_for': None, 'last_chat_audio': None,
    'last_transcript': '', 'last_chat_reply': '', 'owner': '김 대리',
    'auto_voice': False, 'last_chat_audio_for': None, 'email_results': [],
    'meeting_transcript': '', 'meeting_archive': [], 'active_meeting_id': None,
    'calendar_events': [], 'calendar_selected': None, 'calendar_offset': 0,
}
for key, value in DEFAULTS.items():
    if key not in st.session_state:
        st.session_state[key] = value.copy() if isinstance(value, (dict, list)) else value

api_key = get_setting('OPENAI_API_KEY')
if not api_key:
    st.error('OPENAI_API_KEY가 없습니다. Streamlit Community Cloud의 앱 Secrets를 확인하세요.')
    st.stop()

@st.cache_resource(show_spinner=False)
def get_client(key):
    return OpenAI(api_key=key, timeout=45.0, max_retries=1)

client = get_client(api_key)
today = datetime.now(ZoneInfo('Asia/Seoul')).date()


def reset_meeting():
    st.session_state.analysis = None
    st.session_state.tasks = []
    st.session_state.brief_audio = None
    st.session_state.brief_audio_for = None
    st.session_state.pending_email = None
    st.session_state.meeting_transcript = ''
    st.session_state.email_results = []
    st.session_state.active_meeting_id = None


def update_status(task_id):
    for task in st.session_state.tasks:
        if task['id'] == task_id:
            task['status'] = st.session_state[f'status_{task_id}']
            break
    st.session_state.brief_audio = None
    st.session_state.brief_audio_for = None
    if st.session_state.active_meeting_id and st.session_state.analysis:
        st.session_state.meeting_archive = upsert_record(
            st.session_state.meeting_archive, make_record(
                st.session_state.analysis, st.session_state.tasks,
                st.session_state.meeting_transcript,
                record_id=st.session_state.active_meeting_id,
            ), preserve_created=True
        )


def format_problem(exc):
    name = type(exc).__name__
    if name in ('AuthenticationError', 'PermissionDeniedError'):
        return 'API 인증 또는 권한 오류입니다. 키와 프로젝트 권한을 확인하세요.'
    if name == 'RateLimitError':
        return '요청 한도 또는 API 사용량 제한입니다. 잠시 후 다시 시도하세요.'
    if name in ('APITimeoutError', 'APIConnectionError', 'TimeoutError'):
        return 'API 서버 연결이 지연되거나 실패했습니다.'
    if isinstance(exc, (ValueError, UnicodeError, json.JSONDecodeError)):
        return str(exc)[:220]
    return f'요청 처리 실패 ({name}). 앱 로그를 확인하세요.'


with st.sidebar:
    # 과도하게 큰 이미지를 피하고 로고/브랜드 영역만 간결하게 배치합니다.
    logo, name_col = st.columns([1, 3], vertical_alignment='center')
    with logo:
        if SIDE_IMAGE.is_file():
            st.image(str(SIDE_IMAGE), use_container_width=True)
        else:
            st.markdown('🤖')
    with name_col:
        st.markdown('**에이블**')
        st.caption('AI 개인비서 AIVLE')
    st.divider()
    page = st.radio(
        '메뉴',
        ['회의 통합 분석', '회의 기록', '캘린더', '담당 업무', '업무 브리핑', 'AI 비서 대화'],
        format_func=lambda name: {
            '회의 통합 분석': '◈  회의 통합 분석',
            '회의 기록': '▤  회의 기록',
            '캘린더': '▦  캘린더',
            '담당 업무': '☷  담당 업무',
            '업무 브리핑': '▦  업무 브리핑',
            'AI 비서 대화': '◯  AI 비서 대화',
        }[name],
        label_visibility='collapsed',
        key='page_navigation',
    )
    st.divider()
    st.caption(f'미완료 업무 {sum(t.get("status") != "완료" for t in st.session_state.tasks)}건 · 저장된 회의 {len(st.session_state.meeting_archive)}건')
    with st.expander('⚙️ 설정', expanded=False):
        st.text_input('담당자 이름', key='owner', help='회의록의 담당자 표기와 같게 입력하세요.')
        st.caption(f'기준일 {today.isoformat()} · 한국 시간')
        st.toggle('AI 답변 자동 음성 생성', key='auto_voice', help='답변마다 TTS API를 호출하므로 비용이 추가됩니다.')
        st.caption(f'최근 대화 {len(st.session_state.messages) // 2}/10')
        st.caption('OpenAI: 설정됨' if api_key else 'OpenAI: 설정 필요')
        st.caption('Gmail: 설정됨' if get_setting('GMAIL_ADDRESS') and get_setting('GMAIL_APP_PASSWORD') else 'Gmail: 설정 필요')
        if st.button('새 대화 시작', use_container_width=True):
            st.session_state.messages = []
            st.session_state.last_transcript = ''
            st.session_state.last_chat_reply = ''
            st.session_state.last_chat_audio = None
            st.session_state.last_chat_audio_for = None
            st.rerun()
        if st.button('회의/업무 데이터 초기화', use_container_width=True):
            reset_meeting()
            st.rerun()
    st.caption('회의·일정은 현재 세션에 저장됩니다. 영구 보관은 [회의 기록]에서 JSON 백업을 사용하세요.')

# 메인 영역은 선택된 페이지 하나만 표시합니다.
page_kicker = {
    '회의 통합 분석': 'AI 개인비서 AIVLE',
    '회의 기록': 'MEETING ARCHIVE',
    '캘린더': 'CALENDAR',
    '담당 업무': '업무 대시보드',
    '업무 브리핑': 'DAILY BRIEFING',
    'AI 비서 대화': 'AI ASSISTANT',
}
st.caption(page_kicker[page])
st.title(page)

if page == '회의 통합 분석':
    with st.container(border=True):
        st.markdown('**회의 자료 업로드**')
        c1, c2 = st.columns(2)
        with c1:
            text_file = st.file_uploader('회의록 TXT', type=['txt'], key='meeting_txt', help='UTF-8 텍스트 파일')
        with c2:
            image_file = st.file_uploader('화이트보드 이미지 (최대 8MB)', type=['png','jpg','jpeg'], key='meeting_img')
        recording_file = st.file_uploader(
            '회의 녹음 파일 (선택 · MP3/M4A/WAV 등, 최대 24MB)',
            type=['mp3', 'm4a', 'mp4', 'mpeg', 'mpga', 'wav', 'webm'],
            key='meeting_audio',
            help='업로드한 녹음을 STT로 전사한 뒤 회의록·화이트보드와 함께 분석합니다.'
        )
        st.markdown('**🎙️ 회의 중 바로 녹음하기**')
        live_recording = st.audio_input('마이크로 회의 녹음 (녹음 종료 후 분석 가능)', key='live_meeting_audio')
        st.caption('브라우저의 마이크 권한이 필요합니다. 녹음이 끝나면 통합 분석 실행을 눌러 주세요. 긴 회의는 파일 녹음 후 업로드를 권장합니다.')
        if live_recording is not None:
            st.success(f'마이크 녹음 준비됨 · {len(live_recording.getvalue())/1024/1024:.1f}MB')
        if recording_file is not None:
            st.caption(f'✓ 녹음 파일 첨부: {recording_file.name} · {recording_file.size / 1024 / 1024:.1f}MB')
        audio_source = None
        if live_recording is not None and recording_file is not None:
            choice = st.radio('분석할 음성 선택', ['직접 녹음', '업로드 파일'], horizontal=True)
            audio_source = live_recording if choice == '직접 녹음' else recording_file
        else:
            audio_source = live_recording if live_recording is not None else recording_file
        # 화이트보드 미리보기는 제거했습니다. 파일명/형식 검증만 표시합니다.
        whiteboard_bytes, image_mime, image_error = None, None, None
        if image_file is not None:
            try:
                raw_bytes = image_file.getvalue()
                if not raw_bytes or len(raw_bytes) > 8_000_000:
                    raise ValueError('이미지는 8MB 이하의 PNG/JPG 파일이어야 합니다.')
                with Image.open(io.BytesIO(raw_bytes)) as img:
                    image_format = img.format
                    if image_format not in ('PNG', 'JPEG'):
                        raise ValueError('PNG 또는 JPG 이미지 파일만 지원합니다.')
                    img.verify()
                image_mime = 'image/png' if image_format == 'PNG' else 'image/jpeg'
                whiteboard_bytes = raw_bytes
                st.caption(f'✓ 화이트보드 업로드 완료: {image_file.name} · {len(raw_bytes) / 1024 / 1024:.1f}MB')
            except (UnidentifiedImageError, OSError, ValueError) as exc:
                image_error = str(exc)
                st.error('이미지 검증 실패: ' + image_error)

        analyze_clicked = st.button('통합 분석 실행', type='primary', use_container_width=True)
    if analyze_clicked:
        if text_file is None and image_file is None and audio_source is None:
            st.warning('회의록 TXT, 화이트보드 이미지, 회의 녹음 중 하나 이상 업로드해 주세요.')
        elif image_error:
            st.error('화이트보드 파일을 확인해 주세요.')
        elif text_file is not None and text_file.size > 1_000_000:
            st.warning('회의록 TXT는 1MB 이하로 올려 주세요.')
        elif audio_source is not None and len(audio_source.getvalue()) > MAX_AUDIO_BYTES:
            st.warning('회의 녹음 파일은 24MB 이하로 올려 주세요.')
        else:
            try:
                meeting_text = text_file.getvalue().decode('utf-8-sig') if text_file is not None else ''
                transcript_text = ''
                if audio_source is not None:
                    with st.spinner('회의 음성을 텍스트로 변환하고 있습니다...'):
                        transcript_text = transcribe_audio(
                            client, stt_model(), audio_source.getvalue(),
                            'meeting_recording.wav' if audio_source is live_recording else audio_source.name
                        )
                combined_text = meeting_text.strip()
                if transcript_text:
                    combined_text += ('\n\n' if combined_text else '') + '[회의 녹음 전사]\n' + transcript_text
                with st.spinner('회의 자료를 통합 분석하고 담당 업무를 추출하는 중...'):
                    analysis = analyze_meeting(client, llm_model(), combined_text, whiteboard_bytes, image_mime)
                reset_meeting()
                st.session_state.analysis = analysis
                st.session_state.tasks = with_ids(analysis.get('tasks', []))
                st.session_state.meeting_transcript = transcript_text
                record = make_record(analysis, st.session_state.tasks, transcript_text)
                st.session_state.meeting_archive = upsert_record(st.session_state.meeting_archive, record)
                st.session_state.active_meeting_id = record['id']
                st.success(f'분석 완료 · 추출 업무 {len(st.session_state.tasks)}건 · [회의 기록]에 보관됨')
            except Exception as exc:
                st.error(format_problem(exc))

    if st.session_state.meeting_transcript:
        with st.expander('🎙️ 회의 녹음 전사 결과 확인'):
            st.caption('자동 음성 인식 결과에는 오류가 있을 수 있어 원본 녹음과 대조해 주세요.')
            st.text(st.session_state.meeting_transcript)
            st.download_button('전사 텍스트 다운로드', st.session_state.meeting_transcript,
                               'meeting_transcript.txt', mime='text/plain')

    if st.session_state.analysis:
        info = st.session_state.analysis
        st.subheader(info.get('meeting_title', '통합 회의록'))
        st.write(info.get('summary', ''))
        a, b, c = st.columns(3)
        a.metric('추출 업무', len(st.session_state.tasks))
        b.metric('확정 결정', len(info.get('decisions', [])))
        c.metric('확인 필요', len(info.get('conflicts', [])))
        with st.expander('확정 결정사항', expanded=True):
            for item in info.get('decisions', []):
                st.markdown('- ' + item)
        with st.expander('검토 중인 사항'):
            for item in info.get('pending', []):
                st.markdown('- ' + item)
        with st.expander('자료 간 불일치 / 확인 필요'):
            for item in info.get('conflicts', []):
                st.warning(item)
        report = build_meeting_report(info, st.session_state.tasks)
        st.download_button('최종 회의록 다운로드 (.md)', report, 'final_meeting_report.md', mime='text/markdown')
        with st.expander('최종 회의록 텍스트 보기'):
            st.markdown(report)
    else:
        st.caption('회의록·화이트보드·회의 녹음 중 하나 이상 올리고 분석을 실행하세요.')

elif page == '회의 기록':
    st.caption('분석 완료한 회의록을 다시 열거나, JSON으로 백업하고 다른 세션에서 복원할 수 있습니다.')
    st.info('현재 보관함은 브라우저 세션에만 유지됩니다. 중요한 회의는 꼭 백업 파일을 다운로드하세요. 원본 음성·사진은 보관하지 않습니다.')
    backup_json = export_backup(st.session_state.meeting_archive, st.session_state.messages, st.session_state.calendar_events)
    st.download_button('⬇️ 회의·일정·최근 대화 JSON 백업', backup_json,
                       file_name=f'aivle_meeting_backup_{today.isoformat()}.json',
                       mime='application/json', use_container_width=True)
    with st.expander('📥 이전 백업 복원'):
        restore_file = st.file_uploader('에이블 백업 JSON 파일 선택', type=['json'], key='history_restore_file')
        if st.button('백업 불러오기', disabled=restore_file is None):
            try:
                archive, messages, events = import_backup(restore_file.getvalue(), include_events=True)
                st.session_state.meeting_archive = archive
                st.session_state.messages = messages
                st.session_state.calendar_events = events
                reset_meeting()
                st.success(f'회의 {len(archive)}건, 일정 {len(events)}건, 대화 {len(messages)//2}개를 불러왔습니다.')
                st.rerun()
            except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                st.error('백업을 불러올 수 없습니다: ' + str(exc)[:150])
    if st.session_state.meeting_archive:
        records = list(reversed(st.session_state.meeting_archive))
        for record in records:
            with st.container(border=True):
                st.markdown(f"**{record['title']}**")
                st.caption(f"회의일: {record.get('meeting_date') or '미상'} · 저장: {record['saved_at'][:16].replace('T',' ')} · 담당 업무 {len(record['tasks'])}건")
                st.write(record['analysis'].get('summary',''))
                cols = st.columns([1,1,1])
                if cols[0].button('이 회의 불러오기', key=f"load_{record['id']}", use_container_width=True):
                    st.session_state.analysis = copy.deepcopy(record['analysis'])
                    st.session_state.tasks = copy.deepcopy(record['tasks'])
                    st.session_state.meeting_transcript = record.get('transcript','')
                    st.session_state.active_meeting_id = record['id']
                    st.session_state.brief_audio = None
                    st.session_state.brief_audio_for = None
                    st.session_state.pending_email = None
                    for task in st.session_state.tasks:
                        st.session_state[f"status_{task['id']}"] = task.get('status', '미시작')
                    st.success('이전 회의 자료를 불러왔습니다. 담당 업무 메뉴에서 확인해 주세요.')
                    st.rerun()
                report = build_meeting_report(record['analysis'], record['tasks'])
                cols[1].download_button('회의록 다운로드', report,
                                        file_name=f"meeting_{record['id']}.md", mime='text/markdown',
                                        key=f"dl_{record['id']}", use_container_width=True)
                if cols[2].button('기록 삭제', key=f"del_{record['id']}", use_container_width=True):
                    st.session_state.meeting_archive = [r for r in st.session_state.meeting_archive if r['id'] != record['id']]
                    if st.session_state.active_meeting_id == record['id']:
                        reset_meeting()
                    st.rerun()
                with st.expander('최종 회의록 펼치기'):
                    st.markdown(report)
                if record.get('transcript'):
                    with st.expander('회의 음성 전사 펼치기'):
                        st.text(record['transcript'])
    else:
        st.caption('아직 저장된 회의가 없습니다. [회의 통합 분석]에서 자료를 분석하면 자동으로 이곳에 쌓입니다.')

elif page == '캘린더':
    from datetime import date as calendar_date
    import calendar as calendar_lib

    st.caption('회의에서 추출된 업무 마감일과 직접 등록한 일정을 한눈에 확인합니다. Google Calendar와는 연결되지 않습니다.')
    deadlines = deadline_entries(
        st.session_state.meeting_archive,
        st.session_state.analysis,
        st.session_state.tasks,
        st.session_state.active_meeting_id,
    )
    events = st.session_state.calendar_events
    base = today.year * 12 + today.month - 1 + st.session_state.calendar_offset
    year, zero_month = divmod(base, 12)
    month = zero_month + 1
    left, center, right = st.columns([1, 4, 1], vertical_alignment='center')
    with left:
        if st.button('◀ 이전', key='cal_prev', use_container_width=True):
            st.session_state.calendar_offset -= 1
            st.rerun()
    with center:
        st.markdown(f'<h3 style="text-align:center; margin:0">{year}년 {month}월</h3>', unsafe_allow_html=True)
    with right:
        if st.button('다음 ▶', key='cal_next', use_container_width=True):
            st.session_state.calendar_offset += 1
            st.rerun()
    st.markdown("""<style>
    .aivle-calendar table{width:100%;border-collapse:separate;border-spacing:4px;table-layout:fixed}
    .aivle-calendar th{font-size:.8rem;color:#a9b2be;text-align:center;padding:6px}
    .aivle-calendar td{height:90px;vertical-align:top;padding:9px;border:1px solid #2d343a;border-radius:9px;background:#15191d}
    .aivle-calendar td.other{opacity:.3}
    .aivle-calendar td.today{border:2px solid #13bdb3;background:#142a2a}
    .aivle-calendar .day-number{font-weight:650;margin-bottom:8px}
    .aivle-calendar .event-dot,.aivle-calendar .task-dot{display:block;font-size:.69rem;margin-top:3px;overflow:hidden;white-space:nowrap}
    .aivle-calendar .event-dot{color:#60c5ee}.aivle-calendar .task-dot{color:#e8c37b}
    </style>""", unsafe_allow_html=True)
    st.markdown(month_html(year, month, events, deadlines, today), unsafe_allow_html=True)
    st.caption('파란색: 직접 등록 일정 · 노란색: 미완료 업무 마감 · 날짜별 상세는 아래에서 선택')
    chosen = st.date_input('확인할 날짜', value=today, key='cal_day_select')
    day_entries = entries_for_day(events, deadlines, chosen)
    st.subheader(f'{chosen.isoformat()} 일정 ({len(day_entries)}건)')
    if not day_entries:
        st.info('선택한 날짜에 일정이 없습니다.')
    for entry in day_entries:
        if entry['kind'] == 'deadline':
            with st.container(border=True):
                st.markdown(f"**📌 {entry['title']}** · {entry.get('status','미시작')}")
                st.caption(f"회의: {entry.get('meeting','')} · 담당: {entry.get('owner','')}")
        else:
            with st.container(border=True):
                st.markdown(f"**🗓️ {entry.get('time','') or '종일'} · {entry['title']}**")
                if entry.get('note'):
                    st.caption(entry['note'])
    with st.expander('➕ 새 일정 추가', expanded=False):
        with st.form('calendar_add_form', clear_on_submit=True):
            add_title = st.text_input('일정 제목', max_chars=120)
            add_day = st.date_input('일정 날짜', value=chosen)
            add_timed = st.checkbox('시간 지정', value=False)
            add_time = st.time_input('시작 시간', value=datetime.now(ZoneInfo('Asia/Seoul')).time())
            add_note = st.text_area('메모 (선택)', max_chars=2000)
            add_submit = st.form_submit_button('일정 저장', type='primary')
        if add_submit:
            try:
                st.session_state.calendar_events = save_event(
                    st.session_state.calendar_events,
                    {'title':add_title,'date':add_day.isoformat(),
                     'time':add_time.strftime('%H:%M') if add_timed else '', 'note':add_note}
                )
                st.success('일정이 등록되었습니다.')
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))
    if events:
        with st.expander('✏️ 일정 수정·삭제'):
            chosen_id = st.selectbox('편집할 일정', options=[e['id'] for e in events],
                format_func=lambda key: next(f"{e['date']} · {e['title']}" for e in events if e['id']==key))
            selected_event = next(e for e in events if e['id'] == chosen_id)
            with st.form(f'calendar_edit_{chosen_id}'):
                edit_title = st.text_input('제목', value=selected_event['title'], max_chars=120)
                edit_day = st.date_input('날짜', value=calendar_date.fromisoformat(selected_event['date']))
                edit_time = st.text_input('시간 (HH:MM 또는 빈칸)', value=selected_event.get('time',''))
                edit_note = st.text_area('메모', value=selected_event.get('note',''), max_chars=2000)
                edit_save = st.form_submit_button('수정 저장', type='primary')
                edit_delete = st.form_submit_button('일정 삭제')
            if edit_save:
                try:
                    st.session_state.calendar_events = save_event(events,
                        {'id':chosen_id,'title':edit_title,'date':edit_day.isoformat(),
                         'time':edit_time.strip(),'note':edit_note})
                    st.success('일정을 수정했습니다.')
                    st.rerun()
                except ValueError as exc:
                    st.error(str(exc))
            if edit_delete:
                st.session_state.calendar_events = [e for e in events if e['id'] != chosen_id]
                st.success('일정을 삭제했습니다.')
                st.rerun()
    st.caption('직접 등록 일정은 세션에서만 유지됩니다. 회의 기록 메뉴의 JSON 백업에 일정도 함께 포함됩니다.')

elif page == '담당 업무':
    if not st.session_state.analysis:
        st.info('먼저 회의 통합 분석 메뉴에서 자료를 분석해 주세요.')
    else:
        ranked = rank_tasks(st.session_state.tasks, today)
        mine = personal_tasks(ranked, st.session_state.owner)
        pending = [x for x in mine if x['status'] != '완료']
        m1, m2, m3 = st.columns(3)
        m1.metric('전체 업무', len(mine))
        m2.metric('미완료', len(pending))
        m3.metric('마감 임박/초과', len([x for x in pending if x['days_left'] is not None and x['days_left'] <= 2]))
        st.caption('우선순위 = 마감 긴급도 60점 + 중요도 25점 + 선행작업 15점 · AI 추정치는 확인 필요')
        show_all = st.checkbox('모든 담당자의 업무 표시')
        for task in (ranked if show_all else mine):
            with st.container(border=True):
                left, right = st.columns([3, 1], vertical_alignment='center')
                left.markdown('**' + task['title'] + '**')
                left.caption(f"담당 {task['owner']} · 마감 {task['due_date'] or '미정'} · {task['urgency_status']} · {task['priority_score']}점")
                status_key = f"status_{task['id']}"
                if status_key not in st.session_state:
                    st.session_state[status_key] = task.get('status', '미시작')
                right.selectbox('진행 상태', STATUSES, key=status_key, on_change=update_status, args=(task['id'],))
                with st.expander('업무 설명 및 출처'):
                    st.write(task.get('description', ''))
                    st.caption(task.get('source_notes', ''))
        if not (ranked if show_all else mine):
            st.warning('담당 업무를 찾지 못했습니다. 설정에서 담당자 이름을 확인해 주세요.')

elif page == '업무 브리핑':
    if not st.session_state.analysis:
        st.info('회의 분석 후 오늘의 업무 브리핑을 이용할 수 있습니다.')
    else:
        briefing = make_briefing(st.session_state.tasks, st.session_state.owner, today)
        with st.container(border=True):
            st.markdown(briefing)
        col1, col2 = st.columns(2)
        with col1:
            st.download_button('브리핑 다운로드', briefing, 'today_briefing.md', mime='text/markdown', use_container_width=True)
        with col2:
            listen = st.button('🔊 브리핑 음성 재생', use_container_width=True)
        if listen:
            try:
                with st.spinner('브리핑 음성 생성 중...'):
                    if st.session_state.brief_audio_for != briefing:
                        st.session_state.brief_audio = make_speech(client, tts_model(), briefing)
                        st.session_state.brief_audio_for = briefing
            except Exception as exc:
                st.error(format_problem(exc))
        if st.session_state.brief_audio is not None and st.session_state.brief_audio_for == briefing:
            st.audio(st.session_state.brief_audio, format='audio/mp3', autoplay=listen)

elif page == 'AI 비서 대화':
    st.caption('텍스트 또는 음성으로 질문하세요. 최근 10개 대화를 기억합니다.')
    if not st.session_state.messages:
        with st.container(border=True):
            if MAIN_IMAGE.is_file():
                st.image(str(MAIN_IMAGE), width=96)
            st.markdown('**이렇게 질문해 보세요**')
            st.caption('오늘 가장 급한 업무가 뭐야? · 회의에서 확정된 사항을 알려줘 · KPI 정의서를 어떻게 시작할까?')
    for message in st.session_state.messages[-20:]:
        with st.chat_message(message['role']):
            st.markdown(message['content'])
    audio_input = st.audio_input('음성으로 질문하기', key='chat_audio_input')
    voice_submit = st.button('녹음한 질문 실행', disabled=audio_input is None)
    user_question = st.chat_input('에이블에게 질문을 입력하세요...')
    if voice_submit and audio_input is not None:
        try:
            with st.spinner('음성 인식 중...'):
                user_question = transcribe_audio(client, stt_model(), audio_input.getvalue(), 'voice.wav')
            st.session_state.last_transcript = user_question
            st.info('인식된 질문: ' + (user_question or '음성을 인식하지 못했습니다.'))
        except Exception as exc:
            st.error(format_problem(exc))
            user_question = None
    if user_question and user_question.strip():
        question = user_question.strip()
        if len(question) > 2500:
            st.warning('질문은 최대 2,500자까지 입력할 수 있습니다.')
        else:
            st.session_state.last_chat_audio = None
            st.session_state.last_chat_audio_for = None
            email_intent = ('메일' in question or '이메일' in question) and any(w in question for w in ('보내', '전송', '공유'))
            if email_intent:
                if st.session_state.analysis:
                    report = build_meeting_report(st.session_state.analysis, st.session_state.tasks)
                    brief = make_briefing(st.session_state.tasks, st.session_state.owner, today)
                    kind = '오늘의 브리핑' if ('브리핑' in question or '오늘 할 일' in question) else '통합 회의록'
                    content = brief if kind == '오늘의 브리핑' else report
                    st.session_state.pending_email = {'to': '', 'subject': f'[에이블] {kind}', 'body': content}
                    answer = '이메일 초안을 준비했습니다. 아래 공유 영역에서 확인 후 전송할 수 있습니다.'
                else:
                    answer = '회의 분석을 먼저 진행한 후 이메일을 준비할 수 있습니다.'
            else:
                try:
                    context = json.dumps({'calendar_events': st.session_state.calendar_events[:60]}, ensure_ascii=False)
                    if st.session_state.analysis:
                        context = json.dumps({
                            'summary': st.session_state.analysis.get('summary'),
                            'decisions': st.session_state.analysis.get('decisions'),
                            'pending': st.session_state.analysis.get('pending'),
                            'conflicts': st.session_state.analysis.get('conflicts'),
                            'my_tasks': personal_tasks(rank_tasks(st.session_state.tasks, today), st.session_state.owner),
                            'calendar_events': st.session_state.calendar_events[:60],
                        }, ensure_ascii=False)[:14000]
                    with st.spinner('답변 생성 중...'):
                        response = client.responses.create(
                            model=llm_model(),
                            instructions=CHAT_INSTRUCTIONS + f'\n사용자: {st.session_state.owner}\n오늘: {today}\n참고 업무 정보: {context}',
                            input=[*st.session_state.messages[-20:], {'role': 'user', 'content': question}],
                            max_output_tokens=1000,
                        )
                    answer = response.output_text.strip() or '응답이 비어 있습니다. 다시 질문해 주세요.'
                except Exception as exc:
                    answer = '답변 생성 실패: ' + format_problem(exc)
            st.session_state.messages.extend([{'role': 'user', 'content': question}, {'role': 'assistant', 'content': answer}])
            st.session_state.messages = st.session_state.messages[-20:]
            st.session_state.last_chat_reply = answer
            # 자동 TTS는 설정에서 사용자가 명시적으로 켠 경우에만 호출합니다.
            if st.session_state.auto_voice and not answer.startswith('답변 생성 실패:'):
                try:
                    with st.spinner('답변 음성 생성 중...'):
                        st.session_state.last_chat_audio = make_speech(client, tts_model(), answer)
                        st.session_state.last_chat_audio_for = answer
                except Exception as exc:
                    st.session_state.last_chat_audio = None
                    st.session_state.last_chat_audio_for = None
                    st.warning('텍스트 답변은 생성했지만 음성 생성에 실패했습니다: ' + format_problem(exc))
            st.rerun()
    if st.session_state.last_chat_reply:
        with st.container(border=True):
            st.markdown('**🔊 에이블의 답변 음성으로 듣기**')
            st.caption('재생 버튼을 누르면 MP3를 만들고 플레이어에 표시합니다. 브라우저가 자동 재생을 차단하면 ▶ 버튼을 눌러 주세요.')
            play_reply = st.button('🔊 마지막 답변 음성 생성 / 재생', use_container_width=True)
            if play_reply:
                try:
                    with st.spinner('음성 답변을 생성하고 있습니다...'):
                        if (st.session_state.last_chat_audio_for != st.session_state.last_chat_reply
                                or not st.session_state.last_chat_audio):
                            st.session_state.last_chat_audio = make_speech(
                                client, tts_model(), st.session_state.last_chat_reply)
                            st.session_state.last_chat_audio_for = st.session_state.last_chat_reply
                except Exception as exc:
                    st.session_state.last_chat_audio = None
                    st.session_state.last_chat_audio_for = None
                    st.error('TTS 생성 실패: ' + format_problem(exc))
            if (st.session_state.last_chat_audio
                    and st.session_state.last_chat_audio_for == st.session_state.last_chat_reply):
                st.audio(st.session_state.last_chat_audio, format='audio/mp3', autoplay=play_reply)
                st.download_button('MP3 음성 다운로드', st.session_state.last_chat_audio,
                                   'aivle_reply.mp3', mime='audio/mpeg')
            else:
                st.caption('아직 생성된 음성 파일이 없습니다. 위 버튼을 눌러 주세요.')

# 이메일은 AI와 독립적으로 처리하며 반드시 사용자 최종 확인이 있어야 발송합니다.
st.divider()
with st.expander('✉️ 최종 회의록 / 업무 브리핑 이메일 공유', expanded=bool(st.session_state.pending_email)):
    if not st.session_state.analysis:
        st.info('회의 분석이 완료되면 이메일 공유가 활성화됩니다.')
    else:
        kind = st.radio('공유할 문서', ['최종 회의록', '오늘의 브리핑', '둘 다'], horizontal=True)
        if st.button('이메일 초안 작성'):
            report = build_meeting_report(st.session_state.analysis, st.session_state.tasks)
            brief = make_briefing(st.session_state.tasks, st.session_state.owner, today)
            content = {'최종 회의록': report, '오늘의 브리핑': brief, '둘 다': report + '\n\n---\n\n' + brief}[kind]
            st.session_state.pending_email = {'to': '', 'subject': f'[에이블] {kind}', 'body': content}
            st.session_state.email_results = []
        if st.session_state.pending_email is not None:
            with st.form('email_confirm_form', clear_on_submit=False):
                to = st.text_area('받는 사람 이메일 주소 (여러 명 가능)',
                                  value=st.session_state.pending_email.get('to', ''), height=100,
                                  help='쉼표, 세미콜론 또는 줄바꿈으로 구분하세요. 최대 10개, 각각 개별 발송합니다.')
                subject = st.text_input('제목', value=st.session_state.pending_email.get('subject', ''))
                body = st.text_area('본문 (수정 가능)', value=st.session_state.pending_email.get('body', ''), height=220)
                confirm = st.form_submit_button('✅ 입력한 모든 수신자에게 발송 확인', type='primary')
            if confirm:
                st.session_state.pending_email = {'to': to, 'subject': subject, 'body': body}
                try:
                    recipients = parse_recipients(to)
                    if not subject.strip() or not body.strip():
                        raise ValueError('제목과 본문을 입력해 주세요.')
                    with st.spinner(f'{len(recipients)}명에게 개별 이메일을 보내는 중...'):
                        results = send_emails(recipients, subject, body)
                    st.session_state.email_results = results
                    success = [x for x in results if x['status'] == 'success']
                    failed = [x for x in results if x['status'] != 'success']
                    if success:
                        st.success(f'Gmail 서버 접수: {len(success)}건 / {len(recipients)}건 (실제 배달은 수신 서버 상태에 따라 다를 수 있습니다)')
                    if failed:
                        st.error(f'발송 실패: {len(failed)}건. 아래 결과를 확인하고 실패 주소만 재시도하세요.')
                    else:
                        st.session_state.pending_email = None
                except ValueError as exc:
                    st.error(str(exc))
            if st.button('초안 취소'):
                st.session_state.pending_email = None
                st.session_state.email_results = []
                st.rerun()
    if st.session_state.email_results:
        st.markdown('**수신자별 전송 결과**')
        for item in st.session_state.email_results:
            if item['status'] == 'success':
                st.caption(f"✓ {item['to']} · Gmail 접수")
            else:
                st.warning(f"{item['to']} · {item['error']}")
