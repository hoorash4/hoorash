import os
import smtplib
from email.mime.text import MIMEText

def send_test():
    sender = os.environ.get("EMAIL_USER")
    password = os.environ.get("EMAIL_PASS")
    
    if sender and "," in sender:
        recipients = [email.strip() for email in sender.split(",")]
        sender_email = recipients[0]
    else:
        recipients = [sender]
        sender_email = sender

    print(f"📧 발신 테스트 계정: {sender_email}")
    print(f"📬 수신 대상: {recipients}")

    msg = MIMEText("윤슬아! 아웃룩 SMTP 이메일 알림 연동이 완벽하게 성공했어! 🎉\n나중에 인스턴스가 잡히면 이 메일함으로 바로 성공 알림이 올 거야.")
    msg['Subject'] = "🧪 [테스트] OCI 이메일 알림 연동 테스트"
    msg['From'] = sender_email
    msg['To'] = ", ".join(recipients)

    try:
        # 아웃룩 SMTP 서버 설정
        smtp_server = "smtp.gmail.com" if "gmail" in sender_email else "smtp-mail.outlook.com"
        
        server = smtplib.SMTP(smtp_server, 587)
        server.starttls()
        server.login(sender_email, password)
        server.sendmail(sender_email, recipients, msg.as_string())
        server.quit()
        print("✅ 테스트 이메일 발송 성공!")
    except Exception as e:
        print(f"❌ 이메일 발송 실패: {e}")
        exit(1)

if __name__ == "__main__":
    send_test()
