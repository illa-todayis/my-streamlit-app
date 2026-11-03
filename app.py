import csv
import hashlib
import io
import json
import os
import re
import smtplib
import sqlite3
from datetime import date
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
[data-testid="stSidebar"] {background:#F6F0FA;}
h1,h2,h3 {color:#73558D;}
div.stButton > button {border-radius:10px;}
div.stButton > button[kind="primary"] {
    background:#9474B5;
    border:0;
    color:#fff;
}
[data-testid="stAudioInput"] {
    border:2px solid #CAB1DF;
    border-radius:12px;
    padding:12px;
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
그다음 주요 안건·결정사항·향후 계획을 요약하세요.
회의록에 없는 정보와 마감일을 지어내지 마세요."""


# 업무 DB 생성 및 기존 데이터 유지
DB_PATH = os.getenv("AIVLE_DB_PATH", "aivle_tasks.db")

def db_connect():
    conn = sqlite3.connect(DB_PATH, timeout=10)

    conn.execute("""CREATE TABLE IF NOT EXISTS tasks (
        id TEXT PRIMARY KEY,
        title TEXT NOT NULL,
        owner TEXT NOT NULL,
        due_date TEXT,
        description TEXT NOT NULL,
        kind TEXT NOT NULL,
        done INTEGER NOT NULL DEFAULT 0,
        priority TEXT NOT NULL DEFAULT '보통',
        sort_order INTEGER NOT NULL DEFAULT 0
    )""")

    # 기존 DB에 없는 열만 추가
    cols = {
        row[1]
        for row in conn.execute("PRAGMA table_info(tasks)")
    }

    if "priority" not in cols:
        conn.execute(
            "ALTER TABLE tasks ADD COLUMN priority TEXT NOT NULL DEFAULT '보통'"
        )

    if "sort_order" not in cols:
        conn.execute(
            "ALTER TABLE tasks ADD COLUMN sort_order INTEGER NOT NULL DEFAULT 0"
        )
        conn.execute("UPDATE tasks SET sort_order=rowid")

    conn.commit()
    return conn


# 업무 목록 조회
def list_tasks():
    with db_connect() as conn:
        return conn.execute("""
            SELECT id, title, owner, due_date, description,
                   kind, done, priority, sort_order
            FROM tasks
            ORDER BY sort_order, id
        """).fetchall()


# AI 추출 업무 저장
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

            try:
                due = date.fromisoformat(due).isoformat() if due else None
            except (TypeError, ValueError):
                due = None

            if not title:
                continue

            # 동일한 업무의 중복 등록 방지
            exists = conn.execute("""
                SELECT 1 FROM tasks
                WHERE title=? AND owner=? AND due_date IS ?
            """, (title, owner, due)).fetchone()

            if exists:
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
                (id, title, owner, due_date, description,
                 kind, priority, sort_order)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                task_id,
                title,
                owner,
                due,
                task.get("description", ""),
                task.get("kind", "업무"),
                priority,
                next_pos
            ))

            added += cur.rowcount

        conn.commit()

    return added


# 업무 수정
def update_task(task_id, title, owner, due, description, kind, priority):
    with db_connect() as conn:
        conn.execute("""
            UPDATE tasks
            SET title=?, owner=?, due_date=?,
                description=?, kind=?, priority=?
            WHERE id=?
        """, (
            title.strip(),
            owner.strip() or "미지정",
            due,
            description.strip(),
            kind,
            priority,
            task_id
        ))
        conn.commit()


# 업무 삭제
def delete_task(task_id):
    with db_connect() as conn:
        conn.execute("DELETE FROM tasks WHERE id=?", (task_id,))
        conn.commit()


# 업무 목록 순서 변경
def change_order(task_id, destination, visible_ids):
    ordered = [row[0] for row in list_tasks()]

    if task_id not in visible_ids:
        return

    visible = [item for item in ordered if item in visible_ids]
    visible.remove(task_id)
    visible.insert(destination, task_id)

    iterator = iter(visible)

    updated = [
        next(iterator) if item in visible_ids else item
        for item in ordered
    ]

    with db_connect() as conn:
        for position, item in enumerate(updated, 1):
            conn.execute(
                "UPDATE tasks SET sort_order=? WHERE id=?",
                (position, item)
            )
        conn.commit()


# AI 일정 및 업무 추출
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
                        "due_date": {"type": ["string", "null"]},
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
                        "title", "owner", "due_date",
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

담당자가 없으면 '미지정'으로 표시하세요.
날짜가 없거나 불명확하면 null로 반환하세요.
날짜는 확실한 경우만 YYYY-MM-DD로 표기하세요.
회의 기준일이 없는 상대 날짜는 null로 처리하세요.

긴급하거나 중요한 업무는 우선순위 '높음',
일반 업무는 '보통', 단순 후속 업무는 '낮음'으로 추천하세요.

단순 논의를 업무로 만들지 말고 JSON 스키마에 맞춰 반환하세요.
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
    "description": "사용자가 승인한 요약본 이메일을 발송합니다.",
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


# 이메일 발송 함수
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
                row[k]
                for k in ("이메일주소", "이메일", "이메일 주소", "email")
                if k in row
            ),
            ""
        )

        if name and re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
            employees.append((name, dept, email))

    return employees


# 세션 상태
for key, default in {
    "history": [],
    "meeting_result": None,
    "email_sent_key": None,
    "edit_target": None,
    "cal_version": 0
}.items():
    if key not in st.session_state:
        st.session_state[key] = default


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
            st.info("마이크 버튼으로 녹음한 뒤 정지하고 재생해 확인하세요.")

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

    # 이메일 수신자
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

                result = {
                    "meeting_text": meeting_text,
                    "transcript": "",
                    "summary": "",
                    "show_summary": show_summary,
                    "audio": None,
                    "added": None
                }

                # STT
                if use_voice:
                    with st.spinner("음성 인식 중입니다..."):
                        transcript = client.audio.transcriptions.create(
                            model="whisper-1",
                            file=audio_file
                        )

                    result["transcript"] = transcript.text

                if needs_summary:
                    prompt = f"""에이블, 김 대리입니다. 미팅 내용을 분석해 주세요.

[음성 요청]
{result['transcript']}

[미팅 내용]
{meeting_text}
"""

                    # LLM 요약
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

                    # AI 업무 자동 등록
                    if auto_tasks:
                        with st.spinner("일정과 할 일을 추출·등록 중입니다..."):
                            extracted = extract_tasks(meeting_text)
                            result["added"] = save_tasks(extracted)

                    # TTS
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

    # 분석 결과
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
            st.caption(
                "'일정 및 업무' 메뉴에서 확인·수정할 수 있어요."
            )

        if result["audio"]:
            st.subheader("🔊 AI 요약 음성")
            st.audio(result["audio"], format="audio/mp3")

        # 이메일 승인 후 발송
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
                                        "content": "send_email 도구를 호출하세요. 메일은 한 통만 발송합니다."
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
                                st.error("이메일 도구가 호출되지 않았어요.")

                            else:
                                status = send_email(
                                    email.strip(),
                                    "미팅 내용 요약",
                                    result["summary"]
                                )

                                if status["status"] == "success":
                                    st.session_state.email_sent_key = mail_key

                                # 이메일 도구 실행 결과 전달
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
                                    st.success("이메일을 발송했어요.")
                                else:
                                    st.error(status["error"])

                        except Exception as e:
                            st.error(f"이메일 처리 오류: {e}")


# 일정 및 업무
else:
    st.subheader("📅 일정 및 업무")

    tasks = list_tasks()
    unfinished = sum(not row[6] for row in tasks)

    # 업무 현황
    c1, c2, c3 = st.columns(3)
    c1.metric("전체 업무", len(tasks))
    c2.metric("미완료", unfinished)
    c3.metric("완료", len(tasks) - unfinished)

    # 날짜가 있는 업무만 캘린더 일정으로 생성
    dated = [row for row in tasks if row[3]]
    today = date.today()

    # 날짜가 있는 업무 중 가장 가까운 날짜를 기준으로 표시
    nearest_day = min(
        (date.fromisoformat(row[3]) for row in dated),
        key=lambda d: abs((d - today).days),
        default=today
    )

    # 캘린더 일정 데이터
    events = []

    for row in dated:
        if row[6]:
            color = "#DDD7E5"
        elif row[5] == "일정":
            color = "#C2ADDA"
        else:
            color = "#EAC4D5"

        events.append({
            "id": row[0],
            "title": row[1],
            "start": row[3],
            "allDay": True,
            "backgroundColor": color,
            "borderColor": color,
            "textColor": "#4C4057"
        })

    # 파스텔 캘린더 디자인
    calendar_css = """
    .fc {
        font-family: inherit;
        color: #584D63;
        background: #FFFCFF;
    }

    .fc .fc-toolbar-title {
        color: #74538E;
        font-size: 1.35rem;
        font-weight: 700;
    }

    .fc .fc-button-primary {
        background: #F2ECF8 !important;
        border: 1px solid #E6DCEC !important;
        color: #73548F !important;
        border-radius: 9px !important;
        box-shadow: none !important;
    }

    .fc .fc-button-primary:hover {
        background: #E9DEF3 !important;
    }

    .fc .fc-button-primary.fc-button-active {
        background: #9978B8 !important;
        color: #fff !important;
    }

    .fc .fc-col-header-cell {
        background: #FAF5FC;
    }

    .fc .fc-col-header-cell-cushion {
        color: #806F8A;
        text-decoration: none;
        padding: 9px 0;
    }

    .fc .fc-daygrid-day-number {
        color: #61556A;
        text-decoration: none;
        white-space: nowrap !important;
        padding: 7px;
    }

    .fc .fc-day-today {
        background: #F5EDF9 !important;
    }

    .fc .fc-day-today .fc-daygrid-day-number {
        font-weight: 700;
        color: #76559A !important;
    }

    .fc .fc-event {
        border-radius: 6px;
        padding: 2px 5px;
        font-size: .8rem;
        cursor: pointer;
    }

    .fc .fc-scrollgrid,
    .fc td,
    .fc th {
        border-color: #EEE7F2 !important;
    }
    """

    st.caption(
        "일정을 클릭하면 수정할 수 있어요. "
        "날짜가 없는 업무는 아래 목록에서 기한을 지정하세요."
    )

    if dated:
        st.caption(
            f"등록된 날짜 있는 업무 {len(dated)}건 · "
            f"가장 가까운 일정: {nearest_day.isoformat()}"
        )

    # 캘린더 출력
    cal_state = calendar(
        events=events,
        options={
            "initialView": "dayGridMonth",
            "initialDate": nearest_day.isoformat(),
            "locale": "ko",
            "height": 520,
            "fixedWeekCount": False,
            "dayMaxEvents": 3,
            "editable": False,
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
        key=f"aivle_calendar_{st.session_state.cal_version}"
    )

    # 캘린더의 일정을 클릭하면 편집 대상으로 지정
    if cal_state and cal_state.get("callback") == "eventClick":
        clicked_id = str(
            cal_state["eventClick"]["event"].get("id", "")
        )

        if clicked_id:
            st.session_state.edit_target = clicked_id

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
            "표시할 업무가 없어요. 미팅 업무에서 회의록을 분석해 보세요."
        )

    # 업무별 완료 체크, 수정, 순서 변경
    for index, row in enumerate(visible):
        (
            task_id, title, owner, due,
            description, kind, is_done,
            priority, position
        ) = row

        with st.container(border=True):
            left, mid, right = st.columns(
                [7, 2, 2],
                vertical_alignment="center"
            )

            with left:
                checked = st.checkbox(
                    title,
                    value=bool(is_done),
                    key=f"todo_{task_id}"
                )

                if checked != bool(is_done):
                    with db_connect() as conn:
                        conn.execute(
                            "UPDATE tasks SET done=? WHERE id=?",
                            (int(checked), task_id)
                        )
                        conn.commit()

                    st.session_state.cal_version += 1
                    st.rerun()

                st.caption(
                    f"{owner} · {due or '기한 미정'} · "
                    f"{kind} · 우선순위 {priority}"
                )

                if description:
                    st.caption(description)

            with mid:
                if st.button(
                    "수정",
                    key=f"edit_{task_id}",
                    use_container_width=True
                ):
                    st.session_state.edit_target = task_id
                    st.rerun()

            with right:
                rank = st.selectbox(
                    "순서",
                    range(1, len(visible) + 1),
                    index=index,
                    key=f"rank_{task_id}",
                    label_visibility="collapsed"
                )

                if st.button(
                    "이동",
                    key=f"move_{task_id}",
                    use_container_width=True
                ):
                    change_order(
                        task_id,
                        rank - 1,
                        visible_ids
                    )
                    st.rerun()

    # 일정 수정 및 삭제
    selected = next(
        (
            row for row in list_tasks()
            if row[0] == st.session_state.edit_target
        ),
        None
    )

    if selected:
        (
            task_id, title, owner, due,
            description, kind, is_done,
            priority, _
        ) = selected

        st.divider()
        st.subheader("✏️ 업무 수정")

        with st.form(f"edit_form_{task_id}"):
            new_title = st.text_input(
                "업무명",
                value=title
            )

            c1, c2 = st.columns(2)

            new_owner = c1.text_input(
                "담당자",
                value=owner
            )

            new_kind = c2.selectbox(
                "종류",
                ["업무", "일정"],
                index=(
                    ["업무", "일정"].index(kind)
                    if kind in ("업무", "일정")
                    else 0
                )
            )

            c3, c4 = st.columns(2)

            new_priority = c3.selectbox(
                "우선순위",
                ["높음", "보통", "낮음"],
                index=(
                    ["높음", "보통", "낮음"].index(priority)
                    if priority in ("높음", "보통", "낮음")
                    else 1
                )
            )

            no_deadline = c4.checkbox(
                "기한 미정",
                value=due is None
            )

            date_value = st.date_input(
                "마감일 (기한 미정이면 무시)",
                value=(
                    date.fromisoformat(due)
                    if due else date.today()
                )
            )

            new_due = None if no_deadline else date_value

            new_description = st.text_area(
                "상세 내용",
                value=description
            )

            save_clicked = st.form_submit_button(
                "변경 저장",
                type="primary"
            )

            if save_clicked:
                if not new_title.strip():
                    st.warning("업무명을 입력하세요.")

                else:
                    update_task(
                        task_id,
                        new_title,
                        new_owner,
                        new_due.isoformat() if new_due else None,
                        new_description,
                        new_kind,
                        new_priority
                    )

                    st.session_state.edit_target = None
                    st.session_state.cal_version += 1
                    st.rerun()

        # 삭제 전 확인
        if st.checkbox(
            "이 업무 삭제하기",
            key=f"confirm_{task_id}"
        ):
            if st.button(
                "삭제 확인",
                key=f"delete_{task_id}"
            ):
                delete_task(task_id)
                st.session_state.edit_target = None
                st.session_state.cal_version += 1
                st.rerun()

        if st.button("편집 닫기"):
            st.session_state.edit_target = None
            st.rerun()

    # 수동 업무 추가
    with st.expander("＋ 업무 직접 추가"):
        with st.form("new_task"):
            title = st.text_input("업무명")

            c1, c2 = st.columns(2)

            owner = c1.text_input(
                "담당자",
                value="김대리"
            )

            kind = c2.selectbox(
                "종류",
                ["업무", "일정"]
            )

            c3, c4 = st.columns(2)

            priority = c3.selectbox(
                "우선순위",
                ["높음", "보통", "낮음"],
                index=1
            )

            undecided = c4.checkbox(
                "기한 미정",
                value=True,
                key="new_undecided"
            )

            due_input = st.date_input(
                "마감일 (기한 미정이면 무시)",
                value=date.today()
            )

            due = None if undecided else due_input

            description = st.text_area("내용")

            if st.form_submit_button("추가"):
                if title.strip():
                    save_tasks([{
                        "title": title,
                        "owner": owner,
                        "due_date": (
                            due.isoformat() if due else None
                        ),
                        "description": description,
                        "kind": kind,
                        "priority": priority
                    }])

                    st.session_state.cal_version += 1
                    st.rerun()

                else:
                    st.warning("업무명을 입력하세요.")


