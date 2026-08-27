param(
    [string]$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path,
    [string]$TaskName = "Guitteum-Regwatch-Daily",
    [string]$DailyAt = "06:30"
)

$ErrorActionPreference = "Stop"
$runScript = (Resolve-Path (Join-Path $RepoRoot "regwatch\scripts\run_daily.ps1")).Path
$time = [datetime]::ParseExact($DailyAt, "HH:mm", [Globalization.CultureInfo]::InvariantCulture)
$argument = "-NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$runScript`" -RepoRoot `"$RepoRoot`""
$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $argument -WorkingDirectory $RepoRoot
$trigger = New-ScheduledTaskTrigger -Daily -At $time
$settings = New-ScheduledTaskSettingsSet `
    -MultipleInstances IgnoreNew `
    -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Hours 1)
$principal = New-ScheduledTaskPrincipal `
    -UserId ([Security.Principal.WindowsIdentity]::GetCurrent().Name) `
    -LogonType Interactive `
    -RunLevel Limited

$task = New-ScheduledTask -Action $action -Trigger $trigger -Settings $settings -Principal $principal
Register-ScheduledTask -TaskName $TaskName -InputObject $task -Force | Out-Null
Get-ScheduledTask -TaskName $TaskName | Select-Object TaskName, State
