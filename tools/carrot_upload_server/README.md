# Carrot upload server

This is the HTTP(S) receiver for public Carrot dashcam and tmux uploads. Users
do not create or enter tokens. A client requests a short-lived session that is
bound to its Dongle ID and source IP.

Sessions last four hours. If a mobile connection changes IP, clients obtain a
fresh session instead of bypassing the server's IP binding.

The supplied DSM compose file sets both `CARROT_DAILY_DEVICE_QUOTA_BYTES` and
`CARROT_DAILY_IP_QUOTA_BYTES` to `0`, disabling daily transfer caps. Transfer
accounting continues without rejecting requests based on cumulative volume.
Without these environment overrides, the server defaults are 1 GiB per device
and 8 GiB per IP per UTC day. Health and session responses explicitly report
whether each daily cap is disabled.

There is no bandwidth throttle. Three concurrent uploads per device, sixteen
globally, 512 MiB per file, a 10 GiB free-space floor, and safe path validation
remain in effect. Existing files are never removed automatically.

## DSM deployment

1. Copy this directory to `/volume1/docker/carrot-upload`.
2. Create a Container Manager project from `compose.dsm.yml`.
3. The compose file runs as DSM UID 1038/GID 100 (with the DSM administrators
   ACL group, GID 101) and bind-mounts the existing `/volume1/sorento`
   folder so tmux diagnostics retain their original branch-based path. No DSM
   password or FTP login is passed to the container. Adjust the numeric UID
   only if this DSM account changes.
4. Add DSM reverse proxy `https://upload.g4nas.my:443` to
   `http://127.0.0.1:18080` and assign a trusted certificate for that hostname.
5. Keep port 18080 bound to loopback. Do not publish the upload directory.

Verify `GET /api/v1/health`, automatic session creation, a test segment, and a
tmux upload before disabling the old transfer service and removing its account.

Dashcam files retain the original FTP-era layout at
`/volume1/sorento/routes/<CarName> <DongleID>/<segment>`. Tmux files use
`/volume1/sorento/<GitBranch>/<CarName> <DongleID>/<reason>-<time>-<branch>.txt`.
Strict server-side path validation confines web writes to the expected route
and branch/device layouts, and there is no public download API. Completion
manifests and quota/session state stay in the hidden
`/volume1/sorento/tmux/.state` directory. The receiver never scans or deletes
the existing Openpilot tree.
