import os
import sys
import oci

# 깃허브 Secrets에서 오라클 환경변수 불러오기
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

def get_ubuntu_2604_image_id():
    """사용 중인 리전의 Canonical Ubuntu 26.04 이미지 OCID 찾기 (없을 경우 최신 Ubuntu로 대체)"""
    try:
        images = compute_client.list_images(
            compartment_id=tenancy_ocid,
            operating_system="Canonical Ubuntu",
            shape="VM.Standard.A1.Flex"
        ).data
        
        # Canonical Ubuntu 26.04 이미지 우선 검색
        for img in images:
            if "26.04" in img.display_name:
                print(f"✅ Ubuntu 26.04 이미지 발견: {img.display_name}")
                return img.id
                
        # 만약 해당 리전에 26.04가 아직 등록되어 있지 않다면 가장 최신 우분투 이미지 사용
        if images:
            print(f"⚠️ Ubuntu 26.04를 찾을 수 없어 최신 Ubuntu 이미지({images[0].display_name})로 진행합니다.")
            return images[0].id
            
    except Exception as e:
        print(f"⚠️ 이미지 조회 실패: {e}")
    return None

def create_instance():
    try:
        # 가용 영역(Availability Domain) 가져오기
        ad_list = identity_client.list_availability_domains(tenancy_ocid).data
        if not ad_list:
            print("❌ Availability Domain을 찾을 수 없습니다.")
            return
        ad_name = ad_list[0].name

        image_id = get_ubuntu_2604_image_id()
        if not image_id:
            print("❌ 우분투 이미지를 찾을 수 없어 시도를 중단합니다.")
            return

        # 무료 Ampere A1 (4 Core, 24GB RAM) 및 지정 이름(macrowatch) 설정
        launch_details = oci.core.models.LaunchInstanceDetails(
            compartment_id=tenancy_ocid,
            availability_domain=ad_name,
            display_name="macrowatch",
            shape="VM.Standard.A1.Flex",
            shape_config=oci.core.models.LaunchInstanceShapeConfigDetails(
                ocpus=4,
                memory_in_gbs=24
            ),
            create_vnic_details=oci.core.models.CreateVnicDetails(
                subnet_id=subnet_id,
                assign_public_ip=True
            ),
            source_details=oci.core.models.InstanceSourceViaImageDetails(
                source_type="image",
                image_id=image_id
            )
        )

        print(f"🚀 [{region} / {ad_name}] 'macrowatch' 인스턴스 생성 시도 중...")
        response = compute_client.launch_instance(launch_details)
        print("🎉🎉 축하합니다! 'macrowatch' 인스턴스 생성 성공! ID:", response.data.id)

    except oci.exceptions.ServiceError as e:
        if e.status in [500, 502, 503, 504] or "Out of host capacity" in str(e) or "Capacity" in str(e):
            print("❌ 자원 부족 (Out of Capacity). 다음 스케줄에 자동으로 재시도합니다.")
        else:
            print(f"⚠️ 오라클 서비스 에러 발생 (코드 {e.status}): {e.message}")
    except Exception as e:
        print(f"⚠️ 기타 에러 발생: {e}")

if __name__ == "__main__":
    create_instance()
