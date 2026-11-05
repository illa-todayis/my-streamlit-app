"""여러 수신자에게 각각 별도 메일을 발송하고 수신자별 결과를 반환합니다."""
import re
import smtplib
import ssl
from email.message import EmailMessage

from config import get_setting

MAX_RECIPIENTS = 10
EMAIL_PATTERN = re.compile(r'^[^@\s,;]+@[^@\s,;]+\.[^@\s,;]+$')


def valid_recipient(address):
    return bool(EMAIL_PATTERN.fullmatch((address or '').strip()))


def parse_recipients(raw):
    """쉼표/세미콜론/줄바꿈으로 나눈 이메일을 검증·중복 제거합니다."""
    addresses = [a.strip() for a in re.split(r'[,;\n\r]+', raw or '') if a.strip()]
    unique = list(dict.fromkeys(addresses))
    if not unique:
        raise ValueError('수신자 이메일을 한 개 이상 입력해 주세요.')
    if len(unique) > MAX_RECIPIENTS:
        raise ValueError(f'한 번에 최대 {MAX_RECIPIENTS}개 주소까지 발송할 수 있습니다.')
    invalid = [a for a in unique if not valid_recipient(a)]
    if invalid:
        # 사용자에게는 주소를 다시 확인하도록 안내; 비밀번호 등 출력 금지
        raise ValueError('잘못된 이메일 주소가 있습니다: ' + ', '.join(invalid))
    return unique


def send_emails(recipients, subject, body):
    """수신자별 개별 메일 발송. Bcc나 수신자 목록을 서로 노출하지 않습니다.

    결과: [{'to': ..., 'status': 'success'|'failed', 'error': ...}, ...]
    SMTP 오류에도 나머지 주소 전송을 계속 시도합니다.
    """
    recipients = parse_recipients(','.join(recipients) if isinstance(recipients, (list, tuple)) else recipients)
    if not subject.strip() or not body.strip():
        raise ValueError('이메일 제목과 본문을 입력해 주세요.')
    sender = (get_setting('GMAIL_ADDRESS') or '').strip()
    password = ''.join((get_setting('GMAIL_APP_PASSWORD') or '').split())
    if not sender or not password:
        return [{'to': r, 'status': 'failed', 'error': 'Gmail 발신자 주소 또는 앱 비밀번호가 설정되지 않았습니다.'} for r in recipients]
    results = []
    try:
        with smtplib.SMTP('smtp.gmail.com', 587, timeout=25) as smtp:
            smtp.ehlo()
            smtp.starttls(context=ssl.create_default_context())
            smtp.ehlo()
            smtp.login(sender, password)
            for to in recipients:
                msg = EmailMessage()
                msg['From'] = sender
                msg['To'] = to
                msg['Subject'] = subject
                msg.set_content(body)
                try:
                    smtp.send_message(msg, from_addr=sender, to_addrs=[to])
                    results.append({'to': to, 'status': 'success', 'error': ''})
                except smtplib.SMTPRecipientsRefused as exc:
                    codes = [str(val[0]) for val in exc.recipients.values()]
                    results.append({'to': to, 'status': 'failed', 'error': '수신자 거부 (SMTP ' + ', '.join(codes) + ')'})
                except smtplib.SMTPException as exc:
                    results.append({'to': to, 'status': 'failed', 'error': type(exc).__name__})
    except smtplib.SMTPAuthenticationError:
        return [{'to': r, 'status': 'failed', 'error': 'Gmail 인증 실패: Secrets의 계정/앱 비밀번호 확인'} for r in recipients]
    except (smtplib.SMTPException, OSError) as exc:
        failed = {x['to'] for x in results}
        results.extend({'to': r, 'status': 'failed', 'error': 'SMTP 연결 실패 ('+type(exc).__name__+')'} for r in recipients if r not in failed)
    return results


def send_email(to, subject, body):
    """기존 단일 발송 호출과의 호환성을 유지합니다."""
    try:
        result = send_emails([to], subject, body)[0]
    except ValueError as exc:
        return {'status': 'failed', 'error': str(exc)}
    return {'status': result['status'], 'error': result['error'],
            'message': 'Gmail 서버에 접수되었습니다.' if result['status'] == 'success' else ''}
