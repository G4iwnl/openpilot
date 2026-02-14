import pyray as rl
from dataclasses import dataclass
from openpilot.common.constants import CV
from openpilot.selfdrive.ui.mici.onroad.torque_bar import TorqueBar
from openpilot.selfdrive.ui.ui_state import ui_state, UIStatus
from openpilot.system.ui.lib.application import gui_app, FontWeight
from openpilot.system.ui.lib.multilang import tr
from openpilot.system.ui.lib.text_measure import measure_text_cached
from openpilot.system.ui.widgets import Widget
from openpilot.common.filter_simple import FirstOrderFilter
from cereal import log

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

    if desired_speed is not None and desired_speed > 0.0 and desired_speed < set_speed_kph:
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
    self._txt_turn_intent_right: rl.Texture = gui_app.texture('icons_mici/turn_intent_right.png', 50, 20)

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

    #if self.is_cruise_set:
    self._draw_set_speed(rect)

    self._draw_steering_wheel(rect)
    self._draw_driving_mode_text(rect)
    
  def _draw_steering_wheel(self, rect: rl.Rectangle) -> None:
    wheel_txt = self._txt_wheel_critical if self._show_wheel_critical else self._txt_wheel

    # Always visible (no hide). We keep filters but drive them to stable values.
    self._wheel_alpha_filter.update(255 * 0.95)
    self._wheel_y_filter.update(0)

    # pos (bottom-left)
    pos_x = int(rect.x + 21 + wheel_txt.width / 2)
    pos_y = int(rect.y + rect.height - 14 - wheel_txt.height / 2 + self._wheel_y_filter.x)

    # rotation
    rotation = -ui_state.sm['carState'].steeringAngleDeg

    # Turn intent still OK
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

  def _draw_set_speed(self, rect: rl.Rectangle) -> None:
    ov = self._set_speed_override.compute(ui_state.sm, float(self.set_speed))

    x = rect.x
    y = rect.y

    circle_d = 162
    circle_radius = circle_d // 2

    # 배경(원형)은 기존대로
    rl.draw_circle_gradient(
      int(x + circle_radius), int(y + circle_radius), circle_radius,
      rl.Color(0, 0, 0, 120), rl.BLANK
    )

    # ============================================================
    # 1) 현재 주행속도: 항상 표시 (3자리 슬롯, 오른쪽 정렬)
    # ============================================================
    big_font = FONT_SIZES.set_speed
    top_y = int(y + 3 - 8 - 3 + 4)

    left_margin = 10
    gap = 10

    # 실제 화면(컨텐츠 영역) 오른쪽 끝을 사용
    screen_right = int(rect.x + rect.width - 12)   # 오른쪽 여백 12

    inner_left = int(x + left_margin)

    # 3자리 슬롯 폭
    slot_w = int(measure_text_cached(self._font_display, "888", big_font).x)

    # 슬롯은 왼쪽에 고정
    slot_left = inner_left
    slot_right = slot_left + slot_w

    # 숫자는 슬롯 안에서 오른쪽 정렬
    cur_speed_int = int(round(self.speed))
    cur_digits = str(cur_speed_int)
    cur_digits_w = measure_text_cached(self._font_display, cur_digits, big_font).x
    cur_x = int(slot_right - cur_digits_w)

    rl.draw_text_ex(
      self._font_display,
      cur_digits,
      rl.Vector2(cur_x, top_y),
      big_font,
      0,
      rl.WHITE,
    )

    # ============================================================
    # 2) set_speed 블록: engaged일 때만 표시
    #    -> "3" 오른쪽(= slot_right + gap)에서 시작
    # ============================================================
    show_set_block = self._engaged and self.is_cruise_set and self._can_draw_top_icons
    if not show_set_block:
      return

    # set_speed 값
    set_speed = ov.speed_kph if ov.active else self.set_speed
    if not ui_state.is_metric:
      set_speed *= KM_TO_MILE
    set_speed_text = str(int(round(set_speed)))

    # label
    #max_text = (ov.label if ov.active else tr("MAX")) or "MAX"
    max_text = ov.label if ov.active else "cruise"
    max_text = max_text[:6]

    # 색상(기존 로직)
    if ov.speed_color_mode == 1:      # eco
      set_speed_color = rl.Color(0, 255, 0, 230)
    elif ov.speed_color_mode == 2:    # apply
      set_speed_color = rl.Color(255, 165, 0, 230)
    else:                             # default
      set_speed_color = rl.Color(255, 255, 255, 230)

    max_color = rl.Color(255, 255, 255, 230)

    # 폰트
    label_font = max(22, int(FONT_SIZES.max_speed * 0.85))
    speed_font = max(48, int(FONT_SIZES.set_speed * 0.62))

    label_size = measure_text_cached(self._font_semi_bold, max_text, label_font)
    spd_size = measure_text_cached(self._font_display, set_speed_text, speed_font)

    block_w = int(max(label_size.x, spd_size.x))
    block_h = label_size.y + 2 + spd_size.y

    # 블록은 무조건 속도 오른쪽부터 시작
    block_left = int(slot_right + gap)

    # 화면 오른쪽을 넘어가면, 블록을 오른쪽 끝에 붙임(그래도 속도쪽으로 침범 X)
    max_left = int(screen_right - block_w)
    if block_left > max_left:
      block_left = max_left

    # 그래도 속도쪽 침범하면(아주 극단) -> 그냥 그리지 않음
    if block_left <= slot_right:
      return

    # 세로 정렬: big_font 높이 안에 맞춤
    big_size = measure_text_cached(self._font_display, "888", big_font)
    block_top = top_y + (big_size.y - block_h) / 2.0

    # draw
    rl.draw_text_ex(
      self._font_semi_bold,
      max_text,
      rl.Vector2(block_left + (block_w - label_size.x), block_top),
      label_font,
      0,
      max_color,
    )
    rl.draw_text_ex(
      self._font_display,
      set_speed_text,
      rl.Vector2(block_left + (block_w - spd_size.x), block_top + label_size.y + 2),
      speed_font,
      0,
      set_speed_color,
    )
    

  def _draw_driving_mode_text(self, rect: rl.Rectangle) -> None:
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
