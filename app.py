
import os
import io
import csv
import re
import json
import hashlib
import sqlite3
import smtplib
from datetime import date, datetime, time
from zoneinfo import ZoneInfo
from email.mime.text import MIMEText

import streamlit as st
from openai import OpenAI
from streamlit_calendar import calendar

# 페이지 설정
st.set_page_config(page_title="비서 에이블", page_icon="🪄", layout="wide")

# 화면 디자인
st.markdown("""
<style>
.stApp {background:#FFFCFF;}
[data-testid="stSidebar"] {background:#F7F0FB;}
h1,h2,h3 {color:#71518E;}

div.stButton > button,
[data-testid="stFormSubmitButton"] button {
    border-radius:11px !important;
    border:1px solid #D8C5E5 !important;
    color:#73518F !important;
    background:#FBF7FF !important;
}

button[kind="primary"],
[data-testid="stBaseButton-primary"],
[data-testid="stFormSubmitButton"] button[kind="primary"] {
    background:#9470B7 !important;
    border-color:#9470B7 !important;
    color:white !important;
}

[data-testid="stAudioInput"] {
    background:#F6EEFC;
    border:2px solid #B996D6;
    border-radius:14px;
    padding:16px;
}

[data-testid="stAudioInput"] button {
    border:2px solid #9265B5 !important;
    border-radius:12px !important;
    font-weight:700 !important;
}

[data-baseweb="input"] > div,
[data-baseweb="textarea"] > div,
[data-baseweb="select"] > div {
    background:#F8F3FC !important;
}

[data-testid="stForm"] {
    background:#FDF9FF;
    border:1px solid #E3D5ED;
    border-radius:14px;
}
</style>
""", unsafe_allow_html=True)

# OpenAI 클라이언트
client = OpenAI()

# 역할 부여
sys_role = """당신은 마케팅팀 김대리의 AI 개인비서 '에이블'입니다.
사용자의 업무 요청에 정확하고 친절하게 답변합니다."""

meeting_role = sys_role + """
회의록을 분석할 때 김 대리의 담당 업무를 먼저 보고하고,
그다음 주요 안건, 결정사항, 향후 계획을 요약하세요.
회의록에 없는 정보와 마감일을 지어내지 마세요.
"""

# 한국 기준 오늘 날짜
def get_today():
    return datetime.now(ZoneInfo("Asia/Seoul")).date()


# 데이터베이스 연결 및 기존 데이터 유지
DB_PATH = os.getenv("AIVLE_DB_PATH", "aivle_tasks.db")

def db_connect():
    conn = sqlite3.connect(DB_PATH, timeout=10)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS tasks (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            owner TEXT NOT NULL,
            due_date TEXT,
            description TEXT NOT NULL,
            kind TEXT NOT NULL,
            done INTEGER NOT NULL DEFAULT 0,
            priority TEXT NOT NULL DEFAULT '보통',
            sort_order INTEGER NOT NULL DEFAULT 0,
            start_time TEXT
        )
    """)

    columns = {
        row[1] for row in conn.execute("PRAGMA table_info(tasks)")
    }

    # 기존 DB에 새 컬럼 추가
    if "priority" not in columns:
        conn.execute("""
            ALTER TABLE tasks
            ADD COLUMN priority TEXT NOT NULL DEFAULT '보통'
        """)

    if "sort_order" not in columns:
        conn.execute("""
            ALTER TABLE tasks
            ADD COLUMN sort_order INTEGER NOT NULL DEFAULT 0
        """)
        conn.execute("UPDATE tasks SET sort_order=rowid")

    if "start_time" not in columns:
        conn.execute("ALTER TABLE tasks ADD COLUMN start_time TEXT")

    conn.commit()
    return conn


# 업무 조회
def list_tasks():
    with db_connect() as conn:
        return conn.execute("""
            SELECT id, title, owner, due_date, description,
                   kind, done, priority, sort_order, start_time
            FROM tasks
            ORDER BY sort_order, id
        """).fetchall()


# 업무 저장
def save_tasks(tasks):
    added = 0

    with db_connect() as conn:
        next_pos = conn.execute(
            "SELECT COALESCE(MAX(sort_order),0) FROM tasks"
        ).fetchone()[0]

        for task in tasks:
            title = (task.get("title") or "").strip()
            owner = (task.get("owner") or "").strip() or "미지정"
            due = task.get("due_date")
            start_time = task.get("start_time")

            if not title:
                continue

            if due:
                try:
                    due = date.fromisoformat(due).isoformat()
                except (ValueError, TypeError):
                    due = None

            if start_time:
                try:
                    start_time = time.fromisoformat(
                        start_time
                    ).strftime("%H:%M")
                except (ValueError, TypeError):
                    start_time = None

            # 날짜가 없다면 시간도 미정
            if not due:
                start_time = None

            # 동일 업무 중복 확인
            existing = conn.execute("""
                SELECT 1 FROM tasks
                WHERE title=? AND owner=? AND due_date IS ?
            """, (title, owner, due)).fetchone()

            if existing:
                continue

            task_id = hashlib.sha256(
                f"{title}|{owner}|{due}".encode()
            ).hexdigest()[:20]

            priority = task.get("priority", "보통")

            if priority not in ("높음", "보통", "낮음"):
                priority = "보통"

            next_pos += 1

            cur = conn.execute("""
                INSERT OR IGNORE INTO tasks
                (id, title, owner, due_date, description, kind,
                 priority, sort_order, start_time)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                task_id,
                title,
                owner,
                due,
                task.get("description", ""),
                task.get("kind", "업무"),
                priority,
                next_pos,
                start_time
            ))

            added += cur.rowcount

        conn.commit()

    return added


# 업무 수정
def update_task(task_id, title, owner, due, description,
                kind, priority, start_time=None):
    with db_connect() as conn:
        conn.execute("""
            UPDATE tasks
            SET title=?, owner=?, due_date=?, description=?,
                kind=?, priority=?, start_time=?
            WHERE id=?
        """, (
            title.strip(),
            owner.strip() or "미지정",
            due,
            description.strip(),
            kind,
            priority,
            start_time if due else None,
            task_id
        ))
        conn.commit()


# 업무 삭제
def delete_task(task_id):
    with db_connect() as conn:
        conn.execute("DELETE FROM tasks WHERE id=?", (task_id,))
        conn.commit()


# 업무 순서 변경
def change_order(task_id, destination, visible_ids):
    all_ids = [row[0] for row in list_tasks()]
    visible = [item for item in all_ids if item in visible_ids]

    if task_id not in visible:
        return

    visible.remove(task_id)
    visible.insert(destination, task_id)

    sequence = iter(visible)
    ordered = [
        next(sequence) if item in visible_ids else item
        for item in all_ids
    ]

    with db_connect() as conn:
        for pos, item in enumerate(ordered, 1):
            conn.execute(
                "UPDATE tasks SET sort_order=? WHERE id=?",
                (pos, item)
            )
        conn.commit()


# AI 업무 및 일정 추출
def extract_tasks(meeting_text):
    schema = {
        "type": "object",
        "properties": {
            "tasks": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "owner": {"type": "string"},
                        "due_date": {
                            "type": ["string", "null"]
                        },
                        "start_time": {
                            "type": ["string", "null"]
                        },
                        "description": {"type": "string"},
                        "kind": {
                            "type": "string",
                            "enum": ["업무", "일정"]
                        },
                        "priority": {
                            "type": "string",
                            "enum": ["높음", "보통", "낮음"]
                        }
                    },
                    "required": [
                        "title", "owner", "due_date", "start_time",
                        "description", "kind", "priority"
                    ],
                    "additionalProperties": False
                }
            }
        },
        "required": ["tasks"],
        "additionalProperties": False
    }

    response = client.responses.create(
        model="gpt-4o-mini",
        input=[
            {
                "role": "system",
                "content": """
회의록에 명시된 구체적인 업무와 일정만 추출하세요.

1. 담당자가 없으면 '미지정'으로 표시하세요.
2. 정확한 날짜가 있으면 YYYY-MM-DD로 반환하세요.
3. 날짜가 없거나 불확실하면 due_date=null로 반환하세요.
4. 회의 기준일이 없는 상대 날짜는 추측하지 마세요.
5. 명시된 시간만 HH:MM(24시간제)으로 반환하세요.
6. 시간이 없으면 start_time=null로 반환하세요.
7. 시간을 임의로 만들어 내지 마세요.
8. 기한이 없는 업무는 날짜와 시간을 모두 null로 처리하세요.
9. 중요도에 따라 우선순위를 추천하세요.
10. 단순 논의를 업무로 만들지 마세요.

반드시 JSON 스키마를 따르세요.
"""
            },
            {
                "role": "user",
                "content": meeting_text
            }
        ],
        text={
            "format": {
                "type": "json_schema",
                "name": "meeting_tasks",
                "strict": True,
                "schema": schema
            }
        }
    )

    return json.loads(response.output_text)["tasks"]


# 이메일 도구 정의
email_tools = [{
    "type": "function",
    "name": "send_email",
    "description": "승인한 요약본 이메일 전송",
    "parameters": {
        "type": "object",
        "properties": {
            "to": {"type": "string"},
            "subject": {"type": "string"},
            "body": {"type": "string"}
        },
        "required": ["to", "subject", "body"],
        "additionalProperties": False
    },
    "strict": True
}]


# 이메일 발송
def send_email(to, subject, body):
    sender = os.getenv("GMAIL_ADDRESS")
    password = os.getenv("GMAIL_APP_PASSWORD")

    if not sender or not password:
        return {
            "status": "failed",
            "error": "Gmail 환경변수가 없습니다."
        }

    msg = MIMEText(body, "plain", "utf-8")
    msg["From"] = sender
    msg["To"] = to
    msg["Subject"] = subject

    try:
        with smtplib.SMTP("smtp.gmail.com", 587, timeout=20) as server:
            server.starttls()
            server.login(sender, password)
            server.sendmail(sender, to, msg.as_string())

        return {"status": "success"}

    except Exception as e:
        return {"status": "failed", "error": str(e)}


# 직원 CSV 읽기
def employee_options(file):
    content = file.getvalue()

    try:
        raw = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        raw = content.decode("cp949")

    employees = []

    for row in csv.DictReader(io.StringIO(raw)):
        row = {
            k.strip(): (v or "").strip()
            for k, v in row.items() if k
        }

        name = next(
            (row[k] for k in ("사원", "사원명", "이름") if k in row),
            ""
        )

        dept = next(
            (row[k] for k in ("부서", "부서명") if k in row),
            ""
        )

        email = next(
            (
                row[k] for k in
                ("이메일주소", "이메일", "이메일 주소", "email")
                if k in row
            ),
            ""
        )

        if name and re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
            employees.append((name, dept, email))

    return employees


# 세션 상태
if "history" not in st.session_state:
    st.session_state.history = []

if "meeting_result" not in st.session_state:
    st.session_state.meeting_result = None

if "email_sent_key" not in st.session_state:
    st.session_state.email_sent_key = None

if "pending_tasks" not in st.session_state:
    st.session_state.pending_tasks = []

if "review_batch" not in st.session_state:
    st.session_state.review_batch = 0


# 사이드바 메뉴
with st.sidebar:
    st.title("🪄 에이블")

    menu = st.radio(
        "메뉴",
        ["💬 일반 채팅", "📄 미팅 업무", "📅 일정 및 업무"],
        label_visibility="collapsed"
    )

st.title("비서 에이블 🪄")
st.caption("김 대리의 AI 업무 파트너")


# 일반 채팅
if menu == "💬 일반 채팅":
    st.subheader("💬 일반 채팅")

    for item in st.session_state.history:
        with st.chat_message("user"):
            st.write(item["question"])

        with st.chat_message("assistant"):
            st.write(item["answer"])

    prompt = st.chat_input("에이블에게 질문을 입력하세요")

    if prompt:
        messages = [{"role": "system", "content": sys_role}]

        for item in st.session_state.history:
            messages.extend([
                {"role": "user", "content": item["question"]},
                {"role": "assistant", "content": item["answer"]}
            ])

        messages.append({"role": "user", "content": prompt})

        with st.spinner("답변 중입니다..."):
            response = client.responses.create(
                model="gpt-4o-mini",
                input=messages
            )

        st.session_state.history.append({
            "question": prompt,
            "answer": response.output_text
        })

        st.session_state.history = st.session_state.history[-5:]
        st.rerun()

    if st.session_state.history and st.button("대화 초기화"):
        st.session_state.history = []
        st.rerun()


# 미팅 업무
elif menu == "📄 미팅 업무":
    st.subheader("📄 미팅 업무")

    uploaded_file = st.file_uploader(
        "회의록 TXT",
        type=["txt"]
    )

    # 기능 선택
    st.markdown("**필요한 기능**")

    c1, c2 = st.columns(2)

    with c1:
        show_summary = st.checkbox("회의록 요약", value=True)
        use_voice = st.checkbox("음성 요청 인식")
        auto_tasks = st.checkbox(
            "AI 일정·할 일 자동 등록",
            value=True
        )

    with c2:
        use_tts = st.checkbox("요약 음성 듣기")
        use_email = st.checkbox("요약본 이메일 보내기")

    # 음성 입력
    audio_file = None

    if use_voice:
        st.markdown("**🎙️ 음성 요청**")

        voice_type = st.radio(
            "음성 입력",
            ["직접 녹음", "파일 업로드"],
            horizontal=True
        )

        if voice_type == "직접 녹음":
            st.caption(
                "녹음 버튼을 누르면 시작되고, "
                "정지 버튼을 누르면 녹음이 끝나요."
            )

            audio_file = st.audio_input(
                "🎤 녹음",
                sample_rate=16000
            )

        else:
            audio_file = st.file_uploader(
                "음성 파일",
                type=["m4a", "mp3", "wav"]
            )

        if audio_file is not None:
            st.audio(audio_file)

    # 이메일 수신자 선택
    email = ""

    if use_email:
        st.markdown("**✉️ 요약본 수신자**")

        method = st.radio(
            "수신자 선택",
            ["나에게 보내기", "직원 선택", "직접 입력"],
            horizontal=True
        )

        if method == "나에게 보내기":
            email = "moonstar7577@naver.com"
            st.caption(email)

        elif method == "직원 선택":
            csv_file = st.file_uploader(
                "직원 CSV",
                type=["csv"]
            )

            if csv_file:
                try:
                    employees = employee_options(csv_file)

                    if employees:
                        selected = st.selectbox(
                            "받는 직원",
                            employees,
                            format_func=lambda x:
                                f"{x[0]} · {x[1]} ({x[2]})"
                        )

                        email = selected[2]

                    else:
                        st.warning(
                            "CSV에서 올바른 직원 이메일을 찾지 못했어요."
                        )

                except (UnicodeError, csv.Error) as e:
                    st.error(f"CSV 읽기 오류: {e}")

        else:
            email = st.text_input(
                "받는 이메일",
                placeholder="example@gmail.com"
            )

    # 미팅 분석 실행
    if st.button("실행", type="primary", use_container_width=True):
        needs_summary = (
            show_summary or use_tts or use_email or auto_tasks
        )

        if not any((
            show_summary, use_voice, use_tts, use_email, auto_tasks
        )):
            st.warning("기능을 선택하세요.")

        elif needs_summary and uploaded_file is None:
            st.warning("회의록을 업로드하세요.")

        elif use_voice and audio_file is None:
            st.warning("음성을 녹음하거나 업로드하세요.")

        elif use_email and not re.fullmatch(
            r"[^@\s]+@[^@\s]+\.[^@\s]+",
            email.strip()
        ):
            st.warning("받는 이메일을 확인하세요.")

        else:
            try:
                meeting_text = (
                    uploaded_file.getvalue().decode("utf-8-sig")
                    if uploaded_file else ""
                )

                if needs_summary and not meeting_text.strip():
                    st.warning("회의록 내용이 비어 있습니다.")
                    st.stop()

                st.session_state.pending_tasks = []

                result = {
                    "meeting_text": meeting_text,
                    "transcript": "",
                    "summary": "",
                    "show_summary": show_summary,
                    "audio": None,
                    "added": None
                }

                # 음성 인식
                if use_voice:
                    with st.spinner("음성 인식 중입니다..."):
                        transcript = client.audio.transcriptions.create(
                            model="whisper-1",
                            file=audio_file
                        )

                    result["transcript"] = transcript.text

                if needs_summary:
                    prompt = f"""에이블, 김 대리입니다.
미팅 내용을 분석해 주세요.

[음성 요청]
{result['transcript']}

[미팅 내용]
{meeting_text}
"""

                    # 회의록 요약
                    with st.spinner("회의록 요약 중입니다..."):
                        response = client.responses.create(
                            model="gpt-4o-mini",
                            input=[
                                {
                                    "role": "system",
                                    "content": meeting_role
                                },
                                {
                                    "role": "user",
                                    "content": prompt
                                }
                            ]
                        )

                    result["summary"] = response.output_text

                    # AI 업무 추출
                    if auto_tasks:
                        with st.spinner("일정과 할 일을 추출 중입니다..."):
                            tasks = extract_tasks(meeting_text)

                        st.session_state.pending_tasks = tasks
                        st.session_state.review_batch += 1

                    # 요약 음성 생성
                    if use_tts:
                        with st.spinner("요약 음성 생성 중입니다..."):
                            speech_response = client.audio.speech.create(
                                model="gpt-4o-mini-tts",
                                voice="nova",
                                input=result["summary"]
                            )

                        result["audio"] = speech_response.content

                st.session_state.meeting_result = result
                st.session_state.email_sent_key = None

            except (UnicodeDecodeError, ValueError, json.JSONDecodeError) as e:
                st.error(f"파일 또는 분석 결과를 확인하세요: {e}")

            except Exception as e:
                st.error(f"처리 중 오류가 발생했어요: {e}")

    # 미팅 분석 결과
    result = st.session_state.meeting_result

    if result:
        if result["meeting_text"]:
            with st.expander("📄 회의록 원문"):
                st.text(result["meeting_text"])

        if result["transcript"]:
            st.subheader("🎙️ 음성 인식 텍스트")
            st.write(result["transcript"])

        if result["summary"] and result["show_summary"]:
            st.subheader("📝 AI 회의록 요약")
            st.write(result["summary"])

        if result["added"] is not None:
            st.success(
                f"일정 및 할 일 {result['added']}건 신규 등록 (중복 제외)"
            )

        # 에이블의 일정 등록 확인
        if st.session_state.pending_tasks:
            st.divider()
            st.subheader("📋 에이블의 일정 등록 확인")
            st.caption(
                "회의록에 없는 날짜와 시간은 추측하지 않았어요. "
                "필요한 정보만 확인한 뒤 등록할게요."
            )

            batch = st.session_state.review_batch

            with st.container(border=True):
                selections = []

                for i, task in enumerate(st.session_state.pending_tasks):
                    with st.container(border=True):
                        st.markdown(
                            f"**{i + 1}. {task['title']}**"
                        )

                        st.caption(
                            f"담당자: {task.get('owner') or '미지정'}"
                        )

                        include = st.checkbox(
                            "등록하기",
                            value=True,
                            key=f"include_{batch}_{i}"
                        )

                        # AI가 추출한 날짜 확인
                        raw_due = task.get("due_date")

                        try:
                            parsed_due = (
                                date.fromisoformat(raw_due)
                                if raw_due else None
                            )
                        except (TypeError, ValueError):
                            parsed_due = None

                        # 날짜가 빠진 경우 에이블이 질문
                        if parsed_due is None:
                            with st.chat_message("assistant"):
                                st.write(
                                    "회의록에서 정확한 날짜를 찾지 못했어요. "
                                    "날짜를 지정할까요?"
                                )

                            date_choice = st.radio(
                                "날짜 처리",
                                ["기한 미정으로 등록", "날짜 지정"],
                                horizontal=True,
                                key=f"date_choice_{batch}_{i}"
                            )

                            picked_date = (
                                st.date_input(
                                    "정확한 날짜",
                                    value=get_today(),
                                    key=f"date_{batch}_{i}"
                                )
                                if date_choice == "날짜 지정"
                                else None
                            )

                        else:
                            st.caption(
                                f"회의록에서 확인한 날짜: "
                                f"{parsed_due.isoformat()}"
                            )

                            picked_date = parsed_due

                        # AI가 추출한 시간 확인
                        raw_time = task.get("start_time")

                        try:
                            parsed_time = (
                                time.fromisoformat(raw_time)
                                if raw_time else None
                            )
                        except (TypeError, ValueError):
                            parsed_time = None

                        if picked_date is None:
                            st.caption(
                                "시간: 미정 (날짜 지정 후 입력 가능)"
                            )
                            picked_time = None

                        else:
                            if parsed_time:
                                st.caption(
                                    "회의록에서 시간을 확인했어요."
                                )
                            else:
                                st.caption(
                                    "회의록에 시간 정보가 없어 "
                                    "'시간 미정'으로 처리했어요."
                                )

                            # 시간 정보가 없으면 기본적으로 체크 해제
                            set_time = st.checkbox(
                                "시간 지정",
                                value=parsed_time is not None,
                                key=f"set_time_{batch}_{i}"
                            )

                            picked_time = (
                                st.time_input(
                                    "시작 시간",
                                    value=parsed_time or time(9, 0),
                                    key=f"time_{batch}_{i}"
                                )
                                if set_time else None
                            )

                        selections.append((
                            include,
                            task,
                            picked_date,
                            picked_time
                        ))

                register = st.button(
                    "확인 후 등록",
                    type="primary",
                    use_container_width=True,
                    key=f"confirm_review_{batch}"
                )

            # 확인된 업무 등록
            if register:
                reviewed = []

                for include, task, picked_date, picked_time in selections:
                    if include:
                        reviewed.append({
                            **task,
                            "due_date": (
                                picked_date.isoformat()
                                if picked_date else None
                            ),
                            "start_time": (
                                picked_time.strftime("%H:%M")
                                if picked_time else None
                            )
                        })

                if not reviewed:
                    st.warning("등록할 업무를 하나 이상 선택하세요.")

                else:
                    added = save_tasks(reviewed)

                    st.session_state.meeting_result["added"] = added
                    st.session_state.pending_tasks = []

                    st.rerun()

        # 요약 음성 재생
        if result["audio"]:
            st.subheader("🔊 AI 요약 음성")
            st.audio(result["audio"], format="audio/mp3")

        # 이메일 발송 확인
        if use_email and result["summary"]:
            st.markdown("**✉️ 이메일 발송 확인**")

            if re.fullmatch(
                r"[^@\s]+@[^@\s]+\.[^@\s]+",
                email.strip()
            ):
                st.write(f"받는 사람: **{email}**")

                with st.expander("이메일 본문 미리보기"):
                    st.write(result["summary"])

                mail_key = hashlib.sha256(
                    (email + result["summary"]).encode()
                ).hexdigest()

                if st.session_state.email_sent_key == mail_key:
                    st.success("이 요약본은 전송 완료했어요.")

                elif st.button("보내기", type="primary"):
                    with st.spinner("이메일 발송 중입니다..."):
                        try:
                            mail_response = client.responses.create(
                                model="gpt-4o-mini",
                                input=[
                                    {
                                        "role": "system",
                                        "content": (
                                            "send_email 도구를 호출하세요. "
                                            "메일은 한 통만 발송합니다."
                                        )
                                    },
                                    {
                                        "role": "user",
                                        "content": f"""받는 사람: {email}
제목: 미팅 내용 요약
본문:
{result['summary']}"""
                                    }
                                ],
                                tools=email_tools,
                                tool_choice={
                                    "type": "function",
                                    "name": "send_email"
                                }
                            )

                            calls = [
                                x for x in mail_response.output
                                if x.type == "function_call"
                                and x.name == "send_email"
                            ]

                            if not calls:
                                st.error(
                                    "이메일 도구가 호출되지 않았어요."
                                )

                            else:
                                status = send_email(
                                    email.strip(),
                                    "미팅 내용 요약",
                                    result["summary"]
                                )

                                if status["status"] == "success":
                                    st.session_state.email_sent_key = mail_key

                                # 도구 실행 결과 전달
                                try:
                                    client.responses.create(
                                        model="gpt-4o-mini",
                                        previous_response_id=mail_response.id,
                                        input=[{
                                            "type": "function_call_output",
                                            "call_id": calls[0].call_id,
                                            "output": json.dumps(
                                                status,
                                                ensure_ascii=False
                                            )
                                        }]
                                    )
                                except Exception:
                                    pass

                                if status["status"] == "success":
                                    st.success(
                                        "이메일을 발송했어요."
                                    )
                                else:
                                    st.error(status["error"])

                        except Exception as e:
                            st.error(
                                f"이메일 처리 오류: {e}"
                            )


# 일정 및 업무
else:
    st.subheader("📅 일정 및 업무")

    tasks = list_tasks()
    unfinished = sum(not row[6] for row in tasks)
    today = get_today()

    # 업무 현황
    c1, c2, c3 = st.columns(3)

    c1.metric("전체 업무", len(tasks))
    c2.metric("미완료", unfinished)
    c3.metric("완료", len(tasks) - unfinished)

    # 날짜가 있는 업무만 캘린더에 표시
    dated = [row for row in tasks if row[3]]
    events = []

    for row in dated:
        if row[6]:
            shade = "#DDD6E6"
        elif row[5] == "일정":
            shade = "#C7B0DE"
        else:
            shade = "#EDCAD8"

        start_at = (
            f"{row[3]}T{row[9]}:00"
            if row[9] else row[3]
        )

        events.append({
            "id": row[0],
            "title": row[1],
            "start": start_at,
            "allDay": not bool(row[9]),
            "backgroundColor": shade,
            "borderColor": shade,
            "textColor": "#504258"
        })

    # 파스텔 캘린더 스타일
    calendar_css = """
    .fc {
        font-family:inherit;
        color:#594B64;
        background:#FFFCFF;
    }

    .fc .fc-toolbar-title {
        font-size:1.3rem;
        color:#70518B;
        font-weight:700;
    }

    .fc .fc-button-primary {
        background:#F3EBF8 !important;
        border:1px solid #E2D4ED !important;
        color:#765690 !important;
        border-radius:9px !important;
        box-shadow:none !important;
    }

    .fc .fc-button-primary:hover {
        background:#E8DDF3 !important;
    }

    .fc .fc-button-primary.fc-button-active {
        background:#9873B8 !important;
        color:white !important;
    }

    .fc .fc-col-header-cell {
        background:#F9F4FC;
    }

    .fc .fc-col-header-cell-cushion {
        color:#806D90;
        padding:10px 0;
        text-decoration:none;
    }

    .fc .fc-daygrid-day-number {
        color:#61556A;
        text-decoration:none;
        white-space:nowrap !important;
    }

    /* 오늘 날짜 강조 */
    .fc .fc-day-today {
        background:#F0E4FA !important;
    }

    .fc .fc-day-today .fc-daygrid-day-number {
        background:#79559D !important;
        color:white !important;
        border-radius:9px !important;
        padding:4px 9px !important;
        font-weight:700;
        white-space:nowrap !important;
    }

    .fc .fc-event {
        border-radius:6px;
        padding:2px 5px;
        cursor:pointer;
        font-size:.82rem;
    }

    .fc .fc-scrollgrid,
    .fc td,
    .fc th {
        border-color:#EEE7F2 !important;
    }
    """

    # 오늘 날짜 표시
    st.markdown(
        f"**오늘 · {today.strftime('%Y년 %m월 %d일')}**"
    )

    # 캘린더 출력
    cal_state = calendar(
        events=events,
        options={
            "initialView": "dayGridMonth",
            "initialDate": today.isoformat(),
            "locale": "ko",
            "height": 510,
            "fixedWeekCount": False,
            "dayMaxEvents": 3,
            "headerToolbar": {
                "left": "prev,next today",
                "center": "title",
                "right": "dayGridMonth,dayGridWeek,listMonth"
            },
            "buttonText": {
                "today": "오늘",
                "month": "월",
                "week": "주",
                "list": "목록"
            }
        },
        custom_css=calendar_css,
        callbacks=["eventClick"],
        key="aivle_calendar"
    )

    # 캘린더 일정 선택
    if cal_state and cal_state.get("callback") == "eventClick":
        clicked = str(
            cal_state.get("eventClick", {})
            .get("event", {})
            .get("id", "")
        )

        if clicked:
            st.session_state["calendar_selected"] = clicked

    st.caption(
        "날짜가 있는 업무는 캘린더에 표시돼요. "
        "날짜가 없는 업무는 아래에서 지정할 수 있어요."
    )

    selected_event = next(
        (
            row for row in tasks
            if row[0] == st.session_state.get("calendar_selected")
        ),
        None
    )

    if selected_event:
        show_date = selected_event[3] or "기한 미정"
        show_time = selected_event[9] or "시간 미정"

        st.info(
            f"선택한 일정: {selected_event[1]} · "
            f"{show_date} · {show_time} — "
            "아래 업무 카드의 '수정'에서 변경할 수 있어요."
        )

    # To-Do List
    st.markdown("**📋 To-Do List**")

    status_filter = st.radio(
        "표시",
        ["미완료", "완료", "전체"],
        horizontal=True
    )

    visible = [
        row for row in tasks
        if status_filter == "전체"
        or (status_filter == "완료" and row[6])
        or (status_filter == "미완료" and not row[6])
    ]

    visible_ids = [row[0] for row in visible]

    if not visible:
        st.info(
            "표시할 업무가 없어요. "
            "미팅 업무에서 회의록을 분석해 보세요."
        )

    # 업무 목록
    for index, row in enumerate(visible):
        (
            task_id, title, owner, due, description,
            kind, done, priority, _, start_time
        ) = row

        with st.container(border=True):
            left, right = st.columns(
                [8, 2],
                vertical_alignment="center"
            )

            with left:
                checked = st.checkbox(
                    title,
                    value=bool(done),
                    key=f"todo_{task_id}"
                )

                if checked != bool(done):
                    with db_connect() as conn:
                        conn.execute(
                            "UPDATE tasks SET done=? WHERE id=?",
                            (int(checked), task_id)
                        )
                        conn.commit()

                    st.rerun()

                st.caption(
                    f"{owner} · {due or '기한 미정'} · "
                    f"{start_time or '시간 미정'} · "
                    f"{kind} · 우선순위 {priority}"
                )

                if description:
                    st.caption(description)

            with right:
                # 수정 버튼 하나로 업무 관리
                with st.popover(
                    "수정",
                    use_container_width=True
                ):
                    st.markdown("**업무 편집**")

                    with st.form(f"form_{task_id}"):
                        new_title = st.text_input(
                            "업무명",
                            value=title
                        )

                        new_owner = st.text_input(
                            "담당자",
                            value=owner
                        )

                        new_kind = st.selectbox(
                            "종류",
                            ["업무", "일정"],
                            index=0 if kind == "업무" else 1
                        )

                        priorities = ["높음", "보통", "낮음"]

                        new_priority = st.selectbox(
                            "우선순위",
                            priorities,
                            index=(
                                priorities.index(priority)
                                if priority in priorities else 1
                            )
                        )

                        # 날짜 수정
                        no_due = st.checkbox(
                            "기한 미정",
                            value=not bool(due),
                            key=f"no_due_{task_id}"
                        )

                        new_date = st.date_input(
                            "마감일",
                            value=(
                                date.fromisoformat(due)
                                if due else today
                            )
                        )

                        # 시간 수정
                        no_time = st.checkbox(
                            "시간 미정",
                            value=not bool(start_time),
                            key=f"no_time_{task_id}"
                        )

                        new_time = st.time_input(
                            "시작 시간",
                            value=(
                                time.fromisoformat(start_time)
                                if start_time else time(9, 0)
                            )
                        )

                        new_description = st.text_area(
                            "상세 내용",
                            value=description
                        )

                        # 목록 순서
                        new_rank = st.selectbox(
                            "목록 위치",
                            range(1, len(visible) + 1),
                            index=index,
                            format_func=lambda n: f"{n}번째"
                        )

                        if st.form_submit_button(
                            "변경 저장",
                            type="primary",
                            use_container_width=True
                        ):
                            if not new_title.strip():
                                st.warning("업무명을 입력하세요.")

                            else:
                                update_task(
                                    task_id,
                                    new_title,
                                    new_owner,
                                    None if no_due else new_date.isoformat(),
                                    new_description,
                                    new_kind,
                                    new_priority,
                                    (
                                        None
                                        if no_due or no_time
                                        else new_time.strftime("%H:%M")
                                    )
                                )

                                change_order(
                                    task_id,
                                    new_rank - 1,
                                    visible_ids
                                )

                                st.rerun()

                    # 업무 삭제
                    st.divider()

                    confirm = st.checkbox(
                        "삭제 확인",
                        key=f"delete_confirm_{task_id}"
                    )

                    if st.button(
                        "업무 삭제",
                        key=f"delete_{task_id}",
                        disabled=not confirm,
                        use_container_width=True
                    ):
                        delete_task(task_id)
                        st.rerun()

    # 수동 업무 추가
    with st.expander("＋ 업무 직접 추가"):
        with st.form("new_task"):
            new_title = st.text_input("업무명")

            new_owner = st.text_input(
                "담당자",
                value="김대리"
            )

            new_kind = st.selectbox(
                "종류",
                ["업무", "일정"]
            )

            new_priority = st.selectbox(
                "우선순위",
                ["높음", "보통", "낮음"],
                index=1
            )

            new_undecided = st.checkbox(
                "기한 미정",
                value=True,
                key="new_undecided"
            )

            new_date = st.date_input(
                "마감일",
                value=today
            )

            new_no_time = st.checkbox(
                "시간 미정",
                value=True,
                key="new_no_time"
            )

            new_time = st.time_input(
                "시작 시간",
                value=time(9, 0)
            )

            new_description = st.text_area(
                "상세 내용"
            )

            if st.form_submit_button(
                "추가",
                type="primary"
            ):
                if not new_title.strip():
                    st.warning("업무명을 입력하세요.")

                else:
                    save_tasks([{
                        "title": new_title,
                        "owner": new_owner,
                        "kind": new_kind,
                        "priority": new_priority,
                        "due_date": (
                            None if new_undecided
                            else new_date.isoformat()
                        ),
                        "start_time": (
                            None
                            if new_undecided or new_no_time
                            else new_time.strftime("%H:%M")
                        ),
                        "description": new_description
                    }])

                    st.rerun()
