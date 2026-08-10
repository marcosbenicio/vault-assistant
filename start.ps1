# Vault Assistant launcher for Windows PowerShell: checks everything,
# starts the stack and opens the app. Debian/Ubuntu, macOS and WSL:
# use start.sh instead.

Set-Location $PSScriptRoot

function Say($msg) { Write-Host "`n$msg" }
function Die($msg) { Say $msg; exit 1 }

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
  Say "Docker not found. Install Docker Desktop:"
  Say "  https://www.docker.com/products/docker-desktop/"
  Die "Then run start.ps1 again."
}

docker info *> $null
if ($LASTEXITCODE -ne 0) {
  Die "Docker is installed but not running. Start Docker Desktop, wait for the whale icon, and retry."
}

docker compose version *> $null
if ($LASTEXITCODE -ne 0) {
  Die "Docker Compose v2 not found. Update Docker Desktop."
}

# vault choice: asked once, BEFORE the stack rises, because the mount
# happens on the way up. The answer lives in .env; delete the
# VAULT_PATH / #VAULT_CHOICE lines there to be asked again.
function Choose-Vault {
  $folder = ""
  try {
    Add-Type -AssemblyName System.Windows.Forms
    $r = [System.Windows.Forms.MessageBox]::Show(
          "Answer from your own notes folder?`n`nYes: choose a folder.   No: use the demo vault.",
          "Vault Assistant",
          [System.Windows.Forms.MessageBoxButtons]::YesNo,
          [System.Windows.Forms.MessageBoxIcon]::Question)
    if ($r -eq "Yes") {
      $picker = New-Object System.Windows.Forms.FolderBrowserDialog
      $picker.Description = "Choose your notes folder"
      if ($picker.ShowDialog() -eq "OK") { $folder = $picker.SelectedPath }
    }
  } catch {
    # gui unavailable (unusual shells): fall back to a typed path
    $folder = Read-Host "Path to your notes folder (Enter = demo vault)"
  }

  $envFile = Join-Path $PSScriptRoot ".env"
  $lines = @()
  if (Test-Path $envFile) {
    $lines = @(Get-Content $envFile | Where-Object { $_ -notmatch '^VAULT_PATH=' })
  }

  if ([string]::IsNullOrWhiteSpace($folder)) {
    Say "Using the demo vault. (Your own notes later: rerun after deleting #VAULT_CHOICE from .env)"
    $lines += "#VAULT_CHOICE=demo"
  } elseif (-not (Test-Path -LiteralPath $folder -PathType Container)) {
    Say "Not a folder: $folder - staying on the demo vault."
    $lines += "#VAULT_CHOICE=demo"
  } else {
    # a folder that came back as a \\wsl UNC path must be translated
    # to its linux form before it can be mounted; refuse rather than
    # write a path the mount cannot serve
    if ($folder.StartsWith("\\")) {
      $converted = ""
      try { $converted = (wsl wslpath -a "$folder" 2>$null).Trim() } catch {}
      if ($converted -and $converted.StartsWith("/")) {
        $folder = $converted
      } else {
        Say "Could not translate the WSL path: $folder"
        Say "Staying on the demo vault; from a WSL terminal, use: make vault VAULT=/abs/path"
        $lines += "#VAULT_CHOICE=demo"
        $folder = ""
      }
    }
    if ($folder) {
      $lines += "VAULT_PATH=$folder"
      Say "Vault set: $folder"
    }
  }

  # utf-8 WITHOUT bom: docker compose chokes on a bom before the first key
  $utf8 = New-Object System.Text.UTF8Encoding($false)
  [System.IO.File]::WriteAllLines($envFile, [string[]]$lines, $utf8)
}

$envPath = Join-Path $PSScriptRoot ".env"
$asked = (Test-Path $envPath) -and
         (Select-String -Path $envPath -Pattern '^VAULT_PATH=|^#VAULT_CHOICE=demo' -Quiet)
if (-not $asked) { Choose-Vault }

Say "Starting the stack - the first run downloads images and a basic local model (~4 GB)..."
docker compose up -d
if ($LASTEXITCODE -ne 0) {
  Say "The stack failed to start. The two usual causes:"
  Say "  - 'port is already allocated': change APP_PORT / ES_PORT / ... in .env and rerun"
  Say "  - no disk space: the first run needs about 4 GB free"
  Die "Details above; full logs: docker compose logs"
}

$port = 8501
if (Test-Path .env) {
  $m = Select-String -Path .env -Pattern '^APP_PORT=(\d+)' | Select-Object -Last 1
  if ($m) { $port = $m.Matches[0].Groups[1].Value }
}

Say "Waiting for the app on port $port (first run can take a few minutes)..."
for ($i = 1; $i -le 150; $i++) {
  try {
    Invoke-WebRequest "http://localhost:$port/_stcore/health" -UseBasicParsing -TimeoutSec 2 *> $null
    Say "Ready: http://localhost:$port"
    Start-Process "http://localhost:$port"
    Say "No OpenAI key? The basic local model already answers."
    Say "Stop everything: docker compose down"
    exit 0
  } catch {
    if ($i % 15 -eq 0) { Say "Still starting (downloads in progress)..." }
    Start-Sleep -Seconds 2
  }
}
Die "The app did not come up after 5 minutes. Check: docker compose logs app"
