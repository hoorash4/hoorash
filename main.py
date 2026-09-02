import os
import sys
import smtplib
from email.mime.text import MIMEText

import oci


INSTANCE_NAME = "macrowatch"
SHAPE = "VM.Standard.A1.Flex"

OCPUS = 1.0
MEMORY_GB = 6.0

EMAIL_TO = "hoorash@outlook.kr"


def send_notification(subject, body):
    sender_email = os.environ.get("EMAIL_USER")
    password = os.environ.get("EMAIL_PASS")

    if not sender_email or not password:
        print("⚠️ EMAIL_USER 또는 EMAIL_PASS가 없어 이메일 발송을 건너뜁니다.")
        return

    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = sender_email
    msg["To"] = EMAIL_TO

    try:
        sender_lower = sender_email.lower()

        if "gmail.com" in sender_lower:
            smtp_server = "smtp.gmail.com"
        elif (
            "outlook.com" in sender_lower
            or "outlook.kr" in sender_lower
            or "hotmail.com" in sender_lower
            or "live.com" in sender_lower
        ):
            smtp_server = "smtp-mail.outlook.com"
        else:
            print(
                f"⚠️ 알 수 없는 이메일 서비스입니다: {sender_email}\n"
                "이메일 발송을 건너뜁니다."
            )
            return

        with smtplib.SMTP(smtp_server, 587, timeout=30) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(sender_email, password)
            server.sendmail(
                sender_email,
                [EMAIL_TO],
                msg.as_string()
            )

        print(f"📧 성공 알림 이메일 발송 완료: {EMAIL_TO}")

    except Exception as e:
        print(f"⚠️ 이메일 발송 실패: {e}")


def get_required_env(name):
    value = os.environ.get(name)

    if value is None or not value.strip():
        print(f"❌ 필수 환경변수 누락: {name}")
        sys.exit(1)

    return value.strip()


def main():
    print("==================================================")
    print("OCI macrowatch Auto Runner 시작")
    print("==================================================")

    # --------------------------------------------------
    # GitHub Secrets
    # --------------------------------------------------

    user_ocid = get_required_env("OCI_USER_OCID")
    fingerprint = get_required_env("OCI_FINGERPRINT")
    tenancy_ocid = get_required_env("OCI_TENANCY_OCID")
    subnet_id = get_required_env("OCI_SUBNET_OCID")
    ssh_public_key = get_required_env("OCI_SSH_PUBLIC_KEY")

    region = os.environ.get(
        "OCI_REGION",
        "ap-singapore-1"
    ).strip()

    key_content = get_required_env("OCI_KEY_CONTENT")

    # GitHub Secret에 \n이 문자 그대로 저장된 경우에도 처리
    key_content = key_content.replace("\\n", "\n")

    config = {
        "user": user_ocid,
        "fingerprint": fingerprint,
        "key_content": key_content,
        "tenancy": tenancy_ocid,
        "region": region
    }

    compartment_id = (
        os.environ.get("OCI_COMPARTMENT_OCID")
        or tenancy_ocid
    )

    try:
        # OCI config 형식 검사
        oci.config.validate_config(config)

        core_client = oci.core.ComputeClient(config)
        identity_client = oci.identity.IdentityClient(config)

        print(f"🌏 OCI Region: {region}")

        # --------------------------------------------------
        # 기존 인스턴스 확인
        # --------------------------------------------------

        print("🔎 기존 macrowatch 인스턴스 확인 중...")

        instances = oci.pagination.list_call_get_all_results(
            core_client.list_instances,
            compartment_id=compartment_id
        ).data

        for instance in instances:

            if (
                instance.display_name == INSTANCE_NAME
                and instance.lifecycle_state
                not in ["TERMINATED", "TERMINATING"]
            ):
                print(
                    f"✅ '{INSTANCE_NAME}' 인스턴스가 이미 존재합니다."
                )
                print(
                    f"상태: {instance.lifecycle_state}"
                )
                print(
                    f"OCID: {instance.id}"
                )

                # 이미 있으면 추가 생성 방지
                sys.exit(0)

        # --------------------------------------------------
        # Ubuntu ARM 이미지 찾기
        # --------------------------------------------------

        print("🔎 Ubuntu ARM 이미지 검색 중...")

        images = oci.pagination.list_call_get_all_results(
            core_client.list_images,
            compartment_id=compartment_id,
            operating_system="Canonical Ubuntu",
            shape=SHAPE
        ).data

        if not images:
            print("❌ VM.Standard.A1.Flex용 Ubuntu 이미지를 찾지 못했습니다.")
            sys.exit(1)

        # ARM / aarch64 이미지 우선
        arm_images = [
            image
            for image in images
            if (
                "aarch64" in image.display_name.lower()
                or "arm" in image.display_name.lower()
            )
        ]

        if not arm_images:
            print("❌ ARM64 Ubuntu 이미지를 찾지 못했습니다.")
            sys.exit(1)

        # 최신 이미지 선택
        arm_images.sort(
            key=lambda x: x.time_created,
            reverse=True
        )

        target_image = arm_images[0]

        print("✅ 사용할 이미지:")
        print(target_image.display_name)
        print(target_image.id)

        # --------------------------------------------------
        # Availability Domain 조회
        # --------------------------------------------------

        ads = identity_client.list_availability_domains(
            compartment_id=tenancy_ocid
        ).data

        if not ads:
            print("❌ Availability Domain을 찾지 못했습니다.")
            sys.exit(1)

        print(
            f"🔎 {len(ads)}개의 Availability Domain에서 생성 시도"
        )

        # --------------------------------------------------
        # 각 AD에서 순차적으로 생성
        # --------------------------------------------------

        last_error = None

        for ad in ads:

            print("")
            print("--------------------------------------------------")
            print(f"🚀 생성 시도: {ad.name}")
            print("--------------------------------------------------")

            launch_details = oci.core.models.LaunchInstanceDetails(
                compartment_id=compartment_id,
                availability_domain=ad.name,
                display_name=INSTANCE_NAME,
                shape=SHAPE,

                shape_config=oci.core.models.LaunchInstanceShapeConfigDetails(
                    ocpus=OCPUS,
                    memory_in_gbs=MEMORY_GB
                ),

                source_details=oci.core.models.InstanceSourceViaImageDetails(
                    source_type="image",
                    image_id=target_image.id
                ),

                create_vnic_details=oci.core.models.CreateVnicDetails(
                    subnet_id=subnet_id,
                    assign_public_ip=True
                ),

                metadata={
                    "ssh_authorized_keys": ssh_public_key
                }
            )

            try:
                response = core_client.launch_instance(
                    launch_instance_details=launch_details
                )

                instance = response.data

                print("")
                print("🎉 OCI 인스턴스 생성 요청 성공!")
                print(f"이름: {INSTANCE_NAME}")
                print(f"OCID: {instance.id}")
                print(f"AD: {ad.name}")
                print(f"Shape: {SHAPE}")
                print(f"OCPU: {OCPUS}")
                print(f"RAM: {MEMORY_GB} GB")

                send_notification(
                    "🎉 [OCI] macrowatch 인스턴스 생성 성공!",
                    (
                        "OCI Ampere A1 인스턴스 생성에 성공했습니다.\n\n"
                        f"인스턴스 이름: {INSTANCE_NAME}\n"
                        f"Shape: {SHAPE}\n"
                        f"OCPU: {OCPUS}\n"
                        f"RAM: {MEMORY_GB} GB\n"
                        f"Region: {region}\n"
                        f"Availability Domain: {ad.name}\n\n"
                        f"Instance OCID:\n{instance.id}\n"
                    )
                )

                sys.exit(0)

            except oci.exceptions.ServiceError as e:
                last_error = e

                error_code = getattr(e, "code", "")
                error_message = getattr(e, "message", str(e))

                print(
                    f"❌ 생성 실패 [{ad.name}]"
                )
                print(
                    f"HTTP Status: {e.status}"
                )
                print(
                    f"Code: {error_code}"
                )
                print(
                    f"Message: {error_message}"
                )

                error_text = (
                    f"{error_code} {error_message}"
                ).lower()

                # OCI Free Tier A1에서 흔한 Capacity 부족
                if (
                    "out of capacity" in error_text
                    or "outofcapacity" in error_text
                    or "capacity" in error_text
                ):
                    print(
                        "➡️ 현재 해당 AD에 A1 여유 용량이 없습니다."
                    )
                    print(
                        "➡️ 다음 Availability Domain을 시도합니다."
                    )
                    continue

                # 서비스 제한
                if (
                    "limitexceeded" in error_text
                    or "limit exceeded" in error_text
                ):
                    print(
                        "⚠️ OCI 서비스 한도에 걸렸을 가능성이 있습니다."
                    )
                    continue

                # 다른 오류도 다른 AD 시도
                print(
                    "➡️ 다른 Availability Domain을 계속 시도합니다."
                )
                continue

            except Exception as e:
                last_error = e

                print(
                    f"💥 예상하지 못한 오류 [{ad.name}]: {e}"
                )

                continue

        # --------------------------------------------------
        # 모든 AD 실패
        # --------------------------------------------------

        print("")
        print("==================================================")
        print("❌ 모든 Availability Domain에서 생성 실패")
        print("다음 GitHub Actions 실행 때 다시 시도합니다.")
        print("==================================================")

        if last_error:
            print(f"마지막 오류: {last_error}")

        sys.exit(1)

    except oci.exceptions.ConfigFileNotFound:
        print("❌ OCI 설정 파일 오류")
        sys.exit(1)

    except oci.exceptions.InvalidConfig as e:
        print(f"❌ OCI 인증 설정 오류: {e}")
        sys.exit(1)

    except Exception as e:
        print(f"💥 스크립트 실행 중 예외 발생: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
