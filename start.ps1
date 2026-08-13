# Vault Assistant launcher for Windows PowerShell: checks everything,
# starts the stack and opens the app. Debian/Ubuntu, macOS and WSL:
# use start.sh instead.

Set-Location $PSScriptRoot

function Say($msg) { Write-Host "`n$msg" }
function Die($msg) { Say $msg; exit 1 }

# WHY THIS GATE EXISTS (added 2026-08-12): docker compose must run on
# the side that owns the repo files. A path starting with \\ means the
# repo lives inside WSL; compose launched from Windows then mounts an
# empty /app ("File does not exist: app.py" crash loop). So we hand
# the whole job to the WSL side and exit.
if ($PSScriptRoot.StartsWith("\\")) {
  Say "This repo lives inside WSL - delegating to the WSL side..."
  wsl.exe --cd "$PSScriptRoot" -e bash ./start.sh
  exit $LASTEXITCODE
}

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

# vault choice: asked on EVERY run through a small native window with
# buttons that SAY what they do (Keep / Choose... / Demo). The Demo
# button only exists when a custom vault is active — without one, the
# current vault already IS the demo. Closing the window keeps the
# current vault: the safe path. State lives only in .env's VAULT_PATH.
function Choose-Vault {
  $envFile = Join-Path $PSScriptRoot ".env"
  $current = ""
  if (Test-Path $envFile) {
    $m = Select-String -Path $envFile -Pattern '^VAULT_PATH=(.+)$' | Select-Object -Last 1
    if ($m) { $current = $m.Matches[0].Groups[1].Value }
  }
  $onDemo = [string]::IsNullOrWhiteSpace($current)
  $label = if ($onDemo) { "demo" } else { $current }

  $action = "keep"
  $typedFolder = ""
  try {
    Add-Type -AssemblyName System.Windows.Forms
    Add-Type -AssemblyName System.Drawing

    $form = New-Object Windows.Forms.Form
    $form.Text = "Vault Assistant"
    $form.FormBorderStyle = "FixedDialog"
    $form.MaximizeBox = $false
    $form.MinimizeBox = $false
    $form.StartPosition = "CenterScreen"
    $form.ClientSize = New-Object Drawing.Size(440, 184)

    $q = New-Object Windows.Forms.Label
    $q.Text = "Which vault should the assistant answer from?"
    $q.Font = New-Object Drawing.Font("Segoe UI", 11, [Drawing.FontStyle]::Bold)
    $q.SetBounds(20, 16, 400, 26)

    $c = New-Object Windows.Forms.Label
    $c.Text = "Current vault:  $label"
    $c.Font = New-Object Drawing.Font("Segoe UI", 8.75)
    $c.SetBounds(20, 50, 400, 68)

    $bKeep = New-Object Windows.Forms.Button
    $bKeep.Text = "Keep"
    $bKeep.SetBounds(20, 138, 100, 32)
    $bKeep.add_Click({ $form.Tag = "keep"; $form.Close() })

    $bChoose = New-Object Windows.Forms.Button
    $bChoose.Text = "Choose..."
    $bChoose.SetBounds(130, 138, 110, 32)
    $bChoose.add_Click({ $form.Tag = "choose"; $form.Close() })

    $form.Controls.AddRange(@($q, $c, $bKeep, $bChoose))

    if (-not $onDemo) {
      $bDemo = New-Object Windows.Forms.Button
      $bDemo.Text = "Demo"
      $bDemo.SetBounds(250, 138, 100, 32)
      $bDemo.add_Click({ $form.Tag = "demo"; $form.Close() })
      $form.Controls.Add($bDemo)
    }

    $form.AcceptButton = $bKeep
    $form.Tag = "keep"          # the X also keeps: the safe path
    [void]$form.ShowDialog()
    $action = [string]$form.Tag
    $form.Dispose()
  } catch {
    # no gui available (unusual shells): the same adaptive question in text
    $hint = if ($onDemo) { "Enter keeps, or type a folder path" }
            else { "Enter keeps, type a folder path, or 'demo'" }
    $typed = Read-Host "Current vault: $label - $hint"
    if ([string]::IsNullOrWhiteSpace($typed)) { $action = "keep" }
    elseif ($typed -eq "demo") { $action = "demo" }
    else { $action = "choose"; $typedFolder = $typed }
  }

  if ($action -eq "keep") { return }

  $folder = ""
  if ($action -eq "choose") {
    # VALIDATION LOOP 2026-08-13: never write a vault without notes.
    # The picker repeats until a folder WITH .md files is chosen, the
    # person switches to the demo, or cancels (= keep current).
    while ($true) {
      if ($typedFolder) { $folder = $typedFolder; $typedFolder = "" }
      else {
        $picker = New-Object Windows.Forms.FolderBrowserDialog
        $picker.Description = "Choose your vault folder"
        if ($picker.ShowDialog() -ne "OK") { return }   # cancel = keep
        $folder = $picker.SelectedPath
      }
      $ok = (Test-Path -LiteralPath $folder -PathType Container) -and
            (Get-ChildItem -LiteralPath $folder -Recurse -Filter *.md -File `
             -ErrorAction SilentlyContinue | Select-Object -First 1)
      if ($ok) { break }
      try {
        $r = [System.Windows.Forms.MessageBox]::Show(
              "That folder has no markdown notes.`n`nChoose another folder?  (No = use the demo vault)",
              "Vault Assistant",
              [System.Windows.Forms.MessageBoxButtons]::YesNo,
              [System.Windows.Forms.MessageBoxIcon]::Warning)
      } catch { $folder = ""; break }
      if ($r -ne "Yes") { $folder = ""; break }        # demo
    }
    # NO TRANSLATION 2026-08-13: this branch only runs on a C:\-hosted
    # repo (the gate delegates WSL-hosted repos), so compose runs on the
    # WINDOWS side - and Docker Desktop mounts \\wsl.localhost\... UNC
    # paths natively (verified with a live docker run). The old code
    # "translated" the path through the linux shell, which ate the
    # backslashes and wrote garbage; the correct move is to not touch
    # the path at all.
  }

  $lines = @()
  if (Test-Path $envFile) {
    $lines = @(Get-Content $envFile |
               Where-Object { $_ -notmatch '^VAULT_PATH=' -and $_ -notmatch '^#VAULT_CHOICE=' })
  }
  if ($folder) { $lines += "VAULT_PATH=$folder"; Say "Vault set: $folder" }
  else { Say "Vault: demo" }

  # utf-8 WITHOUT bom: docker compose chokes on a bom before the first key
  $utf8 = New-Object System.Text.UTF8Encoding($false)
  [System.IO.File]::WriteAllLines($envFile, [string[]]$lines, $utf8)
}

Choose-Vault

Say "Starting the stack - the first run downloads images and a basic local model (~4 GB)..."
docker compose up -d
if ($LASTEXITCODE -ne 0) {
  Say "The stack failed to start. The two usual causes:"
  Say "  - 'port is already allocated': change APP_PORT / ES_PORT / ... in .env and rerun"
  Say "  - no disk space: the first run needs about 4 GB free"
  Die "Details above; full logs: docker compose logs"
}

# C1 2026-08-13: hold until the one-shot ingest finishes building the
# index, so the browser never opens on a half-ready app.
Say "Indexing the vault (a first build takes about a minute)..."
# docker compose wait errors out when the one-shot ALREADY exited, so
# the container is inspected directly by its fixed name instead
while ((docker inspect -f '{{.State.Running}}' assistant_ingest 2>$null) -eq "true") {
  Start-Sleep -Seconds 2
}
$ingestRc = docker inspect -f '{{.State.ExitCode}}' assistant_ingest 2>$null
if ($ingestRc -ne "0") {
  Say "The vault indexing FAILED - the reason:"
  docker logs assistant_ingest 2>&1 | Select-Object -Last 3
  Say "The app will open anyway; pick another folder with this launcher, or use the Reingest button."
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
