import numpy as np
import copy
from opendbc.car.common.conversions import Conversions as CV

def hyundai_crc8(data: bytes) -> int:
  poly = 0x2F
  crc = 0xFF

  for byte in data:
    crc ^= byte
    for _ in range(8):
      if crc & 0x80:
        crc = ((crc << 1) ^ poly) & 0xFF
      else:
        crc = (crc << 1) & 0xFF

  return crc ^ 0xFF

def is_emergency_steering(CS):
  emergency_steering = False
  if CS.adrv_161 is not None:
    emergency_steering = CS.adrv_161["ALERTS_1"] in [11, 12, 13, 14, 15, 21, 22, 23, 24, 25, 26]
  return emergency_steering

def create_fake_mdps_active(ret, frame, packer, CAN, CS, angle_control):
  if CS.mdps is not None:
    mdps = copy.copy(CS.mdps)
    if angle_control:
      if CS.lfa_alt is not None:
        mdps["LFA2_ACTIVE"] = CS.lfa_alt["LKAS_ANGLE_ACTIVE"]
    else:
      if CS.lfa is not None:
        mdps["LKA_ACTIVE"] = 1 if CS.lfa["STEER_REQ"] == 1 else 0

      if frame % 1000 < 40:
        mdps["STEERING_COL_TORQUE"] += 220
    ret.append(packer.make_can_msg("MDPS", CAN.CAM, mdps))

def create_fake_steering_touch(ret, frame, packer, CAN, CS):
  if frame % 10 == 0:
    if CS.teer_touch_2af is not None:
      steer_touch = copy.copy(CS.teer_touch_2af)
      if frame % 1000 < 40:
        steer_touch["TOUCH_DETECT"] = 3
        steer_touch["TOUCH1"] = 50
        steer_touch["TOUCH2"] = 50
        steer_touch["CHECKSUM_"] = 0
        dat = packer.make_can_msg("STEER_TOUCH_2AF", 0, steer_touch)[1]
        steer_touch["CHECKSUM_"] = hyundai_crc8(dat[1:8])

      ret.append(packer.make_can_msg("STEER_TOUCH_2AF", CAN.CAM, steer_touch))
  

def create_steering_messages_camera_scc(frame, packer, CAN, CC, lat_active, apply_steer, CS, apply_angle, max_torque, angle_control):

  emergency_steering = is_emergency_steering(CS)

  ret = []
  create_fake_mdps_active(ret, frame, packer, CAN, CS, angle_control)
  #create_fake_steering_touch(ret, frame, packer, CAN, CS)

  if angle_control:
    if CS.lfa_alt is not None:
      if emergency_steering:
        values = CS.lfa_alt
      else:
        values = copy.copy(CS.lfa_alt) #{} #CS.lfa_alt_info
        values["LKAS_ANGLE_ACTIVE"] = 2 if CC.latActive else 1
        values["LKAS_ANGLE_CMD"] = -apply_angle
        values["LKAS_ANGLE_MAX_TORQUE"] = max_torque if CC.latActive else 0
      ret.append(packer.make_can_msg("LFA_ALT", CAN.ECAN, values))

    if CS.lfa is not None:
      
      if frame % 100 == 0:
        if CS.lfa["FCA_SYSWARN"] != 0:
          print("FCA_SYSWARN")
        if CS.ccnc_162 is not None:
          if CS.ccnc_162["FAULT_FSS"] != 0:
            print("FAULT_FSS")
          
      values = copy.copy(CS.lfa)
      if not emergency_steering:
        values["LKA_MODE"] = 0
        values["LKA_ICON"] = 2 if CC.latActive else 1
        values["TORQUE_REQUEST"] = -1024  # apply_steer,
        values["VALUE63"] = 0
        values["STEER_REQ"] = 0
        values["HAS_LANE_SAFETY"] = 0 
        values["LKA_ACTIVE"] = 3 if CC.latActive else 0  # this changes sometimes, 3 seems to indicate engaged
        values["VALUE64"] = 0
        values["LKAS_ANGLE_CMD"] = -25.6
        values["LKAS_ANGLE_ACTIVE"] = 0
        values["LKAS_ANGLE_MAX_TORQUE"] = 0 #max_torque if lat_active else 0,
        values["NEW_SIGNAL_1"] = 10
      ret.append(packer.make_can_msg("LFA", CAN.ECAN, values))

  else:
    values = {}
    values["LKA_MODE"] = 2
    values["LKA_ICON"] = 2 if lat_active else 1
    values["TORQUE_REQUEST"] = apply_steer
    values["STEER_REQ"] = 1 if lat_active else 0
    values["VALUE64"] = 0
    values["HAS_LANE_SAFETY"] = 0
    values["LKA_ACTIVE"] = 0

    values["DampingGain"] = 0 if lat_active else 100  

    ret.append(packer.make_can_msg("LFA", CAN.ECAN, values))

  return ret

def create_lfahda_cluster(packer, CS, CAN, long_active, lat_active):
  if CS.lfahda_cluster is not None:
    values = {}
    values["HDA_CntrlModSta"] = 2 if long_active else 0
    values["HDA_LFA_SymSta"] = 2 if lat_active else 0
  else:
    return []
  return [packer.make_can_msg("LFAHDA_CLUSTER", CAN.ECAN, values)]

def create_acc_control_scc2(packer, CAN, enabled, accel_last, accel, stopping, gas_override, set_speed, hud_control, CS):
  #enabled = (enabled or CS.softHoldActive > 0) and CS.paddle_button_prev == 0

  acc_mode = 0 if not enabled else (2 if gas_override else 1)
  softHoldActive = 0

  """
  if hyundai_jerk.carrot_cruise == 1:
    acc_mode = 4 if enabled else 0
    enabled = False
    accel = accel_last = 0.5
   
  elif hyundai_jerk.carrot_cruise == 2:
    accel = accel_last = hyundai_jerk.carrot_cruise_accel

  jerk_u = hyundai_jerk.jerk_u
  jerk_l = hyundai_jerk.jerk_l
  """

  jerk_u = 3
  jerk_l = 5
  jn = jerk_l / 50
  if not enabled or gas_override:
    a_val, a_raw = 0, 0
  else:
    a_raw = accel
    a_val = np.clip(accel, accel_last - jn, accel_last + jn)

  if CS.scc_control is None:
    return None
  values = copy.copy(CS.scc_control)
  values.pop("COUNTER", None)
  values["ACCMode"] = acc_mode
  values["MainMode_ACC"] = 1
  values["StopReq"] = 1 if stopping or softHoldActive > 0 else 0  # 1: Stop control is required, 2: Not used, 3: Error Indicator
  values["aReqValue"] = a_val
  values["aReqRaw"] = a_raw
  values["VSetDis"] = set_speed
  values["JerkLowerLimit"] = jerk_l if enabled else 1
  values["JerkUpperLimit"] = 2.0 if stopping or softHoldActive else jerk_u
  values["DISTANCE_SETTING"] = hud_control.leadDistanceBars # + 5
  values["DriveMode"] = 0 # 0: Default, 1: Comfort Mode, 2:Normal mode, 3:Dynamic mode, reserved

  hud_lead_info = 0
  if hud_control.leadVisible:
    hud_lead_info = 1 if values["ACC_ObjRelSpd"] > 0 else 2
  values["HUD_LEAD_INFO"] = hud_lead_info  #1: in-path object detected(uncontrollable), 2: controllable long, 3: controllable long & lat, ... reserved

  values["DriverAlert"] = 0   # 1: SCC Disengaged, 2: No SCC Engage condition, 3: SCC Disenganed when the vehicle stops

  values["TARGET_DISTANCE"] = CS.out.vEgo * 1.0 + 4.0

  soft_hold_info = 1 if softHoldActive > 1 and enabled else 0

  # 이거안하면 정지중 뒤로 밀리는 현상 발생하는듯.. (신호정지중에 뒤로 밀리는 경험함.. 시험해봐야)
  if values["InfoDisplay"] != 5: #5: Front Car Departure Notice
    values["InfoDisplay"] = 4 if stopping and CS.out.aEgo > -0.3 else 0  # 1: SCC Mode, 2: Convention Cruise Mode, 3: Object disappered at low speed, 4: Available to resume acceleration control, 5: Front vehicle departure notice, 6: Reserved, 7: Invalid

  values["TakeOverReq"] = 0    # 1: Takeover request, 2: Not used, 3: Error indicator , 이것이 켜지면 가속을 안하는듯함.
  values["SysFailState"] = 0    # 1: Performance degredation, 2: system temporairy unavailble, 3: SCC Service required , 눈이 묻어 레이더오류시... 2가 됨. 이때 가속을 안함...

  values["AccelLimitBandUpper"] = 0.0   # 이값이 1.26일때 가속을 안하는 증상이 보임.. 
  values["AccelLimitBandLower"] = 0.0

  values["ZEROS_7"] = 1

  return packer.make_can_msg("SCC_CONTROL", CAN.ECAN, values)

def create_tcs_messages(packer, CAN, CS):
  ret = []
  if CS.tcs is not None:
    values = copy.copy(CS.tcs)
    values["DriverBraking"] = 0
    values["NEW_SIGNAL_20"] = 0
    values["NEW_SIGNAL_11"] = 0
    values["DriverBrakingLowSens"] = 0
    #values["NEW_SIGNAL_1"] = 0 # accel과 관련..  옆두부 꺼지는것과 관련? 확인필요
    #values["ACC_REQ"] = 1 # 옆두부 꺼지는것과 관련? 확인필요.. 항상 켜지게함..
    values["NEW_SIGNAL_1"] = 0 if values["ACC_REQ"] == 1 else 1 # 옆두부..
    ret.append(packer.make_can_msg("TCS", CAN.CAM, values))
  return ret

def alt_cruise_buttons(packer, CP, CAN, buttons, cruise_btns_msg, cnt):
  cruise_btns_msg["CRUISE_BUTTONS"] = buttons
  cruise_btns_msg["COUNTER"] = (cruise_btns_msg["COUNTER"] + 1 + cnt) % 256
  bus = CAN.ECAN if CP.flags & HyundaiFlags.CANFD_HDA2 else CAN.CAM
  return packer.make_can_msg("CRUISE_BUTTONS_ALT", bus, cruise_btns_msg)

def _clip_int(x, lo, hi):
  return lo if x < lo else hi if x > hi else int(x)

def _get_desire_and_lane_changing(md):
  desire = 0
  lane_changing = 0
  if md is not None:
    desire = md.meta.desire.raw
    ds = md.meta.desireState
    if len(ds) > 4:
      if ds[1] > 0.3: lane_changing = 1
      if ds[2] > 0.3: lane_changing = 2
      if ds[3] > 0.3: lane_changing = 3
      if ds[4] > 0.3: lane_changing = 4
  return desire, lane_changing

def _apply_lane_desire(values, desire):
  #values['LANE_CHANGING'] = 0

  if desire == 1:  # 좌회전
    values['LANE_CHANGING'] = 1
    values["LANELINE_CURVATURE"] = 15
    values["LANELINE_CURVATURE_DIRECTION"] = 0

  elif desire == 2:  # 우회전
    values['LANE_CHANGING'] = 2
    values["LANELINE_CURVATURE"] = 15
    values["LANELINE_CURVATURE_DIRECTION"] = 1

  elif desire == 3:  # 좌차선변경
    values['LANE_CHANGING'] = 3

  elif desire == 4:  # 우차선변경
    values['LANE_CHANGING'] = 4

def _apply_radar_blink(values, radar_pairs, frame, *,
                      disp_dist=30.0, min_dist=14.0,
                      max_interval=100, t=1.0):
  """
  거리 > min_dist 일 때만 깜빡임.
  거리 멀수록 interval 커짐(느리게).
  """
  for det_key, dist_key in radar_pairs:
    dist = values[dist_key]
    if dist <= min_dist:
      continue

    d = min(dist, disp_dist)
    interval = int((1 + (max_interval - 1) * (d / disp_dist)) * t)
    interval = _clip_int(interval, 1, max_interval)

    blink = (frame // interval) & 1
    values[det_key] = 2 - blink
    values[dist_key] = min_dist

def _make_ccnc_values(values, CS, lat_active, frame, hud_control,
                     lane_line=True, corner_radar=True,
                     desire=0,
                     blink_pairs=None,
                     blink_t=1.0):
  if lane_line:
    curvature = round(CS.out.steeringAngleDeg / 3)
    mag = min(abs(curvature), 15)
    curv = mag + (-1 if curvature < 0 else 0)
    direction = 1 if curvature < 0 else 0
    values["LANELINE_CURVATURE"] = curv if lat_active else 0
    values["LANELINE_CURVATURE_DIRECTION"] = direction if lat_active else 0
    if desire:
      _apply_lane_desire(values, desire)

  if corner_radar:
    radar_all = [
      ('LF_DETECT', 'LF_DETECT_DISTANCE'),
      ('RF_DETECT', 'RF_DETECT_DISTANCE'),
      ('LR_DETECT', 'LR_DETECT_DISTANCE'),
      ('RR_DETECT', 'RR_DETECT_DISTANCE'),
    ]
    for det_key, dist_key in radar_all:
      if values[det_key] >= 4 and values[dist_key] != 0:
        values[det_key] = 1

    if blink_pairs:
      _apply_radar_blink(values, blink_pairs, frame, t=blink_t)

def enable_corner_radar(ret, packer, CAN, frame):
  if frame % 500 in [10, 20, 30]:
    values = {
      'BYTE_1': 0,
      'BYTE_2': 0,
      'BYTE_3': 0x80,
      'BYTE_4': 0x8A,
      'BYTE_5': 0x32,
      'BYTE_6': 0x30,
      'BYTE_7': 0x01,
      'BYTE_8': 0x00,
    }
    ret.append(packer.make_can_msg("NEW_MSG_4B9", CAN.CAM, values))
  elif frame % 500 in [40, 50, 60]:
    values = {
      'BYTE_1': 0xff,
      'BYTE_2': 0xff,
      'BYTE_3': 0xff,
      'BYTE_4': 0xff,
      'BYTE_5': 0xff,
      'BYTE_6': 0xff,
      'BYTE_7': 0xff,
      'BYTE_8': 0xff,
    }
    ret.append(packer.make_can_msg("NEW_MSG_4B9", CAN.CAM, values))

def activate_scc_lfa(ret, packer, CAN, frame, CC, CS, lfahda_cluster):
  if frame % 2 == 0:
    MainMode_ACC = CS.scc_control["MainMode_ACC"] == 1 if CS.scc_control is not None else False
    ACCMode = CS.scc_control["ACCMode"] if CS.scc_control is not None else 0
    
    if CS.cruise_buttons_msg is not None:
      values = copy.copy(CS.cruise_buttons_msg)

      if lfahda_cluster["HDA_LFA_SymSta"] == 0 and 0 < frame % 200 < 12:
        values["LDA_BTN"] = 1

      if CC.enabled and MainMode_ACC:
        if ACCMode in [0, 4] and 10 < frame % 200 < 22:
          values["CRUISE_BUTTONS"] = 2
      elif CC.enabled and (not MainMode_ACC) and 10 < frame % 200 <= 16 and CS.out.vEgo > 3.:
        values["ADAPTIVE_CRUISE_MAIN_BTN"] = 1
      else:
        values["ADAPTIVE_CRUISE_MAIN_BTN"] = 0

      ret.append(packer.make_can_msg(CS.cruise_btns_msg_canfd, CAN.CAM, values))
  
def create_ccnc_messages(CP, packer, CAN, frame, CC, CS, hud_control,
                         disp_angle, left_lane_warning, right_lane_warning):
  ret = []

  #md = CS.MD
  desire, lane_changing = 0, 0 #_get_desire_and_lane_changing(md)

  HDA_CntrlModSta = CS.lfahda_cluster["HDA_CntrlModSta"] if CS.lfahda_cluster is not None else False

  if CS.lfahda_cluster is not None:
    activate_scc_lfa(ret, packer, CAN, frame, CC, CS, CS.lfahda_cluster)

  # --- 0x161/0x200/0x1ea/0x162 (frame%5) ---
  if frame % 5 == 0:
    lat_active = CC.latActive

    if CS.adrv_161 is not None:
      main_enabled = CS.out.cruiseState.available
      cruise_enabled = CC.enabled
      lat_enabled = main_enabled #CS.out.latEnabled
      nav_active = False #hud_control.activeCarrot > 1

      # hdpuse carrot
      hdp_active = False

      values = copy.copy(CS.adrv_161)

      values["SETSPEED"] = (6 if hdp_active else 3 if cruise_enabled else 1) if main_enabled else 0
      values["SETSPEED_HUD"] = (5 if hdp_active else 3 if cruise_enabled else 1) if main_enabled else 0

      set_speed_in_units = hud_control.setSpeed * (CV.MS_TO_KPH if CS.is_metric else CV.MS_TO_MPH)
      values["vSetDis"] = int(set_speed_in_units + 0.5)

      values["DISTANCE"] = 4 if hdp_active else hud_control.leadDistanceBars
      values["DISTANCE_LEAD"] = 2 if cruise_enabled and hud_control.leadVisible else 1 if main_enabled and hud_control.leadVisible else 0
      values["DISTANCE_CAR"] = 3 if hdp_active else 2 if cruise_enabled else 1 if main_enabled else 0
      values["DISTANCE_SPACING"] = 5 if hdp_active else 1 if cruise_enabled else 0

      values["TARGET"] = 1 if main_enabled else 0
      #values["TARGET_DISTANCE"] = int(hud_control.leadDistance)

      #values["BACKGROUND"] = 6 if CS.paddle_button_prev > 0 else 1 if cruise_enabled else 3 if main_enabled else 7
      values["CENTERLINE"] = 1 if HDA_CntrlModSta > 0 else 0
      values["CAR_CIRCLE"] = 2 if hdp_active else 1 if cruise_enabled else 0

      values["NAV_ICON"] = 2 if nav_active else 0
      values["HDA_ICON"] = 5 if hdp_active else 2 if cruise_enabled else 1 if main_enabled else 0
      values["LFA_ICON"] = 5 if hdp_active else 2 if lat_active else 1 if lat_enabled else 0
      values["LKA_ICON"] = 4 if lat_active else 3 if lat_enabled else 0
      values["FCA_ALT_ICON"] = 0

      if values["ALERTS_2"] in [1, 2, 5, 6, 10, 21, 22]:
        values["ALERTS_2"] = 0
        values["DAW_ICON"] = 0

      if values["ALERTS_1"] == 0: # alerts가 있으면 사운드도 같이 나옴
        values["SOUNDS_1"] = 0
        values["SOUNDS_2"] = 0
        values["SOUNDS_4"] = 0

      if values["ALERTS_3"] in [3, 4, 13, 17, 19, 26, 7, 8, 9, 10]:
        values["ALERTS_3"] = 0
        values["SOUNDS_3"] = 0

      if values["ALERTS_5"] in [1, 2, 3, 4, 5]:
        values["ALERTS_5"] = 0

      if values["ALERTS_5"] in [11] and CS.softHoldActive == 0:
        values["ALERTS_5"] = 0

      # curvature 표시(0x161쪽 기존 로직 유지)
      curvature = round(CS.out.steeringAngleDeg / 3)
      values["LANELINE_CURVATURE"] = (min(abs(curvature), 15) + (-1 if curvature < 0 else 0)) if lat_active else 0
      values["LANELINE_CURVATURE_DIRECTION"] = 1 if curvature < 0 and lat_active else 0

      """
      lane_color = 4 if CS.out.leftLaneLine >= 20 or CS.out.leftBlindspot else 2
      if hud_control.leftLaneDepart:
        values["LANELINE_LEFT"] = 4 if (frame // 50) % 2 == 0 else 1
      else:
        values["LANELINE_LEFT"] = lane_color if hud_control.leftLaneVisible else 0

      lane_color = 4 if CS.out.rightLaneLine >= 20 or CS.out.rightBlindspot else 2
      if hud_control.rightLaneDepart:
        values["LANELINE_RIGHT"] = 4 if (frame // 50) % 2 == 0 else 1
      else:
        values["LANELINE_RIGHT"] = lane_color if hud_control.rightLaneVisible else 0
      """

      values["LCA_LEFT_ARROW"] = 2 if CS.out.leftBlinker else 0
      values["LCA_RIGHT_ARROW"] = 2 if CS.out.rightBlinker else 0

      values["LCA_LEFT_ICON"] = 1 if CS.out.leftBlindspot else 2
      values["LCA_RIGHT_ICON"] = 1 if CS.out.rightBlindspot else 2

      values["LANE_LEFT"] = 1 if desire in (1, 3) else 0
      values["LANE_RIGHT"] = 1 if desire in (2, 4) else 0

      ret.append(packer.make_can_msg("ADRV_0x161", CAN.ECAN, values))

    if CS.adrv_200 is not None:
      values = copy.copy(CS.adrv_200)
      values["TauGapSet"] = hud_control.leadDistanceBars
      ret.append(packer.make_can_msg("ADRV_0x200", CAN.ECAN, values))

    if CS.adrv_1ea is not None:
      values = copy.copy(CS.adrv_1ea)

      # blinker hold
      values['LEFT_BLINK_HOLD'] = 1 if lane_changing == 3 else 0
      values['RIGHT_BLINK_HOLD'] = 1 if lane_changing == 4 else 0

      _make_ccnc_values(
        values, CS, lat_active, frame, hud_control,
        lane_line=True,
        corner_radar=True,
        desire=desire,
        # 기존대로 LR/RR만 깜빡임
        blink_pairs=[('LR_DETECT', 'LR_DETECT_DISTANCE'),
                      ('RR_DETECT', 'RR_DETECT_DISTANCE')],
        blink_t=1.0
      )

      ret.append(packer.make_can_msg("ADRV_0x1ea", CAN.ECAN, values))

    if False: #CS.ccnc_162 is not None:
      values = copy.copy(CS.ccnc_162)

      if hud_control.leadDistance > 0:
        values["FF_DISTANCE"] = hud_control.leadDistance
        ff_type = 3 if hud_control.leadRadar == 1 else 13
        values["FF_DETECT"] = ff_type if hud_control.leadRelSpeed > -0.1 else ff_type + 1

      _make_ccnc_values(
        values, CS, lat_active, frame, hud_control,
        lane_line=False,
        corner_radar=True,
        desire=0,
        # 필요하면 162도 깜빡임 적용(원래 코드처럼 LR/RR만)
        blink_pairs=[('LR_DETECT', 'LR_DETECT_DISTANCE'),
                      ('RR_DETECT', 'RR_DETECT_DISTANCE')],
        blink_t=1.0
      )

      if (left_lane_warning and not CS.out.leftBlinker) or (right_lane_warning and not CS.out.rightBlinker):
        values["VIBRATE"] = 1

      ret.append(packer.make_can_msg("CCNC_0x162", CAN.ECAN, values))

  if HDA_CntrlModSta == 0:
    enable_corner_radar(ret, packer, CAN, frame)
  return ret

