import asyncio

import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

from openpilot.selfdrive.carrot import web_upload


@pytest.fixture
def retry_waits(monkeypatch):
  waits = []
  real_sleep = asyncio.sleep

  async def sleep(seconds):
    if seconds:
      waits.append(seconds)
    else:
      await real_sleep(0)

  monkeypatch.setattr(web_upload.asyncio, "sleep", sleep)
  return waits


def test_disconnected_file_restarts_at_zero_on_a_new_connection(tmp_path, retry_waits):
  contents = {"rlog.zst": b"original log", "qcamera.ts": b"original video" * 100000}
  for name, data in contents.items():
    (tmp_path / name).write_bytes(data)
  received = []
  transports = []

  async def receive(request):
    name = request.match_info["filename"]
    transports.append(request.transport)
    assert request.headers["Content-Length"] == request.headers["X-File-Size"] == str(len(contents[name]))
    assert "Transfer-Encoding" not in request.headers
    if name == "qcamera.ts" and len(received) == 1:
      received.append((name, await request.content.readexactly(1024)))
      request.transport.abort()
      return web.Response()
    data = await request.read()
    received.append((name, data))
    return web.json_response({"ok": True, "size": len(data)})

  async def run():
    app = web.Application(client_max_size=4 * 1024 * 1024)
    app.router.add_put("/api/v1/upload/device/route/{filename}", receive)
    async with TestServer(app) as server:
      assert await web_upload.upload_folder_to_web(str(tmp_path), "device", "route", str(server.make_url("/")), "token",
                                                   filenames=list(contents))

  asyncio.run(run())
  assert received == [("rlog.zst", contents["rlog.zst"]), ("qcamera.ts", contents["qcamera.ts"][:1024]),
                      ("qcamera.ts", contents["qcamera.ts"])]
  assert len(set(transports)) == 3
  assert retry_waits == [1]


@pytest.mark.parametrize("status", [502, 503, 504, None])
def test_temporary_gateway_or_connection_failure_retries_at_most_three_times(tmp_path, retry_waits, status):
  (tmp_path / "rlog.zst").write_bytes(b"log")
  received = []

  async def receive(request):
    received.append(await request.read())
    if status is None:
      request.transport.abort()
      return web.Response()
    return web.json_response({"ok": False, "error": "gateway unavailable"}, status=status)

  async def run():
    app = web.Application()
    app.router.add_put("/{path:.*}", receive)
    async with TestServer(app) as server:
      with pytest.raises(RuntimeError, match="route/rlog.zst: failed after 3 attempt"):
        await web_upload.upload_folder_to_web(str(tmp_path), "device", "route", str(server.make_url("/")), "token")

  asyncio.run(run())
  assert received == [b"log"] * 3
  assert retry_waits == [1, 3]


@pytest.mark.parametrize("status", [401, 403, 413, 429])
def test_authentication_and_quota_errors_are_not_retried(tmp_path, retry_waits, status):
  (tmp_path / "rlog.zst").write_bytes(b"log")
  received = []

  async def receive(request):
    received.append(await request.read())
    return web.json_response({"ok": False, "error": "rejected"}, status=status)

  async def run():
    app = web.Application()
    app.router.add_put("/{path:.*}", receive)
    async with TestServer(app) as server:
      with pytest.raises(RuntimeError, match=f"HTTP {status}"):
        await web_upload.upload_folder_to_web(str(tmp_path), "device", "route", str(server.make_url("/")), "token")

  asyncio.run(run())
  assert received == [b"log"]
  assert retry_waits == []


@pytest.mark.parametrize("change", ["source", "cancel"])
def test_retry_stops_if_source_changes_or_user_cancels(tmp_path, monkeypatch, change):
  path = tmp_path / "rlog.zst"
  path.write_bytes(b"log")
  received = []
  canceled = False

  async def sleep(seconds):
    nonlocal canceled
    if change == "source":
      path.write_bytes(b"changed source")
    else:
      canceled = True

  monkeypatch.setattr(web_upload.asyncio, "sleep", sleep)

  async def receive(request):
    received.append(await request.read())
    return web.json_response({"ok": False}, status=503)

  async def run():
    app = web.Application()
    app.router.add_put("/{path:.*}", receive)
    async with TestServer(app) as server:
      with pytest.raises(RuntimeError, match="file changed" if change == "source" else "upload canceled"):
        await web_upload.upload_folder_to_web(str(tmp_path), "device", "route", str(server.make_url("/")), "token",
                                             should_cancel=lambda: canceled)

  asyncio.run(run())
  assert received == [b"log"]


@pytest.mark.parametrize("body", ["not JSON", '{"ok":false,"error":"manifest rejected"}'])
def test_http_200_is_not_enough_to_confirm_completion(body):
  async def receive(request):
    return web.Response(text=body)

  async def run():
    app = web.Application()
    app.router.add_post("/api/v1/complete", receive)
    async with TestServer(app) as server:
      result = await web_upload.send_web_upload_complete(str(server.make_url("/")), "token", {"ok": True})
      assert not result["ok"] and result["status"] == 200

  asyncio.run(run())


@pytest.mark.parametrize("case", ["no-files", "empty-file", "symlink"])
def test_invalid_source_never_opens_a_connection(tmp_path, monkeypatch, case):
  if case == "empty-file":
    (tmp_path / "rlog.zst").touch()
  elif case == "symlink":
    source = tmp_path.parent / "source.zst"
    source.write_bytes(b"log")
    (tmp_path / "rlog.zst").symlink_to(source)

  def session(*args, **kwargs):
    raise AssertionError("invalid source must not open a connection")

  monkeypatch.setattr(web_upload, "ClientSession", session)
  with pytest.raises(RuntimeError):
    asyncio.run(web_upload.upload_folder_to_web(str(tmp_path), "device", "route", "https://example.test", "token",
                                               filenames=["rlog.zst"] if case == "symlink" else None))
