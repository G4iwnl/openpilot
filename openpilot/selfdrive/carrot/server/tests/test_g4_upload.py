import asyncio
import json

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from openpilot.selfdrive.carrot.server.features.dashcam import catalog, paths, routes, upload, upload_jobs
from tools.carrot_upload_server.server import Config, create_app  # noqa: TID251


def test_g4_target_is_independent_of_existing_server_and_token(monkeypatch):
  monkeypatch.setattr(upload, "read_web_settings", lambda: {
    "web_upload_url": "https://existing.example",
    "g4_upload_url": "https://owner.example/",
  })
  monkeypatch.setenv("CARROT_WEB_UPLOAD_TOKEN", "existing-server-token")
  monkeypatch.delenv("CARROT_G4_WEB_UPLOAD_URL", raising=False)
  assert upload.upload_target_settings("g4") == ("https://owner.example", "")


@pytest.mark.parametrize("target", ["https://attacker.example", "other", "g4,web"])
def test_unknown_target_cannot_start_a_job(target):
  async def run():
    upload_jobs.jobs().clear()
    app = web.Application()
    app.router.add_post("/start", routes.api_dashcam_upload_start)
    async with TestClient(TestServer(app)) as client:
      response = await client.post("/start", json={"target": target, "segments": ["00000cfb--69588de3d7--0"]})
      assert response.status == 400
      assert not upload_jobs.jobs()
  asyncio.run(run())


def test_g4_button_api_uploads_video_and_full_log_to_receiver(tmp_path, monkeypatch):
  segment = "00000cfb--69588de3d7--0"
  device = "0123456789abcdef"
  source = tmp_path / "realdata" / segment
  source.mkdir(parents=True)
  selected = {"qcamera.ts": b"dummy road video", "rlog.zst": b"dummy full route log"}
  for name, data in {**selected, "qlog.zst": b"auxiliary log", "dcamera.ts": b"unselected camera"}.items():
    (source / name).write_bytes(data)
  monkeypatch.setattr(catalog, "DASHCAM_ROOT", str(source.parent))
  monkeypatch.setattr(paths, "DASHCAM_ROOT", str(source.parent))
  monkeypatch.setattr(upload, "upload_metadata", lambda params: {"carName": "TEST_CAR", "dongleId": device})
  monkeypatch.setattr(upload, "read_web_settings", lambda: {"web_upload_url": "http://127.0.0.1:1"})
  monkeypatch.setenv("CARROT_WEB_UPLOAD_TOKEN", "existing-server-token")

  async def forbidden_discord(*args):
    raise AssertionError("G4 uploads must not send to the existing Discord webhook")

  monkeypatch.setattr(upload, "send_discord_webhook", forbidden_discord)

  async def run():
    upload_jobs.jobs().clear()
    receiver = create_app(Config(
      storage_root=tmp_path / "sorento",
      db_path=tmp_path / "state" / "uploads.sqlite3",
      min_free_bytes=0,
    ), start_cleanup=False)
    async with TestClient(TestServer(receiver)) as receiver_client:
      base_url = str(receiver_client.make_url("/")).rstrip("/")
      monkeypatch.setenv("CARROT_G4_WEB_UPLOAD_URL", base_url)
      app = web.Application()
      app.router.add_post("/summary", routes.api_dashcam_upload_summary)
      app.router.add_post("/start", routes.api_dashcam_upload_start)
      app.router.add_get("/job", routes.api_dashcam_upload_job)
      async with TestClient(TestServer(app)) as client:
        payload = {"target": "g4", "segments": [segment]}
        summary_response = await client.post("/summary", json=payload)
        summary = await summary_response.json()
        assert summary["serverUrl"] == base_url
        assert summary["target"] == "g4"
        assert {item["name"] for item in summary["summaries"][0]["files"]} == set(selected)
        start = await client.post("/start", json=payload)
        assert start.status == 200
        job_id = (await start.json())["job_id"]
        job = upload_jobs.jobs()[job_id]
        assert upload_jobs.snapshot(job)["target"] == "g4"
        await job["_task"]
        response = await client.get("/job", params={"id": job_id})
        snapshot = await response.json()
        assert snapshot["done"] and snapshot["status"] == "done"
        result = snapshot["result"]
        assert result["ok"] and result["target"] == "g4"
        assert result["serverUrl"] == base_url
        assert result["remoteBasePath"] == f"routes/TEST_CAR {device}/"
        assert result["webComplete"]["ok"]
        assert result["discord"]["skipped"]
        assert "OK · Open" not in result["shareText"]
        assert "### Open & Analyze" not in result["shareText"]
        stored = tmp_path / "sorento" / "routes" / f"TEST_CAR {device}" / segment
        assert {file.name: file.read_bytes() for file in stored.iterdir()} == selected
        manifests = list((tmp_path / "state" / "manifests" / device).glob("*.json"))
        assert len(manifests) == 1
        assert json.loads(manifests[0].read_text())["target"] == "g4"
    upload_jobs.jobs().clear()

  asyncio.run(run())
