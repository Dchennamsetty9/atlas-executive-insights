# Setup Windows Task Scheduler for weekly data refresh
# Run this PowerShell script as Administrator

$TaskName = "Atlas-Executive-Insights-Weekly-Refresh"
$ScriptPath = "$PSScriptRoot\refresh_weekly.py"
$PythonPath = (Get-Command python).Source
$WorkingDir = Split-Path -Parent $ScriptPath

# Create a scheduled task that runs every Sunday at 2 AM
$Action = New-ScheduledTaskAction -Execute $PythonPath -Argument $ScriptPath -WorkingDirectory $WorkingDir

$Trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Sunday -At 2am

$Settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -DontStopOnIdleEnd -AllowStartIfOnBatteries

# Register the task
Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Settings $Settings -Description "Weekly data refresh for Atlas Executive Insights dashboard"

Write-Host "✅ Scheduled task created: $TaskName"
Write-Host "📅 Runs every Sunday at 2:00 AM"
Write-Host "📂 Script: $ScriptPath"
Write-Host ""
Write-Host "To view the task: taskschd.msc"
Write-Host "To run manually: schtasks /run /tn `"$TaskName`""
