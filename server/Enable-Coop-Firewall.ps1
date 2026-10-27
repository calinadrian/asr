$ErrorActionPreference = 'Stop'
# Run once in an administrator PowerShell. The rule allows only the ASR server's own Python.
$python = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\tools\python\python.exe'))
if (-not (Test-Path -LiteralPath $python)) { throw 'Missing tools\python\python.exe.' }
foreach ($old in 'WorldOfSurvive-Coop-TCP', 'ASR-Server-TCP') {
    if (Get-NetFirewallRule -Name $old -ErrorAction SilentlyContinue) { Remove-NetFirewallRule -Name $old -ErrorAction Stop }
}
New-NetFirewallRule -Name 'ASR-Server-TCP' -DisplayName 'ASR server' -Direction Inbound -Action Allow -Protocol TCP -LocalPort 47770 -Program $python -InterfaceAlias 'Ethernet' -Profile Public -ErrorAction Stop | Out-Null
Write-Host 'Allowed TCP 47770 for the ASR server on Ethernet / Public only.'
