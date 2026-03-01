import pyray as rl
from dataclasses import dataclass
from typing import Optional
from openpilot.common.constants import CV
from openpilot.selfdrive.ui.mici.onroad.torque_bar import TorqueBar
from openpilot.selfdrive.ui.ui_state import ui_state, UIStatus
from openpilot.system.ui.lib.application import gui_app, FontWeight
from openpilot.system.ui.lib.multilang import tr
from openpilot.system.ui.lib.text_measure import measure_text_cached
from openpilot.system.ui.widgets import Widget
from openpilot.common.filter_simple import FirstOrderFilter
from cereal import log
from openpilot.common.params import Params
from datetime import datetime

EventName = log.OnroadEvent.EventName

# Constants
SET_SPEED_NA = 255
KM_TO_MILE = 0.621371
CRUISE_DISABLED_CHAR = '–'

SET_SPEED_PERSISTENCE = 2.5  # seconds

@dataclass(frozen=True)
class SetSpeedOverrideState:
  active: bool
  speed_kph: float
  label: str
  speed_color_mode: int # 0: white, 1: green, 2: orange
  force_persist: bool


class SetSpeedOverride:

  def compute(self, sm, set_speed_kph: float) -> SetSpeedOverrideState:
    # 1) eco (highest)
    cruise_target = None
    try:
      cruise_target = float(sm['longitudinalPlan'].cruiseTarget)
    except Exception:
      cruise_target = None

    if cruise_target is not None and cruise_target > (set_speed_kph + 0.5):
      return SetSpeedOverrideState(
        active=True,
        speed_kph=cruise_target,
        label="eco",
        speed_color_mode=1,
        force_persist=True,   # eco 조건 유지되는 동안 계속 표시
      )

    # 2) apply_speed (desiredSpeed/source)
    desired_speed = None
    desired_source = ""
    try:
      desired_speed = float(sm['carrotMan'].desiredSpeed)
      desired_source = str(sm['carrotMan'].desiredSource or "")
    except Exception:
      desired_speed = None
      desired_source = ""

    if desired_speed is not None and 0 < desired_speed < 200 and desired_speed < set_speed_kph:
      label = desired_source.strip() or "apply"
      label = label[:8]  # 너무 길면 UI 깨짐 방지 (원하면 길이 조절)
      return SetSpeedOverrideState(
        active=True,
        speed_kph=desired_speed,
        label=label,
        speed_color_mode=2,
        force_persist=True,   # 조건 유지되는 동안 계속 표시
      )

    # 3) default
    return SetSpeedOverrideState(
      active=False,
      speed_kph=set_speed_kph,
      label=tr("MAX"),
      speed_color_mode=0,
      force_persist=False,
    )

@dataclass(frozen=True)
class FontSizes:
  current_speed: int = 176
  speed_unit: int = 66
  max_speed: int = 36
  set_speed: int = 112


@dataclass(frozen=True)
class Colors:
  WHITE = rl.WHITE
  WHITE_TRANSLUCENT = rl.Color(255, 255, 255, 200)


FONT_SIZES = FontSizes()
COLORS = Colors()


class TurnIntent(Widget):
  FADE_IN_ANGLE = 30  # degrees

  def __init__(self):
    super().__init__()
    self._pre = False
    self._turn_intent_direction: int = 0

    self._turn_intent_alpha_filter = FirstOrderFilter(0, 0.05, 1 / gui_app.target_fps)
    self._turn_intent_rotation_filter = FirstOrderFilter(0, 0.1, 1 / gui_app.target_fps)

    self._txt_turn_intent_left: rl.Texture = gui_app.texture('icons_mici/turn_intent_left.png', 50, 20)
    self._txt_turn_intent_right: rl.Texture = gui_app.texture('icons_mici/turn_intent_left.png', 50, 20, flip_x=True)

  def _render(self, _):
    if self._turn_intent_alpha_filter.x > 1e-2:
      turn_intent_texture = self._txt_turn_intent_right if self._turn_intent_direction == 1 else self._txt_turn_intent_left
      src_rect = rl.Rectangle(0, 0, turn_intent_texture.width, turn_intent_texture.height)
      dest_rect = rl.Rectangle(self._rect.x + self._rect.width / 2, self._rect.y + self._rect.height / 2,
                               turn_intent_texture.width, turn_intent_texture.height)

      origin = (turn_intent_texture.width / 2, self._rect.height / 2)
      color = rl.Color(255, 255, 255, int(255 * self._turn_intent_alpha_filter.x))
      rl.draw_texture_pro(turn_intent_texture, src_rect, dest_rect, origin, self._turn_intent_rotation_filter.x, color)

  def _update_state(self) -> None:
    sm = ui_state.sm

    left = any(e.name == EventName.preLaneChangeLeft for e in sm['onroadEvents'])
    right = any(e.name == EventName.preLaneChangeRight for e in sm['onroadEvents'])
    if left or right:
      # pre lane change
      if not self._pre:
        self._turn_intent_rotation_filter.x = self.FADE_IN_ANGLE if left else -self.FADE_IN_ANGLE

      self._pre = True
      self._turn_intent_direction = -1 if left else 1
      self._turn_intent_alpha_filter.update(1)
      self._turn_intent_rotation_filter.update(0)
    elif any(e.name == EventName.laneChange for e in sm['onroadEvents']):
      # fade out and rotate away
      self._pre = False
      self._turn_intent_alpha_filter.update(0)

      if self._turn_intent_direction == 0:
        # unknown. missed pre frame?
        self._turn_intent_rotation_filter.update(0)
      else:
        self._turn_intent_rotation_filter.update(self._turn_intent_direction * self.FADE_IN_ANGLE)
    else:
      # didn't complete lane change, just hide
      self._pre = False
      self._turn_intent_direction = 0
      self._turn_intent_alpha_filter.update(0)
      self._turn_intent_rotation_filter.update(0)


class HudRenderer(Widget):
  def __init__(self):
    super().__init__()
    """Initialize the HUD renderer."""
    self._debug_speed_panel = False
    self.is_cruise_set: bool = False
    self.is_cruise_available: bool = True
    self.set_speed: float = SET_SPEED_NA
    self._set_speed_changed_time: float = 0
    self.speed: float = 0.0
    self.v_ego_cluster_seen: bool = False
    self._engaged: bool = False

    self._can_draw_top_icons = True
    self._show_wheel_critical = False

    self._font_bold: rl.Font = gui_app.font(FontWeight.BOLD)
    self._font_medium: rl.Font = gui_app.font(FontWeight.MEDIUM)
    self._font_semi_bold: rl.Font = gui_app.font(FontWeight.SEMI_BOLD)
    self._font_display: rl.Font = gui_app.font(FontWeight.DISPLAY)

    self._turn_intent = TurnIntent()
    self._torque_bar = TorqueBar()

    self._txt_wheel: rl.Texture = gui_app.texture('icons_mici/wheel.png', 50, 50)
    self._txt_wheel_critical: rl.Texture = gui_app.texture('icons_mici/wheel_critical.png', 50, 50)
    self._txt_exclamation_point: rl.Texture = gui_app.texture('icons_mici/exclamation_point.png', 44, 44)

    # Bottom-left speed panel background
    self._txt_speed_bg: rl.Texture = gui_app.texture('images/speed_bg.png', 307, 115)

    self._wheel_alpha_filter = FirstOrderFilter(0, 0.05, 1 / gui_app.target_fps)
    self._wheel_y_filter = FirstOrderFilter(0, 0.1, 1 / gui_app.target_fps)

    self._set_speed_alpha_filter = FirstOrderFilter(0.0, 0.1, 1 / gui_app.target_fps)
    
    self._set_speed_override = SetSpeedOverride()

  def set_wheel_critical_icon(self, critical: bool):
    """Set the wheel icon to critical or normal state."""
    self._show_wheel_critical = critical

  def set_can_draw_top_icons(self, can_draw_top_icons: bool):
    """Set whether to draw the top part of the HUD."""
    self._can_draw_top_icons = can_draw_top_icons

  def drawing_top_icons(self) -> bool:
    # whether we're drawing any top icons currently
    return bool(self._set_speed_alpha_filter.x > 1e-2)

  def _update_state(self) -> None:
    """Update HUD state based on car state and controls state."""
    sm = ui_state.sm
    if sm.recv_frame["carState"] < ui_state.started_frame:
      self.is_cruise_set = False
      self.set_speed = SET_SPEED_NA
      self.speed = 0.0
      return

    controls_state = sm['controlsState']
    car_state = sm['carState']

    v_cruise_cluster = car_state.vCruiseCluster
    set_speed = (
      controls_state.vCruiseDEPRECATED if v_cruise_cluster == 0.0 else v_cruise_cluster
    )
    engaged = sm['selfdriveState'].enabled
    if (set_speed != self.set_speed and engaged) or (engaged and not self._engaged):
      self._set_speed_changed_time = rl.get_time()
    self._engaged = engaged
    self.set_speed = set_speed
    self.is_cruise_set = 0 < self.set_speed < SET_SPEED_NA
    self.is_cruise_available = self.set_speed != -1

    v_ego_cluster = car_state.vEgoCluster
    self.v_ego_cluster_seen = self.v_ego_cluster_seen or v_ego_cluster != 0.0
    v_ego = v_ego_cluster if self.v_ego_cluster_seen else car_state.vEgo
    speed_conversion = CV.MS_TO_KPH if ui_state.is_metric else CV.MS_TO_MPH
    self.speed = max(0.0, v_ego * speed_conversion)

  def _render(self, rect: rl.Rectangle) -> None:
    """Render HUD elements to the screen."""

    if ui_state.sm['controlsState'].lateralControlState.which() != 'angleState':
      self._torque_bar.render(rect)

    # bottom-left panel (speed_bg)
    self._draw_set_speed(rect)

    # wheel moved to top-left
    self._draw_steering_wheel(rect)
    
    print(f"[FONTDBG] speed uses font DISPLAY? {self._font_display.texture.id}")

  def _draw_steering_wheel(self, rect: rl.Rectangle) -> None:
    wheel_txt = self._txt_wheel_critical if self._show_wheel_critical else self._txt_wheel

    # Always visible (no hide). We keep filters but drive them to stable values.
    self._wheel_alpha_filter.update(255 * 0.95)
    self._wheel_y_filter.update(0)

    # pos (TOP-left)
    margin_x = 18
    margin_y = 18
    pos_x = int(rect.x + margin_x + wheel_txt.width / 2)
    pos_y = int(rect.y + margin_y + wheel_txt.height / 2 + self._wheel_y_filter.x)

    # rotation
    rotation = -ui_state.sm['carState'].steeringAngleDeg

    # Turn intent (around wheel)
    turn_intent_margin = 25
    self._turn_intent.render(rl.Rectangle(
      pos_x - wheel_txt.width / 2 - turn_intent_margin,
      pos_y - wheel_txt.height / 2 - turn_intent_margin,
      wheel_txt.width + turn_intent_margin * 2,
      wheel_txt.height + turn_intent_margin * 2,
    ))

    src_rect = rl.Rectangle(0, 0, wheel_txt.width, wheel_txt.height)
    dest_rect = rl.Rectangle(pos_x, pos_y, wheel_txt.width, wheel_txt.height)
    origin = (wheel_txt.width / 2, wheel_txt.height / 2)

    # Color: green if lat_active else gray
    if ui_state.lat_active:
      wheel_color = rl.Color(0, 255, 0, int(self._wheel_alpha_filter.x))     # green
    else:
      wheel_color = rl.Color(160, 160, 160, int(self._wheel_alpha_filter.x)) # gray

    rl.draw_texture_pro(wheel_txt, src_rect, dest_rect, origin, rotation, wheel_color)

    if self._show_wheel_critical:
      EXCLAMATION_POINT_SPACING = 10
      exclamation_pos_x = pos_x - self._txt_exclamation_point.width / 2 + wheel_txt.width / 2 + EXCLAMATION_POINT_SPACING
      exclamation_pos_y = pos_y - self._txt_exclamation_point.height / 2
      rl.draw_texture(self._txt_exclamation_point, int(exclamation_pos_x), int(exclamation_pos_y), rl.WHITE)


    # ----- current time (right of wheel) -----
    now_text = datetime.now().strftime("%H:%M")

    # 휠 높이 기준으로 폰트 크기 설정
    time_font = int(wheel_txt.height * 1.1)  # 90% 정도 (너무 꽉 차지 않게)

    time_size = measure_text_cached(self._font_semi_bold, now_text, time_font)

    time_x = pos_x + wheel_txt.width / 2 + 15
    time_y = pos_y - time_size.y / 2

    rl.draw_text_ex(
      self._font_semi_bold,
      now_text,
      rl.Vector2(time_x, time_y),
      time_font,
      0,
      rl.Color(255, 255, 255, 230),
    )

  def _get_gear_text(self) -> str:
    sm = ui_state.sm

    try:
      car_state = sm["carState"]
      gear = car_state.gearShifter
    except Exception:
      return "R"

    # cereal enum → 문자열 변환
    try:
      gear_name = str(gear).split('.')[-1]
    except Exception:
      gear_name = str(gear)

    # DRIVE 처리
    if "DRIVE" in gear_name.upper():
      try:
        step = int(car_state.gearStep)
        if step > 0:
          return str(step)
        else:
          return "D"
      except Exception:
        return "D"

    if "PARK" in gear_name.upper():
      return "P"

    if "REVERSE" in gear_name.upper():
      return "R"

    if "NEUTRAL" in gear_name.upper():
      return "N"

    if "SPORT" in gear_name.upper():
      return "S"

    if "LOW" in gear_name.upper():
      return "L"

    if "BRAKE" in gear_name.upper():
      return "B"

    if "ECO" in gear_name.upper():
      return "E"

    if "UNKNOWN" in gear_name.upper():
      return "U"

    return "M"

  def _get_cruise_gap(self) -> int:
    try:
      personality = Params().get_int("LongitudinalPersonality")
      gap = int(personality) + 1
    except Exception:
      gap = 8

    return gap

  def _draw_set_speed(self, rect: rl.Rectangle) -> None:
    """
    Bottom-left speed panel (like your 3rd image)
    - Background: images/speed_bg.png
    - Overlays: current speed, set speed, traffic light, cruise gap (1~4), gear (D/P/R/N)
    """
    ov = self._set_speed_override.compute(ui_state.sm, float(self.set_speed))

    # ----- panel placement (bottom-left) -----
    bg = self._txt_speed_bg
    panel_w = bg.width
    panel_h = bg.height

    margin_x = 10
    margin_y = 10
    panel_x = int(rect.x + margin_x)
    panel_y = int(rect.y + rect.height - panel_h - margin_y)

    # draw background
    rl.draw_texture(bg, panel_x, panel_y, rl.WHITE)

    # ----- current speed (big, left) -----
    if self._debug_speed_panel:
      cur_speed_int = 123
    else:
      cur_speed_int = int(round(self.speed))

    cur_text = str(cur_speed_int)

    cur_font = 80
    cur_size = measure_text_cached(self._font_display, cur_text, cur_font)
    cur_x = panel_x + 18

    cur_y = int(panel_y + panel_h * 0.48 - cur_size.y * 0.5) - 2

    rl.draw_text_ex(
      self._font_display,
      cur_text,
      rl.Vector2(cur_x, cur_y),
      cur_font,
      0,
      rl.WHITE,
    )
    
    mode_text, mode_color = self._get_driving_mode_text_and_color()
    if self._debug_speed_panel:
      mode_text = "safe"
      mode_color = rl.Color(0, 255, 0, 230)

    if mode_text:
      mode_font = 35
      mode_size = measure_text_cached(self._font_semi_bold, mode_text, mode_font)

      mode_x = panel_x + 35
      mode_y = int(panel_y + panel_h * 0.05 - mode_size.y * 0.5 - 15)

      rl.draw_text_ex(
        self._font_semi_bold,
        mode_text,
        rl.Vector2(mode_x, mode_y),
        mode_font,
        0,
        mode_color,
      )
  
    # ----- set speed (center, smaller) -----
    show_set = self._engaged and self.is_cruise_set
    if True: #show_set or self._debug_speed_panel:
      if show_set:
        set_speed = self.set_speed
        if not ui_state.is_metric:
          set_speed *= KM_TO_MILE
        set_text = str(int(round(set_speed)))
      else:
        set_text = "--"

      set_color = rl.Color(0, 255, 0, 230)

      if self._debug_speed_panel:
        set_text = str(123)

      set_font = 40
      set_size = measure_text_cached(self._font_display, set_text, set_font)
      set_x = int(panel_x + panel_w * 0.76 - set_size.x * 0.5)
      set_y = int(panel_y + panel_h * 0.33 - set_size.y * 0.5)
      rl.draw_text_ex(
        self._font_display,
        set_text,
        rl.Vector2(set_x, set_y),
        set_font,
        0,
        set_color,
      )
      if ov.active:
        set_speed = ov.speed_kph
        if not ui_state.is_metric:
          set_speed *= KM_TO_MILE
        set_text = str(int(round(set_speed)))
        set_label_text = ov.label

        if ov.speed_color_mode == 1:      # eco
          set_color = rl.Color(0, 255, 0, 230)
        elif ov.speed_color_mode == 2:    # apply
          set_color = rl.Color(255, 165, 0, 230)
        else:
          set_color = rl.Color(0, 255, 0, 230)   # your sample is green

        if self._debug_speed_panel:
          set_text = str(111)
          set_color = rl.Color(255, 165, 0, 230)
          set_label_text = "vturn"

        set_font = 40
        set_size = measure_text_cached(self._font_display, set_text, set_font)
        set_x = int(panel_x + panel_w * 0.90 - set_size.x * 0.5 + 50)
        set_y = int(panel_y + panel_h * 0.25 - set_size.y * 0.5)
        rl.draw_text_ex(
          self._font_display,
          set_text,
          rl.Vector2(set_x, set_y),
          set_font,
          0,
          set_color,
        )
        set_font = 30
        set_size = measure_text_cached(self._font_display, set_label_text, set_font)
        set_x = int(panel_x + panel_w * 0.90 - set_size.x * 0.5 + 50)
        set_y = int(panel_y + panel_h * 0.10 - set_size.y * 0.5 - 20)
        rl.draw_text_ex(
          self._font_display,
          set_label_text,
          rl.Vector2(set_x, set_y),
          set_font,
          0,
          set_color,
        )

    # ----- cruise gap (small circle + number, bottom-mid-right) -----
    gap = self._get_cruise_gap()
    gap_center_x = int(panel_x + panel_w * 0.90)
    gap_center_y = int(panel_y + panel_h * 0.82)
    #rl.draw_circle_lines(gap_center_x, gap_center_y, 16, rl.WHITE)

    gap_text = str(gap)
    gap_font = 28
    gap_size = measure_text_cached(self._font_semi_bold, gap_text, gap_font)
    rl.draw_text_ex(
      self._font_semi_bold,
      gap_text,
      rl.Vector2(gap_center_x - gap_size.x * 0.5, gap_center_y - gap_size.y * 0.5),
      gap_font,
      0,
      rl.WHITE,
    )

    # ----- gear (right side box with letter) -----
    gear = self._get_gear_text()
    box_w = 44
    box_h = 54
    box_x = int(panel_x + panel_w - box_w - 14 + 70)
    box_y = int(panel_y + panel_h * 0.50)

    # Fill (dark) + border (green)
    rl.draw_rectangle_rounded(rl.Rectangle(box_x, box_y, box_w, box_h), 0.2, 8, rl.Color(0, 0, 0, 120))
    rl.draw_rectangle_rounded_lines_ex(rl.Rectangle(box_x, box_y, box_w, box_h), 0.2, 8, 3, rl.Color(0, 255, 0, 230))

    gear_font = 44
    gear_size = measure_text_cached(self._font_display, gear, gear_font)
    rl.draw_text_ex(
      self._font_display,
      gear,
      rl.Vector2(box_x + (box_w - gear_size.x) * 0.5, box_y + (box_h - gear_size.y) * 0.5),
      gear_font,
      0,
      rl.WHITE,
    )

    if self._debug_speed_panel:
      active_lane_line = True
    else:
      active_lane_line = bool(ui_state.sm['controlsState'].activeLaneLine)      

    line1 = "lane"
    line2 = "mode" if active_lane_line else "less"

    lane_font = 26  # 원하면 22~30 사이로 조절
    lane_color = rl.Color(255, 255, 255, 220)  # 흰색

    lane_x = box_x + box_w + 80
    lane_y1 = box_y + 6
    lane_y2 = box_y + 6 + lane_font + 2

    # 오른쪽 정렬(gear box 옆에 딱 붙게)
    s1 = measure_text_cached(self._font_semi_bold, line1, lane_font)
    s2 = measure_text_cached(self._font_semi_bold, line2, lane_font)

    rl.draw_text_ex(
      self._font_semi_bold,
      line1,
      rl.Vector2(lane_x - s1.x, lane_y1),
      lane_font, 0, lane_color
    )
    rl.draw_text_ex(
      self._font_semi_bold,
      line2,
      rl.Vector2(lane_x - s2.x, lane_y2),
      lane_font, 0, lane_color
    )

  def _draw_driving_mode_text(self, rect: rl.Rectangle) -> None:
    # (기존 기능 유지용) 지금은 _render에서 호출하지 않음
    if not self._engaged:
      return

    mode_text, mode_color = self._get_driving_mode_text_and_color()
    if not mode_text:
      return

    wheel_txt = self._txt_wheel_critical if self._show_wheel_critical else self._txt_wheel
    pos_x = int(rect.x + 21 + wheel_txt.width / 2)
    pos_y = int(rect.y + rect.height - 14 - wheel_txt.height / 2 + self._wheel_y_filter.x)

    mode_font = FONT_SIZES.max_speed
    mode_size = measure_text_cached(self._font_semi_bold, mode_text, mode_font)

    mode_x = int(pos_x + wheel_txt.width / 2 + 10)
    mode_y = int(pos_y - mode_size.y / 2)

    # 기존 driving_mode
    rl.draw_text_ex(
      self._font_semi_bold,
      mode_text,
      rl.Vector2(mode_x, mode_y),
      mode_font,
      0,
      mode_color,
    )

    active_lane_line = bool(ui_state.sm['controlsState'].activeLaneLine)
    if active_lane_line:
      lm_text = "lanemode"
      lm_color = self._color_mode(1, 200)   # green
    else:
      lm_text = "laneless"
      lm_color = self._color_mode(2, 200)   # orange
      
    lm_gap = 10

    lm_x = int(mode_x + mode_size.x + lm_gap)
    lm_y = mode_y  # 같은 높이/크기

    rl.draw_text_ex(
      self._font_semi_bold,
      lm_text,
      rl.Vector2(lm_x, lm_y),
      mode_font,
      0,
      lm_color,
    )

  def _color_mode(self, mode: int, alpha: int = 200) -> rl.Color:
    # mode: 0 white, 1 green, 2 orange, 3 red
    if mode == 1:
      return rl.Color(0, 255, 0, alpha)
    if mode == 2:
      return rl.Color(255, 165, 0, alpha)
    if mode == 3:
      return rl.Color(255, 0, 0, alpha)
    return rl.Color(255, 255, 255, alpha)

  def _get_driving_mode_text_and_color(self) -> tuple[str, rl.Color]:
    try:
      mode_val = int(ui_state.sm["longitudinalPlan"].myDrivingMode)
    except Exception:
      return "", self._color_mode(0, 200)

    if mode_val == 1:   # eco
      return "eco", self._color_mode(1, 200)
    if mode_val == 2:   # safe
      return "safe", self._color_mode(2, 200)
    if mode_val == 3:   # normal
      return "norm", self._color_mode(0, 200)
    if mode_val == 4:   # high
      return "high", self._color_mode(3, 200)

    return "", self._color_mode(0, 200)


  def _draw_current_speed(self, rect: rl.Rectangle) -> None:
    """Draw the current vehicle speed and unit."""
    speed_text = str(round(self.speed))
    speed_text_size = measure_text_cached(self._font_bold, speed_text, FONT_SIZES.current_speed)
    speed_pos = rl.Vector2(rect.x + rect.width / 2 - speed_text_size.x / 2, 180 - speed_text_size.y / 2)
    rl.draw_text_ex(self._font_bold, speed_text, speed_pos, FONT_SIZES.current_speed, 0, COLORS.WHITE)

    unit_text = tr("km/h") if ui_state.is_metric else tr("mph")
    unit_text_size = measure_text_cached(self._font_medium, unit_text, FONT_SIZES.speed_unit)
    unit_pos = rl.Vector2(rect.x + rect.width / 2 - unit_text_size.x / 2, 290 - unit_text_size.y / 2)
    rl.draw_text_ex(self._font_medium, unit_text, unit_pos, FONT_SIZES.speed_unit, 0, COLORS.WHITE_TRANSLUCENT)
