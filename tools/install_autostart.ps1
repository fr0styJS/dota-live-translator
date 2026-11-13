# Registers autostart for the translator, from wherever the repo lives.
#   powershell -ExecutionPolicy Bypass -File tools\install_autostart.ps1
#   powershell -ExecutionPolicy Bypass -File tools\install_autostart.ps1 -Remove
param([switch]$Remove, [switch]$NoWatchdog)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$pyw = Join-Path $root ".venv\Scripts\pythonw.exe"
$watcher = Join-Path $root "tools\watch_dota.py"
$ensure = Join-Path $root "tools\ensure_watcher.py"
$taskName = "DotaTranslatorWatchdog"
$startup = [Environment]::GetFolderPath('Startup')
$lnkPath = Join-Path $startup "DotaTranslatorWatch.lnk"

if (-not (Test-Path $pyw)) {
  throw "No venv interpreter at $pyw - run setup.ps1 first."
}

if ($Remove) {
  if (Test-Path $lnkPath) { Remove-Item $lnkPath -Force; "removed startup shortcut" }
  Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue
  "removed scheduled task $taskName"
  return
}

# 1. logon shortcut -> the watcher (instant start when you log in)
$ws = New-Object -ComObject WScript.Shell
$lnk = $ws.CreateShortcut($lnkPath)
$lnk.TargetPath = $pyw
$lnk.Arguments = "`"$watcher`""
$lnk.WorkingDirectory = $root
$lnk.WindowStyle = 7
$lnk.Description = "Starts the Dota translator backend when Dota 2 opens"
$lnk.Save()
"startup shortcut: $lnkPath"

# 2. every-minute watchdog -> restarts the watcher if it was killed
if ($NoWatchdog) { "watchdog skipped (-NoWatchdog)"; return }

Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue
$act = New-ScheduledTaskAction -Execute $pyw -Argument "`"$ensure`"" -WorkingDirectory $root
$trg = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) `
        -RepetitionInterval (New-TimeSpan -Minutes 1) `
        -RepetitionDuration (New-TimeSpan -Days 3650)
$set = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
        -MultipleInstances IgnoreNew -Hidden -StartWhenAvailable `
        -ExecutionTimeLimit (New-TimeSpan -Minutes 5)
$prn = New-ScheduledTaskPrincipal -UserId ("{0}\{1}" -f $env:USERDOMAIN, $env:USERNAME) `
        -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskName $taskName -Action $act -Trigger $trg -Settings $set -Principal $prn `
  -Description "Restarts the Dota translator watcher within a minute if it dies." | Out-Null
"scheduled task: $taskName (every minute)"
