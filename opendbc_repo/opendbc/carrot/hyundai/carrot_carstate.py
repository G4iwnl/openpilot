from opendbc.car.interfaces import CarStateBase
from openpilot.common.params import Params
from opendbc.car import Bus, create_button_events, structs, DT_CTRL

class CarrotCarState(CarStateBase):
  def _carrot_init(self, CP):
    self.controls_ready_count = 0
    self.cp_bsm = None
    self._params = Params()

    self.cp = None
    self.cp_cam = None
    self.cp_alt = None

    self.mdps = None
    self.steer_touch_2af = None
    self.tcs = None
    self.adrv_161 = None
    self.lfa_alt = None
    self.lfa = None
    self.ccnc_162 = None
    self.lfahda_cluster = None
    self.scc_control = None
    self.adrv_200 = None
    self.adrv_1ea = None
    self.cruise_buttons_msg = None

  def _carrot_monitor_fingerprint(self, can_parsers):
    self.cp = can_parsers[Bus.pt]
    self.cp_cam = can_parsers[Bus.cam]
    self.cp_alt = can_parsers[Bus.alt] if Bus.alt in can_parsers else None

    if self.controls_ready_count <= 200:
      if self._params.get_bool("ControlsReady"):
        self.controls_ready_count += 1

      if self.controls_ready_count == 50:  # after 500msec
        self.cp.enable_capture = self.cp_cam.enable_capture = True
        if self.cp_alt is not None:
          self.cp_alt.enable_capture = True
      elif self.controls_ready_count == 100: # after 1sec
        print("cp_cam.seen_addresses =", self.cp_cam.seen_addresses)
        print("cp.seen_addresses =", self.cp.seen_addresses)
        self.cp.enable_capture = self.cp_cam.enable_capture = False
        if self.cp_alt is not None:
          print("cp_alt.seen_addresses =", self.cp_alt.seen_addresses)
          self.cp_alt.enable_capture = False

        if 69 in self.cp.seen_addresses:
          self.gear_msg_canfd = "GEAR"
        if 442 in self.cp.seen_addresses:
          self.cp_bsm = self.cp
        elif 442 in self.cp_cam.seen_addresses:
          self.cp_bsm = self.cp_cam

        def add_if_seen(parser, name):
          msg = parser.dbc.name_to_msg.get(name)
          if not msg:
            print(f"{name} not in DBC")
            return
          if msg.address not in parser.seen_addresses:
            return
          if msg.address in parser.addresses:
            return
          parser._add_message(name)   # ← 이름으로 등록

        add_if_seen(self.cp, "MDPS")
        add_if_seen(self.cp, "STEER_TOUCH_2AF")
        add_if_seen(self.cp, "TCS")
        add_if_seen(self.cp_cam, "ADRV_0x161")
        add_if_seen(self.cp_cam, "LFA_ALT")
        add_if_seen(self.cp_cam, "LFA")
        add_if_seen(self.cp_cam, "CCNC_0x162")
        add_if_seen(self.cp_cam, "LFAHDA_CLUSTER")
        add_if_seen(self.cp_cam, "SCC_CONTROL")
        add_if_seen(self.cp_cam, "ADRV_0x200")
        add_if_seen(self.cp_cam, "ADRV_0x1ea")
        

  def _carrot_update_rx(self):
    self.mdps = self.cp.vl.get("MDPS")
    self.steer_touch_2af = self.cp.vl.get("STEER_TOUCH_2AF")
    self.tcs = self.cp.vl.get("TCS")
    self.adrv_161 = self.cp_cam.vl.get("ADRV_0x161")
    self.lfa_alt = self.cp_cam.vl.get("LFA_ALT")
    self.lfa = self.cp_cam.vl.get("LFA")
    self.ccnc_162 = self.cp_cam.vl.get("CCNC_0x162")
    self.lfahda_cluster = self.cp_cam.vl.get("LFAHDA_CLUSTER")
    self.scc_control = self.cp_cam.vl.get("SCC_CONTROL")
    self.adrv_200 = self.cp_cam.vl.get("ADRV_0x200")
    self.adrv_1ea = self.cp_cam.vl.get("ADRV_0x1ea")
    self.cruise_buttons_msg = self.cp.vl.get(self.cruise_btns_msg_canfd)
    
  def _carrot_update_canfd(self, ret):
    self._carrot_update_rx()

    ret.cruiseState.available = self.scc_control is not None and self.scc_control["MainMode_ACC"] == 1
    # TPMS
    #tpms_unit = self.cp.vl["TPMS"]["UNIT"] * 0.725 if int(self.cp.vl["TPMS"]["UNIT"]) > 0 else 1.
    #ret.tpms.fl = tpms_unit * self.cp.vl["TPMS"]["PRESSURE_FL"]
    #ret.tpms.fr = tpms_unit * self.cp.vl["TPMS"]["PRESSURE_FR"]
    #ret.tpms.rl = tpms_unit * self.cp.vl["TPMS"]["PRESSURE_RL"]
    #ret.tpms.rr = tpms_unit * self.cp.vl["TPMS"]["PRESSURE_RR"]

    # BSM
    if self.cp_bsm is not None:
      bsm_info = self.cp_bsm.vl["BLINDSPOTS_REAR_CORNERS"]
      ret.leftBlindspot = (bsm_info["FL_INDICATOR"] + bsm_info["INDICATOR_LEFT_TWO"] + bsm_info["INDICATOR_LEFT_FOUR"]) > 0
      ret.rightBlindspot = (bsm_info["FR_INDICATOR"] + bsm_info["INDICATOR_RIGHT_TWO"] + bsm_info["INDICATOR_RIGHT_FOUR"]) > 0

    # brakeLights
    #ret.brakeLights = ret.brakePressed or self.cp.vl["TCS"]["BrakeLight"] == 1
  
    return ret
