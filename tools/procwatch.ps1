param([int]$Seconds = 90, [int]$IntervalMs = 150)
$root = Split-Path -Parent $PSScriptRoot
$log = Join-Path $root "logs\procwatch.log"
New-Item -ItemType Directory -Force -Path (Split-Path $log) | Out-Null
if (Test-Path $log) { Remove-Item $log -Force }
function W($s) { $s | Out-File $log -Append -Encoding utf8 }

$script:known = @{}
$initial = Get-CimInstance Win32_Process | Select-Object ProcessId, ParentProcessId, Name, CreationDate
foreach ($p in $initial) { $script:known[[int]$p.ProcessId] = $p }

W "=== watch start $(Get-Date -Format HH:mm:ss.fff) interval=${IntervalMs}ms ==="

$deadline = (Get-Date).AddSeconds($Seconds)
while ((Get-Date) -lt $deadline) {
  $snap = Get-CimInstance Win32_Process | Select-Object ProcessId, ParentProcessId, Name, CreationDate
  $now = @{}
  foreach ($p in $snap) { $now[[int]$p.ProcessId] = $p }

  foreach ($id in $now.Keys) {
    if (-not $script:known.ContainsKey($id)) {
      $p = $now[$id]
      $parentName = ''
      if ($now.ContainsKey([int]$p.ParentProcessId)) { $parentName = $now[[int]$p.ParentProcessId].Name }
      elseif ($script:known.ContainsKey([int]$p.ParentProcessId)) { $parentName = $script:known[[int]$p.ParentProcessId].Name + '(gone)' }
      $cmd = ''
      try { $cmd = (Get-CimInstance Win32_Process -Filter "ProcessId=$id" -ErrorAction Stop).CommandLine } catch { $cmd = '<exited before read>' }
      if ($null -eq $cmd) { $cmd = '' }
      if ($cmd.Length -gt 220) { $cmd = $cmd.Substring(0,220) }
      W ("{0} BIRTH pid={1} ppid={2} parent={3} name={4} cmd={5}" -f (Get-Date -Format HH:mm:ss.fff), $id, $p.ParentProcessId, $parentName, $p.Name, $cmd)
    }
  }
  foreach ($id in @($script:known.Keys)) {
    if (-not $now.ContainsKey($id)) {
      $p = $script:known[$id]
      W ("{0} DEATH pid={1} name={2}" -f (Get-Date -Format HH:mm:ss.fff), $id, $p.Name)
    }
  }
  $script:known = $now
  Start-Sleep -Milliseconds $IntervalMs
}
W "=== watch end $(Get-Date -Format HH:mm:ss.fff) ==="

