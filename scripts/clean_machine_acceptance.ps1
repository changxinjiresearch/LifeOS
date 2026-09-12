param(
  [Parameter(Mandatory=$true)][string]$CoreExe,
  [Parameter(Mandatory=$true)][string]$Installer
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$root = Join-Path $env:TEMP ("nextplan-clean-machine-" + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $root | Out-Null
$db = Join-Path $root 'nextplan.db'
$desktopToken = 'clean-machine-desktop-token'
$base = 'http://127.0.0.1:47123'

function Wait-Health {
  param([int]$Seconds = 30)
  $deadline = (Get-Date).AddSeconds($Seconds)
  do {
    try {
      $h = Invoke-RestMethod -Uri "$base/healthz" -Method Get -TimeoutSec 2
      if ($h.status -eq 'ok') { return $h }
    } catch {}
    Start-Sleep -Milliseconds 350
  } while ((Get-Date) -lt $deadline)
  throw 'Local Core did not become healthy'
}

function Start-Core {
  $env:NEXTPLAN_LOCAL_DB = $db
  $env:NEXTPLAN_LOCAL_PORT = '47123'
  $env:NEXTPLAN_LOCAL_BOOTSTRAP_TOKEN = $desktopToken
  return Start-Process -FilePath $CoreExe -PassThru -WindowStyle Hidden
}

function Stop-Tree {
  param($Process)
  if ($Process -and -not $Process.HasExited) {
    Stop-Process -Id $Process.Id -Force -ErrorAction SilentlyContinue
    $Process.WaitForExit(5000) | Out-Null
  }
}

$headers = @{ Authorization = "Bearer $desktopToken" }
$core = $null
$app = $null
try {
  # Standalone packaged Core: no Python process is involved.
  $core = Start-Core
  $health = Wait-Health
  if ($health.runtime -ne 'nextplan-local-core-v4' -or $health.schema_version -ne 3) { throw 'Unexpected packaged Core runtime' }

  $code = (Invoke-RestMethod -Uri "$base/pairing/code" -Method Post -Headers $headers -ContentType 'application/json' -Body '{}').code
  $pairHeaders = @{ Origin = 'chrome-extension://cleanmachine' }
  $paired = Invoke-RestMethod -Uri "$base/pairing/complete" -Method Post -Headers $pairHeaders -ContentType 'application/json' -Body (@{ code=$code; extension_id='cleanmachine' } | ConvertTo-Json)
  $extensionHeaders = @{ Authorization = "Bearer $($paired.token)"; Origin = 'chrome-extension://cleanmachine' }

  $create = @{ action = @{ action='create_project'; project_id='clean-machine-project'; name='Clean Machine Project'; category='Acceptance' } } | ConvertTo-Json -Depth 5
  $receipt = Invoke-RestMethod -Uri "$base/actions/execute" -Method Post -Headers $extensionHeaders -ContentType 'application/json' -Body $create
  if ($receipt.status -notin @('applied','ok')) { throw 'Could not create clean-machine project' }

  $backup = Invoke-RestMethod -Uri "$base/backup/export" -Method Post -Headers $headers -ContentType 'application/json' -Body '{}'
  if (-not (Test-Path $backup.path)) { throw 'Backup ZIP was not created' }
  Stop-Tree $core; $core = $null

  # Persistence across a complete Core restart.
  $core = Start-Core
  $health2 = Wait-Health
  $state = Invoke-RestMethod -Uri "$base/state" -Method Get -Headers $extensionHeaders
  if (-not ($state.projects | Where-Object { $_.id -eq 'clean-machine-project' })) { throw 'Canonical state did not persist across restart' }
  Stop-Tree $core; $core = $null

  # Install the real NSIS bundle. Force an invalid Python path: if the desktop
  # accidentally falls back to Python, this test cannot reach /healthz.
  Start-Process -FilePath $Installer -ArgumentList '/S' -Wait
  $candidates = @(
    (Join-Path $env:LOCALAPPDATA 'NextPlan\NextPlan.exe'),
    (Join-Path $env:LOCALAPPDATA 'Programs\NextPlan\NextPlan.exe')
  )
  $desktopExe = $candidates | Where-Object { Test-Path $_ } | Select-Object -First 1
  if (-not $desktopExe) {
    $desktopExe = Get-ChildItem -Path $env:LOCALAPPDATA -Filter 'NextPlan.exe' -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1 -ExpandProperty FullName
  }
  if (-not $desktopExe) { throw 'Installed NextPlan.exe was not found' }

  $env:NEXTPLAN_LOCAL_PYTHON = 'C:\definitely-not-python\python.exe'
  Remove-Item Env:NEXTPLAN_LOCAL_DB -ErrorAction SilentlyContinue
  Remove-Item Env:NEXTPLAN_LOCAL_BOOTSTRAP_TOKEN -ErrorAction SilentlyContinue
  $app = Start-Process -FilePath $desktopExe -PassThru
  $installedHealth = Wait-Health 45
  if ($installedHealth.runtime -ne 'nextplan-local-core-v4') { throw 'Installed desktop did not launch bundled Local Core v4' }
  if (-not $installedHealth.integrity.ok) { throw 'Installed desktop database integrity failed' }

  Write-Host "CLEAN_MACHINE_ACCEPTANCE_PASS"
  Write-Host "Installer=$Installer"
  Write-Host "InstalledExe=$desktopExe"
  Write-Host "Runtime=$($installedHealth.runtime)"
  Write-Host "Schema=$($installedHealth.schema_version)"
} finally {
  Stop-Tree $core
  Stop-Tree $app
  Get-NetTCPConnection -LocalPort 47123 -State Listen -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }
}
