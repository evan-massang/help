# notifier

Tiny Rust sidecar that surfaces memeterm alerts as Windows toasts. Listens
on `127.0.0.1:8788`; the backend POSTs to `/notify` whenever an alert's
delivery channel set includes `toast`.

## Build

```powershell
cd infra/notifier
cargo build --release
# Output at infra/notifier/target/release/notifier.exe
```

## Run

```powershell
./target/release/notifier.exe
```

Add to Windows startup so it auto-launches with the dashboard:

```powershell
$shortcut = "$env:APPDATA\Microsoft\Windows\Start Menu\Programs\Startup\memeterm-notifier.lnk"
$ws = New-Object -ComObject WScript.Shell
$lnk = $ws.CreateShortcut($shortcut)
$lnk.TargetPath = "$PWD\target\release\notifier.exe"
$lnk.Save()
```

## Smoke test

```bash
curl -X POST http://127.0.0.1:8788/notify \
  -H 'Content-Type: application/json' \
  -d '{"title": "memeterm", "body": "test alert", "sound": "watch"}'
```

The backend's `memeterm.alerts.notifier.post_toast` swallows connection
errors so a stopped sidecar never fails an alert delivery — toasts simply
don't show until the sidecar is back.
