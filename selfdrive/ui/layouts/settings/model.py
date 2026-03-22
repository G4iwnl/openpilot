import json
import shutil
import subprocess
import threading
import urllib.request
from pathlib import Path

from openpilot.common.basedir import BASEDIR
from openpilot.common.params import Params
from openpilot.common.swaglog import cloudlog
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.system.ui.lib.application import gui_app
from openpilot.system.ui.lib.multilang import tr
from openpilot.system.ui.widgets import Widget, DialogResult
from openpilot.system.ui.widgets.confirm_dialog import ConfirmDialog, alert_dialog
from openpilot.system.ui.widgets.list_view import button_item, text_item
from openpilot.system.ui.widgets.option_dialog import MultiOptionDialog
from openpilot.system.ui.widgets.scroller_tici import Scroller

MODELS_JSON_URL = "https://raw.githubusercontent.com/happymaj11r/openpilot-models/main/models.json"
MODELS_DIR = Path("/data/models")
MODELS_TMP_DIR = Path("/data/models_tmp")
MODELS_BACKUP_DIR = Path("/data/models_backup")
STATUS_FILE = Path("/data/model_compile_status")

REQUIRED_MODEL_FILES = [
  "driving_vision_tinygrad.pkl",
  "driving_policy_tinygrad.pkl",
  "driving_vision_metadata.pkl",
  "driving_policy_metadata.pkl",
]

DEFAULT_MODEL_NAME = "DTRv6"


def has_valid_custom_model(directory: Path) -> bool:
  for filename in REQUIRED_MODEL_FILES:
    filepath = directory / filename
    if not filepath.exists() or filepath.stat().st_size == 0:
      return False
  return True


class ModelLayout(Widget):
  def __init__(self):
    super().__init__()
    self._params = Params()
    self._models: list[dict] = []
    self._selected_model_id: str = ""
    self._is_downloading = False
    self._download_thread: threading.Thread | None = None
    self._model_dialog: MultiOptionDialog | None = None

    # UI items
    self._current_model_item = text_item(
      lambda: tr("Current Model"),
      self._get_current_model_display,
    )
    self._select_btn = button_item(
      lambda: tr("Select Model"),
      lambda: tr("SELECT"),
      description=lambda: tr("Download and select a custom driving model from the model list."),
      callback=self._on_select_model,
    )
    self._status_item = text_item(
      lambda: tr("Status"),
      self._get_status_text,
    )
    self._reset_btn = button_item(
      lambda: tr("Reset to Default"),
      lambda: tr("RESET"),
      description=lambda: tr("Remove custom model and revert to the built-in default model ({}).").format(DEFAULT_MODEL_NAME),
      callback=self._on_reset_model,
      enabled=lambda: ui_state.is_offroad() and has_valid_custom_model(MODELS_DIR),
    )

    self._scroller = Scroller([
      self._current_model_item,
      self._select_btn,
      self._status_item,
      self._reset_btn,
    ], line_separator=True, spacing=0)

    # Start background fetch
    self._fetch_model_list()

  def _get_current_model_display(self) -> str:
    model_name = (self._params.get("DrivingModelName") or b"").decode("utf-8", "replace").strip()
    if model_name:
      return model_name
    if has_valid_custom_model(MODELS_DIR):
      return tr("Custom (unknown)")
    return DEFAULT_MODEL_NAME + tr(" (default)")

  def _get_status_text(self) -> str:
    # Check compile status file
    if STATUS_FILE.exists():
      try:
        status = STATUS_FILE.read_text().strip()
        if status.startswith("compiling:"):
          return tr("Compiling: ") + status[len("compiling:"):]
        if status.startswith("installing:"):
          return tr("Installing: ") + status[len("installing:"):]
        if status.startswith("done:"):
          return tr("Done: ") + status[len("done:"):]
        if status.startswith("error:"):
          return tr("Error: ") + status[len("error:"):]
        return status
      except OSError:
        pass
    if self._is_downloading:
      return tr("Downloading...")
    if not self._models:
      return tr("Loading model list...")
    return tr("{} models available").format(len(self._models))

  def _fetch_model_list(self):
    def _fetch():
      try:
        with urllib.request.urlopen(MODELS_JSON_URL, timeout=10) as resp:
          data = json.loads(resp.read().decode("utf-8"))
          if isinstance(data, list):
            self._models = data
          elif isinstance(data, dict) and "models" in data:
            self._models = data["models"]
      except Exception as e:
        cloudlog.warning(f"Failed to fetch model list: {e}")
        self._models = []

    thread = threading.Thread(target=_fetch, daemon=True)
    thread.start()

  def _on_select_model(self):
    if not self._models:
      self._fetch_model_list()
      gui_app.push_widget(alert_dialog(tr("Model list not loaded yet. Please try again shortly.")))
      return

    if not ui_state.is_offroad():
      gui_app.push_widget(alert_dialog(tr("Please park the car before selecting a model.")))
      return

    options = []
    for model in self._models:
      name = model.get("name", model.get("id", ""))
      added_at = model.get("addedAt", "")
      label = f"{name}  [{added_at}]" if added_at else name
      options.append(label)

    current_name = (self._params.get("DrivingModelName") or b"").decode("utf-8", "replace").strip()
    current_label = ""
    for i, model in enumerate(self._models):
      if model.get("name", "") == current_name:
        current_label = options[i]
        break

    def handle_selection(result: DialogResult):
      if result == DialogResult.CONFIRM and self._model_dialog is not None:
        idx = options.index(self._model_dialog.selection) if self._model_dialog.selection in options else -1
        if idx >= 0:
          self._start_download(self._models[idx])
      self._model_dialog = None

    self._model_dialog = MultiOptionDialog(
      tr("Select a Model"),
      options,
      current_label,
      callback=handle_selection,
    )
    gui_app.push_widget(self._model_dialog)

  def _start_download(self, model: dict):
    if self._is_downloading:
      return

    model_name = model.get("name", model.get("id", ""))
    base_url = model.get("baseUrl", "")
    files = model.get("files", {})

    if not base_url or not files:
      gui_app.push_widget(alert_dialog(tr("Invalid model data.")))
      return

    self._is_downloading = True
    self._select_btn.action_item.set_enabled(False)

    def _download():
      try:
        # Clean up tmp dir
        if MODELS_TMP_DIR.exists():
          shutil.rmtree(MODELS_TMP_DIR)
        MODELS_TMP_DIR.mkdir(parents=True, exist_ok=True)

        # Download each file
        for filename in REQUIRED_MODEL_FILES:
          if filename not in files:
            continue
          url = base_url.rstrip("/") + "/" + filename
          dest = MODELS_TMP_DIR / filename
          STATUS_FILE.write_text(f"downloading:{filename}")
          with urllib.request.urlopen(url, timeout=120) as resp:
            with open(dest, "wb") as f:
              shutil.copyfileobj(resp, f)

        # Check if we have ONNX files that need compilation
        onnx_files = [f for f in files if f.endswith(".onnx")]
        has_pkl = any(f.endswith("_tinygrad.pkl") for f in files)

        if onnx_files and not has_pkl:
          # Needs compilation
          STATUS_FILE.write_text("compiling:Starting compilation...")
          self._params.put("PendingModelName", model_name)
          self._params.put("DrivingModelName", f"{model_name} (Installing...)")
          compile_script = Path(BASEDIR) / "selfdrive/modeld/compile_model.py"
          subprocess.Popen(
            ["python3", str(compile_script), str(MODELS_TMP_DIR), model_name],
            close_fds=True,
          )
        else:
          # Pre-compiled, install directly
          _install_model(MODELS_TMP_DIR, model_name)

      except Exception as e:
        cloudlog.error(f"Model download/install failed: {e}")
        STATUS_FILE.write_text(f"error:{e}")
      finally:
        self._is_downloading = False
        self._select_btn.action_item.set_enabled(True)

    self._download_thread = threading.Thread(target=_download, daemon=True)
    self._download_thread.start()

  def _on_reset_model(self):
    def _confirm(result: DialogResult):
      if result == DialogResult.CONFIRM:
        _remove_custom_model()
        self._params.remove("DrivingModelName")
        self._params.remove("PendingModelName")
        if STATUS_FILE.exists():
          STATUS_FILE.unlink(missing_ok=True)

    dlg = ConfirmDialog(
      tr("Remove custom model and revert to the default model ({})?\n\nA restart is required.").format(DEFAULT_MODEL_NAME),
      tr("Reset"),
      callback=_confirm,
    )
    gui_app.push_widget(dlg)

  def show_event(self):
    self._scroller.show_event()
    self._update_items()

  def _update_items(self):
    # Refresh enabled state for reset button
    self._reset_btn.action_item.set_enabled(
      ui_state.is_offroad() and has_valid_custom_model(MODELS_DIR)
    )
    self._select_btn.action_item.set_enabled(
      ui_state.is_offroad() and not self._is_downloading
    )

  def _render(self, rect):
    self._update_items()
    self._scroller.render(rect)


def _install_model(tmp_dir: Path, display_name: str):
  """Install compiled/pre-built model files from tmp_dir to MODELS_DIR."""
  if MODELS_BACKUP_DIR.exists():
    shutil.rmtree(MODELS_BACKUP_DIR)
  if MODELS_DIR.exists():
    try:
      MODELS_DIR.rename(MODELS_BACKUP_DIR)
    except OSError:
      shutil.rmtree(MODELS_DIR)

  try:
    tmp_dir.rename(MODELS_DIR)
  except OSError:
    shutil.copytree(str(tmp_dir), str(MODELS_DIR))
    shutil.rmtree(tmp_dir)

  STATUS_FILE.write_text(f"done:{display_name}")
  Params().put("DrivingModelName", display_name)
  Params().remove("PendingModelName")


def _remove_custom_model():
  if MODELS_DIR.exists():
    shutil.rmtree(MODELS_DIR, ignore_errors=True)
  if MODELS_BACKUP_DIR.exists():
    shutil.rmtree(MODELS_BACKUP_DIR, ignore_errors=True)
  if MODELS_TMP_DIR.exists():
    shutil.rmtree(MODELS_TMP_DIR, ignore_errors=True)
