from opendbc.car.interfaces import RadarInterfaceBase
from opendbc.car.hyundai.values import DBC, HyundaiFlags
from opendbc.can import CANParser
from opendbc.car import Bus, structs
from opendbc.car.hyundai.hyundaicanfd import CanBus
from openpilot.common.params import Params
import ast

RADAR_START_ADDR_CANFD1 = 0x210  # Group 1 (msg당 2 타겟)
RADAR_MSG_COUNT1 = 16

RADAR_START_ADDR_CANFD2 = 0x3A5  # Group 2 (msg당 1 타겟)
RADAR_MSG_COUNT2 = 32


# ===== 레이더 파서 클래스들 =====
class _RadarBase:
  start_addr: int = 0
  msg_count: int = 0

  def build_parser(self, CP, CAN: CanBus) -> CANParser:
    raise NotImplementedError

  def parse_points(self, iface: "CarrotRadarInterface") -> list[structs.RadarData.RadarPoint]:
    raise NotImplementedError

  # 공통: trackId/pts 관리
  def _get_pt(self, iface: "CarrotRadarInterface", key: int) -> structs.RadarData.RadarPoint:
    if key not in iface.pts:
      iface.pts[key] = structs.RadarData.RadarPoint()
      iface.pts[key].trackId = iface.track_id
      iface.track_id += 1
    return iface.pts[key]

  def _del_pt(self, iface: "CarrotRadarInterface", key: int) -> None:
    if key in iface.pts:
      del iface.pts[key]


class RadarCanFdGroup1(_RadarBase):
  start_addr = RADAR_START_ADDR_CANFD1
  msg_count = RADAR_MSG_COUNT1

  def build_parser(self, CP, CAN: CanBus) -> CANParser:
    # hyundai_canfd_radar_generated DBC를 쓰는 구조를 가정 (당신 기존 코드 방향 그대로)
    messages = [(f"RADAR_TRACK_{addr:x}", 20) for addr in range(self.start_addr, self.start_addr + self.msg_count)]
    return CANParser("hyundai_canfd_radar_generated", messages, CAN.ACAN)

  def parse_points(self, iface: "CarrotRadarInterface"):
    for addr in range(self.start_addr, self.start_addr + self.msg_count):
      msg = iface.rcp.vl[f"RADAR_TRACK_{addr:x}"]

      # target1: key = addr
      k1 = addr
      valid1 = msg.get("VALID_CNT1", 0) > 10
      if valid1:
        pt = self._get_pt(iface, k1)
        pt.measured = True
        pt.dRel = msg["LONG_DIST1"]
        pt.yRel = msg["LAT_DIST1"]
        pt.vRel = msg["REL_SPEED1"]
        pt.aRel = msg["REL_ACCEL1"]
        pt.yvRel = msg["LAT_SPEED1"]
      else:
        self._del_pt(iface, k1)

      # target2: key = addr + msg_count
      k2 = addr + self.msg_count
      valid2 = msg.get("VALID_CNT2", 0) > 10
      if valid2:
        pt = self._get_pt(iface, k2)
        pt.measured = True
        pt.dRel = msg["LONG_DIST2"]
        pt.yRel = msg["LAT_DIST2"]
        pt.vRel = msg["REL_SPEED2"]
        pt.aRel = msg["REL_ACCEL2"]
        pt.yvRel = msg["LAT_SPEED2"]
      else:
        self._del_pt(iface, k2)

    return list(iface.pts.values())


class RadarCanFdGroup2(_RadarBase):
  start_addr = RADAR_START_ADDR_CANFD2
  msg_count = RADAR_MSG_COUNT2

  def build_parser(self, CP, CAN: CanBus) -> CANParser:
    messages = [(f"RADAR_TRACK_{addr:x}", 20) for addr in range(self.start_addr, self.start_addr + self.msg_count)]
    return CANParser("hyundai_canfd_radar_generated", messages, CAN.ACAN)

  def parse_points(self, iface: "CarrotRadarInterface"):
    for addr in range(self.start_addr, self.start_addr + self.msg_count):
      msg = iface.rcp.vl[f"RADAR_TRACK_{addr:x}"]
      valid = msg.get("VALID_CNT", 0) > 10

      if valid:
        pt = self._get_pt(iface, addr)
        pt.measured = True
        pt.dRel = msg["LONG_DIST"]
        pt.yRel = msg["LAT_DIST"]
        pt.vRel = msg["REL_SPEED"]
        pt.aRel = msg["REL_ACCEL"]
        pt.yvRel = msg["LAT_SPEED"]
      else:
        self._del_pt(iface, addr)

    return list(iface.pts.values())


class RadarSccFallback(_RadarBase):
  # SCC_CONTROL 기반 (레이더 트랙이 없을 때 임시)
  start_addr = 0x1A0
  msg_count = 1

  def build_parser(self, CP, CAN: CanBus) -> CANParser:
    msgs = [("SCC_CONTROL", 50)]
    bus = CAN.ECAN
    bus = CAN.CAM if CP.flags & HyundaiFlags.CAMERA_SCC else bus
    return CANParser(DBC[CP.carFingerprint][Bus.pt], msgs, bus)

  def parse_points(self, iface: "CarrotRadarInterface"):
    msg = iface.rcp.vl["SCC_CONTROL"]
    d_rel = msg.get("ACC_ObjDist", 0.0)
    valid = 0.0 < d_rel < 150.0

    key = self.start_addr
    if valid:
      pt = self._get_pt(iface, key)
      pt.measured = True
      pt.dRel = d_rel
      pt.yRel = 0.0
      pt.vRel = msg.get("ACC_ObjRelSpd", 0.0)
      pt.aRel = float("nan")
      pt.yvRel = float("nan")
    else:
      self._del_pt(iface, key)

    return list(iface.pts.values())


# ===== CarrotRadarInterface =====
class CarrotRadarInterface(RadarInterfaceBase):
  def _carrot_init(self, CP):
    CAN = CanBus(CP)
    self.canfd = bool(CP.flags & HyundaiFlags.CANFD)

    self.radar = None
    self.track_id = 0

    if not self.canfd:
      return

    fingerprints_str = Params().get("FingerPrints")
    fingerprints = ast.literal_eval(fingerprints_str)

    if RADAR_START_ADDR_CANFD1 in fingerprints[CAN.ACAN]:
      self.radar = RadarCanFdGroup1()
    elif RADAR_START_ADDR_CANFD2 in fingerprints[CAN.ACAN]:
      self.radar = RadarCanFdGroup2()
    else:
      self.radar = RadarSccFallback()

    self.radar_start_addr = self.radar.start_addr
    self.radar_msg_count = self.radar.msg_count
    self.rcp = self.radar.build_parser(CP, CAN)

    self.trigger_msg = self.radar_start_addr + self.radar_msg_count - 1

  def _carrot_update(self, updated_messages):
    ret = structs.RadarData()
    if self.rcp is None:
      return ret

    if not self.rcp.can_valid:
      ret.errors.canError = True
      return ret

    if self.radar is None:
      return ret

    ret.points = self.radar.parse_points(self)
    return ret
