"""Radar lead-selection runtime."""

# Mirrors radar_motion.primary.VISION_ONLY_RADAR_TRACK_MODE. Importing that
# module here would pull the whole lead-selection stack into every caller.
VISION_ONLY_RADAR_TRACK_MODE = -2


def effective_radar_track_mode(
  brand: str,
  radar_unavailable: bool,
  configured_mode: int,
  vision_only: bool = False,
) -> int:
  """Keep radar-source options Hyundai-only and auto-select other cars."""
  if vision_only:
    return VISION_ONLY_RADAR_TRACK_MODE
  if brand == "hyundai":
    return int(configured_mode)
  return VISION_ONLY_RADAR_TRACK_MODE if radar_unavailable else 1
