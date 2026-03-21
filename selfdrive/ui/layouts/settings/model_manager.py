#!/usr/bin/env python3
"""
Model Manager Dialog for C4 (comma4)
Allows downloading and switching driving models.
"""

import os
import json
import shutil
import hashlib
import subprocess
import threading
import time
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional

import pyray as rl
import urllib.request
import urllib.error

from openpilot.common.params import Params
from openpilot.system.ui.lib.application import gui_app, FontWeight, MousePos
from openpilot.system.ui.lib.multilang import tr
from openpilot.system.ui.lib.text_measure import measure_text_cached
from openpilot.system.ui.widgets import Widget, DialogResult
from openpilot.system.ui.widgets.button import Button, ButtonStyle
from openpilot.system.ui.widgets.label import gui_label
from openpilot.system.ui.widgets.scroller_tici import Scroller

# Constants
MODELS_JSON_URL = "https://raw.githubusercontent.com/happymaj11r/openpilot-models/main/models.json"
MODELS_DIR = Path("/data/models")
MODELS_TMP_DIR = Path("/data/models_tmp")
MODELS_BACKUP_DIR = Path("/data/models_backup")
STATUS_FILE = Path("/data/model_compile_status")
DEFAULT_MODEL_NAME = "DTRv6"
MODEL_SELECTOR_VERSION = 2

REQUIRED_MODEL_FILES = [
    'driving_vision_tinygrad.pkl',
    'driving_policy_tinygrad.pkl',
    'driving_vision_metadata.pkl',
    'driving_policy_metadata.pkl',
]

# UI constants
MARGIN = 60
TITLE_FONT_SIZE = 65
SUBTITLE_FONT_SIZE = 40
ITEM_FONT_SIZE = 45
STATUS_FONT_SIZE = 42
BUTTON_HEIGHT = 120
BUTTON_SPACING = 30
ROW_HEIGHT = 110
HEADER_HEIGHT = 80
FOOTER_HEIGHT = BUTTON_HEIGHT + MARGIN * 2

# Colors
BG_COLOR = rl.Color(27, 27, 27, 255)
PANEL_COLOR = rl.Color(41, 41, 41, 255)
ROW_COLOR = rl.Color(50, 50, 50, 255)
ROW_HOVER_COLOR = rl.Color(65, 65, 65, 255)
ROW_SELECTED_COLOR = rl.Color(70, 91, 234, 200)
HEADER_COLOR = rl.Color(35, 35, 35, 255)
TEXT_NORMAL = rl.Color(200, 200, 200, 255)
TEXT_GRAY = rl.Color(128, 128, 128, 255)
TEXT_WHITE = rl.WHITE
STATUS_OK = rl.Color(44, 226, 44, 255)
STATUS_ERROR = rl.Color(226, 44, 44, 255)
STATUS_PROGRESS = rl.Color(70, 91, 234, 255)
PROGRESS_BG = rl.Color(60, 60, 60, 255)


@dataclass
class FileInfo:
    size: int
    sha256: str


@dataclass
class ModelInfo:
    id: str
    name: str
    base_url: str
    added_at: str
    files: dict = field(default_factory=dict)
    minimum_selector_version: int = 1


def has_valid_custom_model(directory: Path = MODELS_DIR) -> bool:
    """Check if a custom model directory has all required files."""
    for filename in REQUIRED_MODEL_FILES:
        fi = directory / filename
        if not fi.exists() or fi.stat().st_size == 0:
            return False
    return True


def format_size(size_bytes: int) -> str:
    """Format byte size to human-readable string."""
    if size_bytes < 1024:
        return f"{size_bytes}B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes // 1024}KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f}MB"
    else:
        return f"{size_bytes / (1024 * 1024 * 1024):.2f}GB"


def get_dir_size(path: Path) -> int:
    """Get total size of all files in directory."""
    total = 0
    if path.exists():
        for f in path.rglob('*'):
            if f.is_file():
                total += f.stat().st_size
    return total


def get_available_storage() -> int:
    """Get available storage bytes at /data."""
    try:
        stat = os.statvfs("/data")
        return stat.f_bavail * stat.f_frsize
    except Exception:
        return 0


class ModelManagerDialog(Widget):
    """Model Manager Dialog for selecting and downloading driving models."""

    def __init__(self):
        super().__init__()
        self._params = Params()
        self._models: list[ModelInfo] = []
        self._selected_model_id: Optional[str] = None
        self._status_text: str = tr("Loading model list...")
        self._status_color: rl.Color = TEXT_NORMAL
        self._is_downloading: bool = False
        self._download_progress: float = 0.0
        self._current_download: Optional[ModelInfo] = None
        self._download_thread: Optional[threading.Thread] = None
        self._cancel_requested: bool = False
        self._font_bold = gui_app.font(FontWeight.BOLD)
        self._font_medium = gui_app.font(FontWeight.MEDIUM)
        self._font_normal = gui_app.font(FontWeight.NORMAL)
        self._scroll_offset: float = 0.0
        self._scroll_velocity: float = 0.0
        self._last_mouse_y: float = 0.0
        self._is_scrolling: bool = False
        self._scroll_start_y: float = 0.0
        self._scroll_start_offset: float = 0.0
        self._list_rect: rl.Rectangle = rl.Rectangle(0, 0, 0, 0)
        self._fetch_thread: Optional[threading.Thread] = None

        # Buttons
        self._download_btn = Button(lambda: tr("Download"), self._on_download_click,
                                    button_style=ButtonStyle.PRIMARY)
        self._reset_btn = Button(lambda: tr("Reset to Default"), self._on_reset_click,
                                 button_style=ButtonStyle.DANGER)
        self._cancel_btn = Button(lambda: tr("Cancel"), self._on_cancel_click,
                                  button_style=ButtonStyle.DANGER)
        self._close_btn = Button(lambda: tr("Close"), self._on_close_click,
                                 button_style=ButtonStyle.NORMAL)

        # Start fetching model list
        self._fetch_models()

    def _fetch_models(self):
        """Fetch model list from server in background thread."""
        self._fetch_thread = threading.Thread(target=self._do_fetch_models, daemon=True)
        self._fetch_thread.start()

    def _do_fetch_models(self):
        """Background thread to fetch model list."""
        try:
            req = urllib.request.Request(MODELS_JSON_URL,
                                          headers={'User-Agent': 'openpilot-model-selector/2.0'})
            with urllib.request.urlopen(req, timeout=10) as response:
                data = response.read()
            doc = json.loads(data.decode('utf-8'))
            self._parse_model_list(doc)
            self._status_text = tr("Select a model and tap Download")
            self._status_color = TEXT_NORMAL
        except urllib.error.URLError as e:
            self._status_text = tr("Network error: ") + str(e.reason)
            self._status_color = STATUS_ERROR
        except Exception as e:
            self._status_text = tr("Error: ") + str(e)
            self._status_color = STATUS_ERROR

    def _parse_model_list(self, doc: dict):
        """Parse model list from JSON document."""
        models = []
        for obj in doc.get("models", []):
            model_id = obj.get("id", "")
            base_url = obj.get("base_url", "")
            min_version = obj.get("minimum_selector_version", 1)

            # Version compatibility check
            if min_version > MODEL_SELECTOR_VERSION:
                continue

            # Validate id and url
            if not self._is_valid_model_id(model_id) or not self._is_valid_model_url(base_url):
                continue

            model = ModelInfo(
                id=model_id,
                name=obj.get("name", model_id),
                base_url=base_url,
                added_at=obj.get("added_at", ""),
                minimum_selector_version=min_version,
            )

            for filename, file_info in obj.get("files", {}).items():
                if self._is_valid_filename(filename):
                    model.files[filename] = FileInfo(
                        size=file_info.get("size", 0),
                        sha256=file_info.get("sha256", ""),
                    )

            if len(model.files) >= 2:
                models.append(model)

        self._models = models

    def _is_valid_model_id(self, model_id: str) -> bool:
        """Validate model ID - alphanumeric, dashes, underscores only."""
        if not model_id or len(model_id) > 64:
            return False
        import re
        return bool(re.match(r'^[a-zA-Z0-9_\-]+$', model_id))

    def _is_valid_model_url(self, url: str) -> bool:
        """Validate model URL - must be https only."""
        return url.startswith("https://")

    def _is_valid_filename(self, filename: str) -> bool:
        """Allowlist of valid ONNX filenames."""
        return filename in ("driving_policy.onnx", "driving_vision.onnx", "driving_off_policy.onnx")

    def _get_current_model_name(self) -> str:
        """Get currently active model name."""
        name = self._params.get("DrivingModelName") or ""
        if isinstance(name, bytes):
            name = name.decode("utf-8", "replace")
        name = name.strip()
        # Remove installing suffix for comparison
        if name.endswith(" (Installing...)"):
            name = name[:-len(" (Installing...)")]
        return name if name else DEFAULT_MODEL_NAME

    def _on_download_click(self):
        if not self._selected_model_id:
            return
        model = next((m for m in self._models if m.id == self._selected_model_id), None)
        if model is None:
            return
        current_name = self._get_current_model_name()
        if (model.name.lower() == current_name.lower() or
                model.id.lower() == current_name.lower()):
            self._status_text = tr("This model is already installed and in use.")
            self._status_color = STATUS_OK
            return
        self._start_download(model)

    def _on_reset_click(self):
        """Reset to default built-in model."""
        try:
            if MODELS_DIR.exists():
                shutil.rmtree(MODELS_DIR)
            self._params.remove("DrivingModelName")
            self._status_text = tr("Reset to default model. Please reboot.")
            self._status_color = STATUS_OK
        except Exception as e:
            self._status_text = tr("Reset failed: ") + str(e)
            self._status_color = STATUS_ERROR

    def _on_cancel_click(self):
        self._cancel_requested = True
        self._status_text = tr("Cancelling...")
        self._status_color = TEXT_NORMAL

    def _on_close_click(self):
        gui_app.pop_widget()

    def _start_download(self, model: ModelInfo):
        """Start downloading the selected model."""
        self._is_downloading = True
        self._cancel_requested = False
        self._current_download = model
        self._download_progress = 0.0
        self._status_text = tr("Preparing download...")
        self._status_color = STATUS_PROGRESS

        # Mark as pending in params
        self._params.put("PendingModelName", model.name)
        self._params.put("DrivingModelName", model.name + " (Installing...)")

        # Clean up and create tmp dir
        if MODELS_TMP_DIR.exists():
            shutil.rmtree(MODELS_TMP_DIR)
        MODELS_TMP_DIR.mkdir(parents=True, exist_ok=True)

        self._download_thread = threading.Thread(
            target=self._do_download, args=(model,), daemon=True
        )
        self._download_thread.start()

    def _do_download(self, model: ModelInfo):
        """Background thread for downloading model files."""
        try:
            filenames = list(model.files.keys())
            total_size = sum(f.size for f in model.files.values())
            downloaded_size = 0

            for i, filename in enumerate(filenames):
                if self._cancel_requested:
                    raise Exception("Download cancelled")

                file_info = model.files[filename]
                url = model.base_url + "/" + filename
                dest = MODELS_TMP_DIR / filename

                self._status_text = tr("Downloading ") + filename + "..."
                self._status_color = STATUS_PROGRESS

                file_downloaded = 0
                req = urllib.request.Request(url, headers={'User-Agent': 'openpilot-model-selector/2.0'})

                with urllib.request.urlopen(req, timeout=60) as response, open(dest, 'wb') as f:
                    block_size = 65536
                    while True:
                        if self._cancel_requested:
                            raise Exception("Download cancelled")
                        chunk = response.read(block_size)
                        if not chunk:
                            break
                        f.write(chunk)
                        file_downloaded += len(chunk)
                        downloaded_size += len(chunk)
                        if total_size > 0:
                            self._download_progress = min(downloaded_size / total_size, 1.0)

                # Verify downloaded file
                if file_info.sha256:
                    if not self._verify_file(dest, file_info.size, file_info.sha256):
                        raise Exception(f"File verification failed for {filename}")

            if self._cancel_requested:
                raise Exception("Download cancelled")

            # Hand off to compile_model.py in a subprocess
            self._status_text = tr("Starting compilation...")
            self._status_color = STATUS_PROGRESS
            self._download_progress = 1.0

            openpilot_dir = "/data/openpilot"
            compile_script = f"{openpilot_dir}/selfdrive/modeld/compile_model.py"
            subprocess.Popen(
                ["python3", compile_script, str(MODELS_TMP_DIR), model.name],
                cwd=openpilot_dir,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            self._status_text = tr("Compiling model in background. Please wait...")
            self._status_color = STATUS_PROGRESS

        except Exception as e:
            error_msg = str(e)
            if "cancelled" in error_msg.lower():
                self._status_text = tr("Download cancelled.")
                self._status_color = TEXT_NORMAL
            else:
                self._status_text = tr("Error: ") + error_msg
                self._status_color = STATUS_ERROR
            shutil.rmtree(MODELS_TMP_DIR, ignore_errors=True)
            self._params.remove("PendingModelName")
            current = self._params.get("DrivingModelName") or ""
            if isinstance(current, bytes):
                current = current.decode("utf-8", "replace")
            if "(Installing...)" in current:
                self._params.remove("DrivingModelName")
        finally:
            self._is_downloading = False
            self._current_download = None

    def _verify_file(self, filepath: Path, expected_size: int, expected_hash: str) -> bool:
        """Verify downloaded file size and SHA-256 hash."""
        if filepath.stat().st_size != expected_size:
            return False
        sha = hashlib.sha256()
        with open(filepath, 'rb') as f:
            for chunk in iter(lambda: f.read(65536), b''):
                sha.update(chunk)
        return sha.hexdigest() == expected_hash

    def _check_compile_status(self):
        """Check compile status file if compilation is in progress."""
        if STATUS_FILE.exists():
            try:
                status = STATUS_FILE.read_text().strip()
                if status.startswith("complete:"):
                    model_name = status[len("complete:"):]
                    self._status_text = tr("Model installed: ") + model_name
                    self._status_color = STATUS_OK
                    STATUS_FILE.unlink(missing_ok=True)
                elif status.startswith("error:"):
                    err = status[len("error:"):]
                    self._status_text = tr("Compilation error: ") + err
                    self._status_color = STATUS_ERROR
                    STATUS_FILE.unlink(missing_ok=True)
                elif status.startswith("compiling:") or status.startswith("installing:") or status.startswith("restarting:"):
                    self._status_text = tr("Compiling: ") + status.split(":", 1)[1]
                    self._status_color = STATUS_PROGRESS
            except Exception:
                pass

    def _render(self, rect: rl.Rectangle):
        # Check compile status periodically
        self._check_compile_status()

        # Background
        rl.draw_rectangle_rec(rect, BG_COLOR)

        content_x = rect.x + MARGIN
        content_w = rect.width - MARGIN * 2
        y = rect.y + MARGIN

        # Title
        current_model = self._get_current_model_name()
        has_custom = has_valid_custom_model()
        model_info_text = current_model if has_custom else tr("Default (Built-in)")
        title_text = tr("Driving Model: ") + model_info_text
        gui_label(rl.Rectangle(content_x, y, content_w, TITLE_FONT_SIZE), title_text, TITLE_FONT_SIZE,
                  font_weight=FontWeight.BOLD)
        y += TITLE_FONT_SIZE + 10

        # Storage info
        storage = get_available_storage()
        storage_text = tr("Available Storage: ") + format_size(storage)
        if has_custom:
            model_size = get_dir_size(MODELS_DIR)
            storage_text += f"  |  {tr('Model Size: ')}{format_size(model_size)}"
        gui_label(rl.Rectangle(content_x, y, content_w, SUBTITLE_FONT_SIZE), storage_text, SUBTITLE_FONT_SIZE,
                  color=TEXT_GRAY)
        y += SUBTITLE_FONT_SIZE + 20

        # Status text
        gui_label(rl.Rectangle(content_x, y, content_w, STATUS_FONT_SIZE), self._status_text, STATUS_FONT_SIZE,
                  color=self._status_color)
        y += STATUS_FONT_SIZE + 10

        # Progress bar (when downloading)
        if self._is_downloading and self._download_progress > 0:
            bar_rect = rl.Rectangle(content_x, y, content_w, 40)
            rl.draw_rectangle_rec(bar_rect, PROGRESS_BG)
            fill_w = content_w * self._download_progress
            if fill_w > 0:
                rl.draw_rectangle_rec(rl.Rectangle(content_x, y, fill_w, 40), STATUS_PROGRESS)
            y += 40 + 10
        else:
            y += 10

        # Model list area
        footer_y = rect.y + rect.height - FOOTER_HEIGHT
        list_h = footer_y - y - MARGIN
        self._list_rect = rl.Rectangle(content_x, y, content_w, list_h)
        self._draw_model_list(self._list_rect)

        # Footer buttons
        btn_y = footer_y + MARGIN
        self._draw_buttons(rl.Rectangle(content_x, btn_y, content_w, BUTTON_HEIGHT))

    def _draw_model_list(self, rect: rl.Rectangle):
        """Draw the model list with scroll support."""
        if not self._models:
            if self._fetch_thread and self._fetch_thread.is_alive():
                msg = tr("Loading...")
            else:
                msg = tr("No models available")
            gui_label(rect, msg, ITEM_FONT_SIZE, color=TEXT_GRAY)
            return

        current_model = self._get_current_model_name()
        available_models = [m for m in self._models
                            if m.name.lower() != current_model.lower()
                            and m.id.lower() != current_model.lower()]

        if not available_models:
            gui_label(rect, tr("No other models available"), ITEM_FONT_SIZE, color=TEXT_GRAY)
            return

        # Handle scroll
        mouse_pos = rl.get_mouse_position()
        in_list = rl.check_collision_point_rec(mouse_pos, rect)

        if in_list:
            wheel = rl.get_mouse_wheel_move()
            if wheel != 0:
                self._scroll_offset -= wheel * ROW_HEIGHT * 3
                self._scroll_velocity = 0

        total_h = len(available_models) * (ROW_HEIGHT + 2)
        max_scroll = max(0.0, total_h - rect.height)
        self._scroll_offset = max(0.0, min(self._scroll_offset, max_scroll))

        # Draw header
        header_rect = rl.Rectangle(rect.x, rect.y, rect.width, HEADER_HEIGHT)
        rl.draw_rectangle_rec(header_rect, HEADER_COLOR)
        col_widths = [rect.width * 0.55, rect.width * 0.25, rect.width * 0.20]
        hx = rect.x + 15
        for col_text, col_w in zip([tr("Model"), tr("Size"), tr("Date")], col_widths):
            gui_label(rl.Rectangle(hx, rect.y + (HEADER_HEIGHT - ITEM_FONT_SIZE) / 2, col_w, ITEM_FONT_SIZE),
                      col_text, ITEM_FONT_SIZE, color=TEXT_GRAY)
            hx += col_w

        list_content_rect = rl.Rectangle(rect.x, rect.y + HEADER_HEIGHT, rect.width, rect.height - HEADER_HEIGHT)

        # Scissor clip
        rl.begin_scissor_mode(int(list_content_rect.x), int(list_content_rect.y),
                              int(list_content_rect.width), int(list_content_rect.height))

        row_y = list_content_rect.y - self._scroll_offset
        for i, model in enumerate(available_models):
            row_rect = rl.Rectangle(list_content_rect.x, row_y, list_content_rect.width, ROW_HEIGHT)

            # Skip rows outside visible area
            if row_y + ROW_HEIGHT < list_content_rect.y or row_y > list_content_rect.y + list_content_rect.height:
                row_y += ROW_HEIGHT + 2
                continue

            # Row background
            is_selected = (model.id == self._selected_model_id)
            is_hover = in_list and rl.check_collision_point_rec(mouse_pos, row_rect) and not self._is_downloading
            if is_selected:
                row_color = ROW_SELECTED_COLOR
            elif is_hover:
                row_color = ROW_HOVER_COLOR
            else:
                row_color = ROW_COLOR if i % 2 == 0 else PANEL_COLOR
            rl.draw_rectangle_rec(row_rect, row_color)

            # Handle click
            if (is_hover and not self._is_downloading and
                    rl.is_mouse_button_released(rl.MouseButton.MOUSE_BUTTON_LEFT)):
                self._selected_model_id = model.id

            # Row content
            total_size = sum(f.size for f in model.files.values())
            rx = list_content_rect.x + 15
            text_y = row_y + (ROW_HEIGHT - ITEM_FONT_SIZE) / 2
            for col_text, col_w in zip(
                [model.name, format_size(total_size), model.added_at],
                col_widths
            ):
                gui_label(rl.Rectangle(rx, text_y, col_w - 10, ITEM_FONT_SIZE),
                          col_text, ITEM_FONT_SIZE, color=TEXT_NORMAL)
                rx += col_w

            row_y += ROW_HEIGHT + 2

        rl.end_scissor_mode()

        # Scrollbar
        if total_h > list_content_rect.height:
            sb_w = 8
            sb_h = list_content_rect.height * (list_content_rect.height / total_h)
            sb_y = list_content_rect.y + (self._scroll_offset / total_h) * list_content_rect.height
            rl.draw_rectangle_rounded(
                rl.Rectangle(list_content_rect.x + list_content_rect.width - sb_w - 4, sb_y, sb_w, max(30, sb_h)),
                1.0, 10, rl.Color(128, 128, 128, 180)
            )

    def _draw_buttons(self, rect: rl.Rectangle):
        """Draw action buttons in footer."""
        btn_w = (rect.width - BUTTON_SPACING * 3) / 4

        if self._is_downloading:
            cancel_rect = rl.Rectangle(rect.x, rect.y, btn_w * 1.5, rect.height)
            self._cancel_btn.render(cancel_rect)

            close_rect = rl.Rectangle(rect.x + rect.width - btn_w, rect.y, btn_w, rect.height)
            self._close_btn.render(close_rect)
        else:
            has_selection = self._selected_model_id is not None and any(
                m.id == self._selected_model_id for m in self._models
            )
            dl_rect = rl.Rectangle(rect.x, rect.y, btn_w * 1.5, rect.height)
            self._download_btn.set_enabled(has_selection)
            self._download_btn.render(dl_rect)

            reset_rect = rl.Rectangle(rect.x + btn_w * 1.5 + BUTTON_SPACING, rect.y, btn_w * 1.5, rect.height)
            self._reset_btn.set_enabled(has_valid_custom_model())
            self._reset_btn.render(reset_rect)

            close_rect = rl.Rectangle(rect.x + rect.width - btn_w, rect.y, btn_w, rect.height)
            self._close_btn.render(close_rect)

    def show_event(self):
        super().show_event()
        self._selected_model_id = None
        if not self._models:
            self._fetch_models()

    def hide_event(self):
        super().hide_event()
