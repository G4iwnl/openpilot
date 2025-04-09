from openpilot.common.params import Params
import time
from datetime import datetime

def get_gps_location_service(params: Params) -> str:
    if params.get_bool("UbloxAvailable"):
        return "gpsLocationExternal"
    else:
        return "gpsLocation"

def get_gps_time(use_external: bool = False) -> dict:
    """
    GPS로부터 시간 정보를 가져오는 함수
    Args:
        use_external: 외부 GPS 서비스 사용 여부 (UbloxAvailable과 연동)
    Returns:
        dict: {
            'success': bool,  # 성공 여부
            'time': datetime,  # GPS 시간 (UTC)
            'timestamp': float,  # Unix timestamp
            'source': str  # 시간 소스 (gpsLocation 또는 gpsLocationExternal)
        }
    """
    try:
        # 실제 구현에서는 여기서 GPS 하드웨어/서비스와 통신
        # 예시를 위해 현재 시간을 반환하지만 실제로는 GPS 모듈에서 시간 추출 필요
        
        if use_external:
            # 외부 GPS 서비스 사용 경우 (예: Ublox)
            # external_gps_time = get_external_gps_time()
            gps_time = datetime.utcnow()  # 임시 코드 (실제 구현시 교체 필요)
            source = "gpsLocationExternal"
        else:
            # 내부 GPS 서비스 사용 경우
            # internal_gps_time = get_internal_gps_time()
            gps_time = datetime.utcnow()  # 임시 코드 (실제 구현시 교체 필요)
            source = "gpsLocation"
        
        return {
            'success': True,
            'time': gps_time,
            'timestamp': time.mktime(gps_time.timetuple()),
            'source': source
        }
    except Exception as e:
        return {
            'success': False,
            'error': str(e),
            'source': "gpsLocationExternal" if use_external else "gpsLocation"
        }

def get_gps_time_from_service(params: Params) -> dict:
    """
    Params를 기반으로 GPS 서비스 유형을 결정하고 해당 서비스에서 시간을 가져옴
    """
    use_external = params.get_bool("UbloxAvailable")
    return get_gps_time(use_external)

# 사용 예제
if __name__ == "__main__":
    params = Params()
    
    # GPS 서비스 유형 확인
    service = get_gps_location_service(params)
    print(f"Using GPS service: {service}")
    
    # 해당 서비스에서 시간 가져오기
    time_data = get_gps_time_from_service(params)
    
    if time_data['success']:
        print(f"g4$Successfully got GPS time from {time_data['source']}")
        print(f"g4$GPS Time (UTC): {time_data['time']}")
        print(f"g4$Timestamp: {time_data['timestamp']}")
    else:
        print(f"g4$Failed to get GPS time from {time_data['source']}: {time_data['error']}")