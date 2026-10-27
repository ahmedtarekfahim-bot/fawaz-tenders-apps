# Close the running programs (window + background server) and install the newest Setup silently, then start it again.
param([string]$setup = "D:\شغل فواز\12 - GCC Tenders - برامج الكمبيوتر\GCC Tenders Setup 2.1.3.exe")
$names = "FAWAZ Gulf Directory", "FAWAZ CAPT Awards"
Get-Process -Name $names -ErrorAction SilentlyContinue | ForEach-Object { Write-Host "closing $($_.Name) ($($_.Id))"; Stop-Process -Id $_.Id -Force }
Start-Sleep -Seconds 3
if (-not (Test-Path $setup)) { Write-Host "Setup not found: $setup"; exit 1 }
Write-Host "installing $setup ..."
$p = Start-Process -FilePath $setup -ArgumentList "/S", "/restart" -PassThru
$p.WaitForExit(600000) | Out-Null
Write-Host "setup exit code: $($p.ExitCode)"
Start-Sleep -Seconds 10
Get-Process -Name $names -ErrorAction SilentlyContinue | ForEach-Object { Write-Host "running: $($_.Name) ($($_.Id))  $($_.Path)" }
try { Write-Host (Invoke-RestMethod -Uri "http://127.0.0.1:8766/api/me" -TimeoutSec 20 | ConvertTo-Json -Compress) } catch { Write-Host "server not up yet: $_" }
