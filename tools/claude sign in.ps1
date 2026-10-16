# One-time sign-in of Claude Code on this PC, so the program can run the Claude routines
# (from its button and from the phone). Uses the copy that comes with the Claude desktop app
# (a packaged app: its real folder is under %LOCALAPPDATA%\Packages\Claude_*\LocalCache\Roaming).
Get-ChildItem env: | Where-Object { $_.Name -match '^(CLAUDE|ANTHROPIC)' } | ForEach-Object { Remove-Item ("env:" + $_.Name) }
$roots = @("$env:APPDATA\Claude\claude-code")
$roots += Get-ChildItem "$env:LOCALAPPDATA\Packages" -Directory -Filter "*Claude*" -ErrorAction SilentlyContinue |
    ForEach-Object { Join-Path $_.FullName "LocalCache\Roaming\Claude\claude-code" }
$exe = $null
foreach ($r in $roots) {
    if (-not $exe -and (Test-Path $r)) {
        $exe = Get-ChildItem $r -Recurse -Filter claude.exe -ErrorAction SilentlyContinue |
            Sort-Object LastWriteTime -Descending | Select-Object -First 1
    }
}
if (-not $exe) { Write-Host "Claude Code not found. Looked in:"; $roots | ForEach-Object { Write-Host "  $_  (exists: $(Test-Path $_))" }; exit 1 }
Write-Host "Claude Code: $($exe.FullName)"
& $exe.FullName auth login
& $exe.FullName auth status
