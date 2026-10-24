# Where is claude.exe on this PC (the Claude desktop app moves it on updates)
$places = @("$env:APPDATA\Claude", "$env:LOCALAPPDATA\AnthropicClaude", "$env:LOCALAPPDATA\Programs", "$env:USERPROFILE\.local\bin")
$places += Get-ChildItem "$env:LOCALAPPDATA\Packages" -Directory -Filter "*Claude*" -ErrorAction SilentlyContinue | ForEach-Object { $_.FullName }
foreach ($p in $places) {
    if (Test-Path $p) {
        Write-Host "== $p"
        Get-ChildItem $p -Recurse -Filter "claude*.exe" -ErrorAction SilentlyContinue | Select-Object -First 8 | ForEach-Object { Write-Host "   $($_.FullName)  $($_.LastWriteTime)" }
    }
}
Get-Command claude -ErrorAction SilentlyContinue | ForEach-Object { Write-Host "PATH: $($_.Source)" }
