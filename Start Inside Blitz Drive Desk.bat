@echo off
setlocal
cd /d "%~dp0"

powershell -NoProfile -ExecutionPolicy Bypass -Command "$url='http://127.0.0.1:8765/Inside%%20Blitz%%20Drive%%20Desk.html'; try { $r=Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 1 -ErrorAction Stop; if ($r.StatusCode -eq 200) { Start-Process $url; exit 0 } } catch {}; try { Start-Process -FilePath 'python' -ArgumentList 'serve_drive_desk.py' -WorkingDirectory (Get-Location).Path } catch { exit 1 }; $deadline=(Get-Date).AddSeconds(20); while ((Get-Date) -lt $deadline) { try { $r=Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 1 -ErrorAction Stop; if ($r.StatusCode -eq 200) { Start-Process $url; exit 0 } } catch {}; Start-Sleep -Milliseconds 250 }; exit 1"
if errorlevel 1 (
  echo Could not start the Drive Desk server. Verify Python is installed and try again.
  pause
)

endlocal