$ErrorActionPreference = 'Stop'
$gamePython = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\Azeroth Survivors Together\.coop-runtime\python.exe'))
if (-not (Test-Path -LiteralPath $gamePython)) { throw 'Install the co-op game first.' }
$ruleName = 'WorldOfSurvive-Coop-TCP'
if (Get-NetFirewallRule -Name $ruleName -ErrorAction SilentlyContinue) {
    Remove-NetFirewallRule -Name $ruleName -ErrorAction Stop
}
New-NetFirewallRule -Name $ruleName -DisplayName 'Azeroth Survivors: Realms public co-op' -Direction Inbound -Action Allow -Protocol TCP -LocalPort 47770,47771 -Program $gamePython -InterfaceAlias 'Ethernet' -Profile Public -ErrorAction Stop | Out-Null
Write-Host 'Allowed TCP 47770 (directory) and 47771 (relay) for the game runtime on Ethernet / Public only.'
