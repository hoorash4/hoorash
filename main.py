import os
import sys
import smtplib
from email.mime.text import MIMEText
import oci

# --- 이메일 발송 함수 ---
def send_success_email(instance_id):
    sender = os.environ.get("EMAIL_USER")
    password = os.environ.get("EMAIL_PASS")
    
    if not sender or not password:
        print("⚠️ EMAIL_USER 또는 EMAIL_PASS 시크릿이 설정되지 않아 이메일 알림을 건너뜁니다.")
        return

    subject = "🎉 [OCI] macrowatch 인스턴스 생성 성공!"
    body = (
        f"안녕하세요, 윤슬님!\n\n"
        f"요청하신 Oracle Cloud 인스턴스 'macrowatch'가 성공적으로 생성되었습니다.\n\n"
        f"- Instance ID: {instance_id}\n"
        f"- Region: {os.environ.get('OCI_REGION')}\n\n"
        f"이제 깃허브 액션 시도를 중단하셔도 됩니다!"
    )

    msg = MIMEText(body)
    msg['Subject'] = subject
    msg['From'] = sender
    msg['To'] = sender

    # 아웃룩 및 지메일 겸용 자동 감지 발송
    try:
        if "@outlook" in sender.lower() or "@hotmail" in sender.lower():
            # Outlook / Hotmail 설정
            with smtplib.SMTP("smtp-mail.outlook.com", 587) as server:
                server.starttls()
                server.login(sender, password)
                server.sendmail(sender, sender, msg.as_string())
        else:
            # Gmail / 기타 기본 SSL 설정
            with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
                server.login(sender, password)
                server.sendmail(sender, sender, msg.as_string())
        print("📧 성공 알림 이메일 발송 완료!")
    except Exception as e:
        print(f"⚠️ 이메일 발송 실패: {e}")

# --- 메인 실행 함수 ---
def main():
    user_ocid = os.environ.get("OCI_USER_OCID")
    tenancy_ocid = os.environ.get("OCI_TENANCY_OCID")
    fingerprint = os.environ.get("OCI_FINGERPRINT")
    region = os.environ.get("OCI_REGION")
    key_content = os.environ.get("OCI_KEY_CONTENT")
    subnet_id = os.environ.get("OCI_SUBNET_ID")

    config = {
        "user": user_ocid,
        "key_content": key_content,
        "fingerprint": fingerprint,
        "tenancy": tenancy_ocid,
        "region": region
    }

    try:
        compute_client = oci.core.ComputeClient(config)
        identity_client = oci.identity.IdentityClient(config)
    except Exception as e:
        print(f"❌ OCI 인증 설정 실패: {e}")
        sys.exit(1)

    # 1. 이미 'macrowatch' 인스턴스가 존재하는지 체크 (있으면 바로 종료)
    try:
        instances = compute_client.list_instances(compartment_id=tenancy_ocid).data
        for inst in instances:
            if inst.display_name == "macrowatch" and inst.lifecycle_state in ["RUNNING", "PROVISIONING"]:
                print("✅ 'macrowatch' 인스턴스가 이미 존재하고 실행 중입니다. 작업을 종료합니다.")
                sys.exit(0)
    except Exception as e:
        print(f"⚠️ 기존 인스턴스 조회 실패 (계속 진행): {e}")

    # 2. Ubuntu 26.04 이미지 탐색
    image_id = None
    try:
        images = compute_client.list_images(
            compartment_id=tenancy_ocid,
            operating_system="Canonical Ubuntu",
            shape="VM.Standard.A1.Flex"
        ).data
        
        for img in images:
            if "26.04" in img.display_name:
                image_id = img.id
                print(f"✅ Ubuntu 26.04 이미지 발견: {img.display_name}")
                break
    except Exception as e:
        print(f"⚠️ 이미지 조회 실패: {e}")

    if not image_id:
        print("❌ Ubuntu 26.04 이미지를 찾지 못해 시도를 중단합니다.")
        sys.exit(1)

    # 3. Availability Domain 탐색
    try:
        ads = identity_client.list_availability_domains(compartment_id=tenancy_ocid).data
        ad_name = ads[0].name
    except Exception as e:
        print(f"❌ AD 조회 실패: {e}")
        sys.exit(1)

    # 4. 인스턴스 생성 요청 상세 설정
    launch_details = oci.core.models.LaunchInstanceDetails(
        compartment_id=tenancy_ocid,
        availability_domain=ad_name,
        display_name="macrowatch",
        shape="VM.Standard.A1.Flex",
        shape_config=oci.core.models.LaunchInstanceShapeConfigDetails(
            ocpus=4.0,
            memory_in_gbs=24.0
        ),
        source_details=oci.core.models.InstanceSourceViaImageDetails(
            image_id=image_id
        ),
        create_vnic_details=oci.core.models.CreateVnicDetails(
            subnet_id=subnet_id,
            assign_public_ip=True
        )
    )

    # 5. 인스턴스 생성 시도
    try:
        print(f"🚀 [{region} / {ad_name}] 'macrowatch' 인스턴스 생성 시도 중...")
        response = compute_client.launch_instance(launch_details)
        instance_id = response.data.id
        print("🎉🎉 축하합니다! 'macrowatch' 인스턴스 생성 성공! ID:", instance_id)
        
        # 성공 시 이메일 발송
        send_success_email(instance_id)
        sys.exit(0)

    except oci.exceptions.ServiceError as e:
        if e.status == 500 or "Out of capacity" in str(e) or "Capacity" in str(e):
            print("❌ 자원 부족 (Out of Capacity). 다음 스케줄에 자동으로 재시도합니다.")
            sys.exit(0)
        else:
            print(f"❌ OCI 서비스 에러 발생: {e}")
            sys.exit(1)

if __name__ == "__main__":
    main()
