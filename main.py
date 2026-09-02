import os
import sys
import smtplib
from email.mime.text import MIMEText
import oci

def send_notification(subject, body):
    sender = os.environ.get("EMAIL_USER")
    password = os.environ.get("EMAIL_PASS")
    
    if sender and "," in sender:
        recipients = [email.strip() for email in sender.split(",")]
        sender_email = recipients[0]
    else:
        recipients = [sender]
        sender_email = sender

    if not sender_email or not password:
        print("⚠️ 이메일 환경변수가 설정되지 않아 알림 발송을 스킵합니다.")
        return

    msg = MIMEText(body)
    msg['Subject'] = subject
    msg['From'] = sender_email
    msg['To'] = ", ".join(recipients)

    try:
        smtp_server = "smtp.gmail.com" if "gmail" in sender_email else "smtp-mail.outlook.com"
        
        server = smtplib.SMTP(smtp_server, 587)
        server.starttls()
        server.login(sender_email, password)
        server.sendmail(sender_email, recipients, msg.as_string())
        server.quit()
        print("📧 이메일 알림 발송 완료!")
    except Exception as e:
        print(f"❌ 이메일 발송 실패: {e}")

def main():
    config = {
        "user": os.environ.get("OCI_USER_OCID"),
        "fingerprint": os.environ.get("OCI_FINGERPRINT"),
        "key_content": os.environ.get("OCI_KEY_CONTENT"),
        "tenancy": os.environ.get("OCI_TENANCY_OCID"),
        "region": os.environ.get("OCI_REGION", "ap-singapore-1")
    }

    try:
        core_client = oci.core.ComputeClient(config)
        identity_client = oci.identity.IdentityClient(config)
        
        compartment_id = os.environ.get("OCI_COMPARTMENT_OCID") or config["tenancy"]
        subnet_id = os.environ.get("OCI_SUBNET_OCID")
        ssh_public_key = os.environ.get("OCI_SSH_PUBLIC_KEY")

        instances = core_client.list_instances(compartment_id=compartment_id).data
        for inst in instances:
            if inst.display_name == "macrowatch" and inst.lifecycle_state not in ["TERMINATED", "TERMINATING"]:
                print("🎉 'macrowatch' 인스턴스가 이미 존재하고 실행 중입니다.")
                sys.exit(0)

        images = core_client.list_images(
            compartment_id=compartment_id,
            operating_system="Canonical Ubuntu",
            shape="VM.Standard.A1.Flex"
        ).data

        aarch64_images = [img for img in images if "aarch64" in img.display_name.lower() and "26.04" in img.display_name]
        
        if not aarch64_images:
            aarch64_images = [img for img in images if "aarch64" in img.display_name.lower()]

        if not aarch64_images:
            print("❌ 적합한 Ubuntu aarch64 이미지를 찾을 수 없습니다.")
            sys.exit(1)

        target_image = sorted(aarch64_images, key=lambda x: x.time_created, reverse=True)[0]
        print(f"✅ Ubuntu 이미지 발견: {target_image.display_name}")

        ads = identity_client.list_availability_domains(compartment_id=config["tenancy"]).data

        for ad in ads:
            print(f"🚀 [{ad.name}] 'macrowatch' 인스턴스 생성 시도 중...")
            
            launch_details = oci.core.models.LaunchInstanceDetails(
                compartment_id=compartment_id,
                availability_domain=ad.name,
                display_name="macrowatch",
                shape="VM.Standard.A1.Flex",
                shape_config=oci.core.models.LaunchInstanceShapeConfigDetails(
                    ocpus=1.0,          # ✅ 1 OCPU (화면 표기 기본값)
                    memory_in_gbs=6.0   # ✅ 6 GB RAM (화면 표기 기본값)
                ),
                image_id=target_image.id,
                create_vnic_details=oci.core.models.CreateVnicDetails(
                    subnet_id=subnet_id,
                    assign_public_ip=True
                ),
                metadata={
                    "ssh_authorized_keys": ssh_public_key
                }
            )

            try:
                response = core_client.launch_instance(launch_details)
                instance = response.data
                print(f"🎉 성공! 인스턴스 생성됨: {instance.id}")
                
                send_notification(
                    "🎉 [OCI] macrowatch 인스턴스 생성 성공!",
                    f"축하합니다 윤슬아!\n\nOCI Ampere A1 (1 OCPU / 6GB) 'macrowatch' 인스턴스가 성공적으로 생성되었습니다.\n\n"
                    f"인스턴스 ID: {instance.id}\n"
                    f"가용 도메인: {ad.name}"
                )
                sys.exit(0)

            except oci.exceptions.ServiceError as e:
                if e.status == 500 or "Out of capacity" in str(e) or "LimitExceeded" in str(e):
                    print(f"❌ 자원 부족 (Out of Capacity). 다음 스케줄에 자동으로 재시도합니다.")
                else:
                    print(f"⚠️ 에러 발생 [{ad.name}]: {e.message}")

        sys.exit(1)

    except Exception as e:
        print(f"💥 스크립트 실행 중 예외 발생: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
