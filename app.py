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
st.markdown("""
<style>
.stApp {background:#FFFBFF;}
[data-testid="stSidebar"] {background:#F6EFFB;}
h1,h2,h3 {color:#79539A;}
div.stButton > button {border-radius:12px;}
div.stButton > button[kind="primary"] {background:#9871BA;border:0;color:white;}
[data-testid="stAudioInput"] {border:2px solid #CBA8E0;border-radius:14px;padding:12px;}
</style>
""", unsafe_allow_html=True)
client = OpenAI()

# 역할 부여
sys_role = """당신은 마케팅팀 김대리의 AI 개인비서 '에이블'입니다.
사용자의 업무 요청에 정확하고 친절하게 답변합니다."""
meeting_role = sys_role + """
회의록을 분석할 때 김 대리의 담당 업무를 먼저 보고하고,
그다음 주요 안건·결정사항·향후 계획을 요약하세요.
회의록에 없는 정보와 마감일을 지어내지 마세요."""

# 데이터 저장
DB_PATH = os.getenv("AIVLE_DB_PATH", "aivle_tasks.db")
def db_connect():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.execute("""CREATE TABLE IF NOT EXISTS tasks (
        id TEXT PRIMARY KEY, title TEXT NOT NULL, owner TEXT NOT NULL,
        due_date TEXT, description TEXT NOT NULL, kind TEXT NOT NULL,
        done INTEGER NOT NULL DEFAULT 0
    )""")
    conn.commit()
    return conn

def list_tasks():
    with db_connect() as conn:
        return conn.execute("""SELECT id,title,owner,due_date,description,kind,done
                               FROM tasks ORDER BY done, due_date IS NULL, due_date, title""").fetchall()

def save_tasks(tasks):
    added = 0
    with db_connect() as conn:
        for task in tasks:
            title = task["title"].strip()
            owner = task["owner"].strip() or "미지정"
            due = task["due_date"]
            if due:
                try:
                    due = date.fromisoformat(due).isoformat()
                except ValueError:
                    due = None
            if not title:
                continue
            # 동일 업무·담당자·날짜의 중복 등록 방지
            task_id = hashlib.sha256(f"{title}|{owner}|{due}".encode()).hexdigest()[:20]
            cur = conn.execute("""INSERT OR IGNORE INTO tasks
                (id,title,owner,due_date,description,kind) VALUES (?,?,?,?,?,?)""",
                (task_id,title,owner,due,task["description"],task["kind"]))
            added += cur.rowcount
        conn.commit()
    return added

def extract_tasks(meeting_text):
    # 교안의 Responses API + JSON Schema를 업무 추출에 활용
    schema = {"type":"object", "properties": {"tasks": {
        "type":"array", "items": {"type":"object", "properties": {
            "title":{"type":"string"}, "owner":{"type":"string"},
            "due_date":{"type":["string","null"]},
            "description":{"type":"string"},
            "kind":{"type":"string","enum":["업무","일정"]}
        }, "required":["title","owner","due_date","description","kind"],
        "additionalProperties":False}
    }}, "required":["tasks"], "additionalProperties":False}
    response = client.responses.create(
        model="gpt-4o-mini",
        input=[
            {"role":"system", "content": """회의록에 명시된 구체적인 업무·일정만 추출하세요.
담당자가 없으면 '미지정', 날짜가 없거나 확실하지 않으면 null로 반환하세요.
날짜는 명확한 경우에만 YYYY-MM-DD로 표기하세요.
상대적인 날짜는 회의 기준일이 명시되어 있지 않으면 null로 처리하세요.
단순 논의는 업무로 만들지 말고 반드시 JSON 스키마에 맞춰 반환하세요."""},
            {"role":"user", "content": meeting_text}
        ],
        text={"format":{"type":"json_schema","name":"meeting_tasks",
                        "strict":True,"schema":schema}}
    )
    return json.loads(response.output_text)["tasks"]

# 이메일 및 직원 목록
email_tools = [{"type":"function","name":"send_email",
    "description":"승인한 요약본 이메일 전송",
    "parameters":{"type":"object","properties":{
        "to":{"type":"string"},"subject":{"type":"string"},"body":{"type":"string"}},
        "required":["to","subject","body"],"additionalProperties":False},"strict":True}]

def send_email(to, subject, body):
    sender, password = os.getenv("GMAIL_ADDRESS"), os.getenv("GMAIL_APP_PASSWORD")
    if not sender or not password:
        return {"status":"failed","error":"Gmail 환경변수가 없습니다."}
    msg = MIMEText(body, "plain", "utf-8")
    msg["From"], msg["To"], msg["Subject"] = sender, to, subject
    try:
        with smtplib.SMTP("smtp.gmail.com", 587, timeout=20) as server:
            server.starttls()
            server.login(sender, password)
            server.sendmail(sender, to, msg.as_string())
        return {"status":"success"}
    except Exception as e:
        return {"status":"failed","error":str(e)}

def employee_options(file):
    content = file.getvalue()
    try:
        raw = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        raw = content.decode("cp949")
    reader = csv.DictReader(io.StringIO(raw))
    employees = []
    for row in reader:
        row = {k.strip(): (v or "").strip() for k, v in row.items() if k}
        name = next((row[k] for k in ("사원","사원명","이름") if k in row), "")
        dept = next((row[k] for k in ("부서","부서명") if k in row), "")
        email = next((row[k] for k in ("이메일주소","이메일","이메일 주소","email") if k in row), "")
        if name and re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
            employees.append((name,dept,email))
    return employees

# 세션 상태
if "history" not in st.session_state:
    st.session_state.history = []
if "meeting_result" not in st.session_state:
    st.session_state.meeting_result = None
if "email_sent_key" not in st.session_state:
    st.session_state.email_sent_key = None

# 사이드바 메뉴
with st.sidebar:
    st.title("🪄 에이블")
    menu = st.radio("메뉴", ["💬 일반 채팅", "📄 미팅 업무", "📅 일정 및 업무"],
                    label_visibility="collapsed")
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
        messages = [{"role":"system","content":sys_role}]
        for item in st.session_state.history:
            messages.extend([{"role":"user","content":item["question"]},
                             {"role":"assistant","content":item["answer"]}])
        messages.append({"role":"user","content":prompt})
        with st.spinner("답변 중입니다..."):
            response = client.responses.create(model="gpt-4o-mini",input=messages)
        st.session_state.history.append({"question":prompt,"answer":response.output_text})
        st.session_state.history = st.session_state.history[-5:]
        st.rerun()
    if st.session_state.history and st.button("대화 초기화"):
        st.session_state.history = []
        st.rerun()

# 미팅 업무
elif menu == "📄 미팅 업무":
    st.subheader("📄 미팅 업무")
    uploaded_file = st.file_uploader("회의록 TXT",type=["txt"])
    st.markdown("**필요한 기능**")
    c1,c2 = st.columns(2)
    with c1:
        show_summary = st.checkbox("회의록 요약",value=True)
        use_voice = st.checkbox("음성 요청 인식")
        auto_tasks = st.checkbox("AI 일정·할 일 자동 등록",value=True)
    with c2:
        use_tts = st.checkbox("요약 음성 듣기")
        use_email = st.checkbox("요약본 이메일 보내기")

    audio_file = None
    if use_voice:
        st.markdown("**🎙️ 음성 요청**")
        voice_type = st.radio("음성 입력",["직접 녹음","파일 업로드"],horizontal=True)
        if voice_type == "직접 녹음":
            st.info("마이크 버튼을 눌러 녹음하고 정지한 뒤 재생해 확인하세요.")
            audio_file = st.audio_input("🎤 녹음",sample_rate=16000)
        else:
            audio_file = st.file_uploader("음성 파일",type=["m4a","mp3","wav"])
        if audio_file is not None:
            st.audio(audio_file)

    email = ""
    if use_email:
        st.markdown("**✉️ 요약본 수신자**")
        method = st.radio("수신자 선택",["나에게 보내기","직원 선택","직접 입력"],horizontal=True)
        if method == "나에게 보내기":
            email = "moonstar7577@naver.com"
            st.caption(email)
        elif method == "직원 선택":
            csv_file = st.file_uploader("직원 CSV",type=["csv"])
            if csv_file:
                try:
                    employees = employee_options(csv_file)
                    if employees:
                        selected = st.selectbox("받는 직원", employees,
                            format_func=lambda x:f"{x[0]} · {x[1]} ({x[2]})")
                        email = selected[2]
                    else:
                        st.warning("CSV에서 올바른 직원 이메일을 찾지 못했어요.")
                except (UnicodeError, csv.Error) as e:
                    st.error(f"CSV 읽기 오류: {e}")
        else:
            email = st.text_input("받는 이메일",placeholder="example@gmail.com")

    if st.button("실행",type="primary",use_container_width=True):
        needs_summary = show_summary or use_tts or use_email or auto_tasks
        if not any((show_summary,use_voice,use_tts,use_email,auto_tasks)):
            st.warning("기능을 선택하세요.")
        elif needs_summary and uploaded_file is None:
            st.warning("회의록을 업로드하세요.")
        elif use_voice and audio_file is None:
            st.warning("음성을 녹음하거나 업로드하세요.")
        elif use_email and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+",email.strip()):
            st.warning("받는 이메일을 확인하세요.")
        else:
            try:
                meeting_text = uploaded_file.getvalue().decode("utf-8-sig") if uploaded_file else ""
                if needs_summary and not meeting_text.strip():
                    st.warning("회의록 내용이 비어 있습니다.")
                    st.stop()
                result = {"meeting_text":meeting_text,"transcript":"","summary":"",
                          "show_summary":show_summary,"audio":None,"added":None,"email_enabled":use_email}
                if use_voice:
                    with st.spinner("음성 인식 중입니다..."):
                        transcript = client.audio.transcriptions.create(model="whisper-1",file=audio_file)
                    result["transcript"] = transcript.text
                if needs_summary:
                    prompt = f"""에이블, 김 대리입니다. 미팅 내용을 분석해 주세요.
[음성 요청]\n{result['transcript']}\n[미팅 내용]\n{meeting_text}"""
                    with st.spinner("회의록 요약 중입니다..."):
                        response = client.responses.create(model="gpt-4o-mini",input=[
                            {"role":"system","content":meeting_role},
                            {"role":"user","content":prompt}])
                    result["summary"] = response.output_text
                    if auto_tasks:
                        with st.spinner("일정과 할 일을 추출·등록 중입니다..."):
                            tasks = extract_tasks(meeting_text)
                            result["added"] = save_tasks(tasks)
                    if use_tts:
                        with st.spinner("요약 음성 생성 중입니다..."):
                            speech_response = client.audio.speech.create(
                                model="gpt-4o-mini-tts",voice="nova",input=result["summary"])
                        result["audio"] = speech_response.content
                st.session_state.meeting_result = result
                st.session_state.email_sent_key = None
            except (UnicodeDecodeError, ValueError, json.JSONDecodeError) as e:
                st.error(f"파일 또는 분석 결과를 확인하세요: {e}")
            except Exception as e:
                st.error(f"처리 중 오류가 발생했어요: {e}")

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
            st.success(f"일정 및 할 일 {result['added']}건 신규 등록 (중복은 제외)")
            st.caption("등록된 항목은 '일정 및 업무' 메뉴에서 확인할 수 있어요.")
        if result["audio"]:
            st.subheader("🔊 AI 요약 음성")
            st.audio(result["audio"],format="audio/mp3")
        if use_email and result["summary"]:
            st.markdown("**✉️ 이메일 발송 확인**")
            if re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+",email.strip()):
                st.write(f"받는 사람: **{email}**")
                with st.expander("이메일 본문 미리보기"):
                    st.write(result["summary"])
                mail_key = hashlib.sha256((email+result["summary"]).encode()).hexdigest()
                if st.session_state.email_sent_key == mail_key:
                    st.success("이 요약본은 전송 완료했어요.")
                elif st.button("보내기",type="primary"):
                    # 교안의 Function Calling 흐름을 유지하고 실제 전송은 한 번만 실행
                    with st.spinner("이메일 발송 중입니다..."):
                        try:
                            mail_response = client.responses.create(
                                model="gpt-4o-mini",input=[
                                    {"role":"system","content":"send_email 도구를 호출하세요. 메일은 한 통만 발송합니다."},
                                    {"role":"user","content":f"받는 사람: {email}\n제목: 미팅 내용 요약\n본문:\n{result['summary']}"}],
                                tools=email_tools,tool_choice={"type":"function","name":"send_email"})
                            calls = [x for x in mail_response.output if x.type == "function_call" and x.name == "send_email"]
                            if not calls:
                                st.error("이메일 도구가 호출되지 않았어요.")
                            else:
                                status = send_email(email.strip(),"미팅 내용 요약",result["summary"])
                                client.responses.create(model="gpt-4o-mini",previous_response_id=mail_response.id,
                                    input=[{"type":"function_call_output","call_id":calls[0].call_id,
                                            "output":json.dumps(status,ensure_ascii=False)}])
                                if status["status"] == "success":
                                    st.session_state.email_sent_key = mail_key
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
    done = len(tasks)-unfinished
    c1,c2,c3 = st.columns(3)
    c1.metric("전체 업무",len(tasks))
    c2.metric("미완료",unfinished)
    c3.metric("완료",done)

    events = [{"title":row[1],"start":row[3],"allDay":True,
               "color":"#B8A4C9" if row[6] else "#9065B6"}
              for row in tasks if row[3]]
    calendar(events=events,options={"initialView":"dayGridMonth",
        "locale":"ko","height":560,
        "headerToolbar":{"left":"prev,next today","center":"title",
                         "right":"dayGridMonth,timeGridWeek,listMonth"}},
        key="aivle_calendar")
    st.caption("날짜가 확정되지 않은 업무는 캘린더가 아닌 아래 목록에 표시돼요.")
    st.markdown("**📋 To-Do List**")
    status_filter = st.radio("표시",["전체","미완료","완료"],horizontal=True)
    shown = [row for row in tasks if status_filter=="전체" or
             (status_filter=="완료" and row[6]) or
             (status_filter=="미완료" and not row[6])]
    if not shown:
        st.info("표시할 업무가 없어요. 미팅 업무에서 회의록을 분석해 보세요.")
    for task_id,title,owner,due,description,kind,is_done in shown:
        checked = st.checkbox(f"{title} · {owner} · {due or '기한 미정'}",
                              value=bool(is_done),key=f"todo_{task_id}")
        if checked != bool(is_done):
            with db_connect() as conn:
                conn.execute("UPDATE tasks SET done=? WHERE id=?",(int(checked),task_id))
                conn.commit()
            st.rerun()
        if description:
            st.caption(f"{kind} · {description}")
    if tasks:
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["업무","담당자","기한","설명","유형","완료"])
        for row in tasks:
            writer.writerow([row[1],row[2],row[3] or "",row[4],row[5],"완료" if row[6] else "미완료"])
        st.download_button("업무 목록 CSV 저장",output.getvalue().encode("utf-8-sig"),
                           file_name="aivle_tasks.csv",mime="text/csv")
