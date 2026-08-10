#!/usr/bin/env bash
# Vault Assistant launcher: checks everything, starts the stack and
# opens the app in your browser. Supports Debian/Ubuntu, macOS, WSL
# and Git Bash. Windows PowerShell: use start.ps1.
set -u

# always work from the repo root, wherever this was called from
cd "$(dirname "$0")"

say() { printf '\n%s\n' "$*"; }
die() { say "$*"; exit 1; }

# native dialog when launched without a terminal (Linux double-click)
if [ ! -t 0 ] && command -v zenity >/dev/null 2>&1; then
  zenity --question --title="Vault Assistant" \
         --text="Start the Vault Assistant?" || exit 0
fi

# 1. curl: the health check needs it (minimal Debian/Ubuntu ships without)
if ! command -v curl >/dev/null 2>&1; then
  die "curl not found. Install it and rerun:  sudo apt install curl"
fi

# 2. docker installed?
if ! command -v docker >/dev/null 2>&1; then
  say "Docker not found. Install it first:"
  say "  Debian/Ubuntu: https://docs.docker.com/engine/install/ubuntu/"
  say "  macOS:         https://www.docker.com/products/docker-desktop/"
  die "Then run ./start.sh again."
fi

# 3. docker usable? (a stopped daemon and a missing permission are
#    different problems with different fixes)
docker_err=$(docker info 2>&1 >/dev/null)
if [ -n "$docker_err" ]; then
  case "$docker_err" in
    *ermission*)
      say "Docker is installed, but your user cannot use it yet. Fix:"
      say "  sudo usermod -aG docker \$USER"
      die "Then log out, log back in, and run ./start.sh again." ;;
    *)
      die "Docker is installed but not running. Start it (Docker Desktop on macOS/WSL; 'sudo systemctl start docker' on Debian/Ubuntu) and retry." ;;
  esac
fi

# 4. compose v2?
if ! docker compose version >/dev/null 2>&1; then
  die "Docker Compose v2 not found (the 'docker compose' command). Update Docker."
fi

# 4.5 vault choice: asked once, BEFORE the stack rises, because the
#     mount happens on the way up. The answer lives in .env; delete
#     the VAULT_PATH / #VAULT_CHOICE lines there to be asked again.
choose_vault() {
  folder=""
  if command -v zenity >/dev/null 2>&1 && [ -n "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ]; then
    # graphical path: a question dialog, then the native folder picker.
    # Cancel or closing either window means the demo vault.
    if zenity --question --title="Vault Assistant" \
              --text="Which notes should the assistant answer from?" \
              --ok-label="My own folder..." --cancel-label="Demo vault"; then
      folder=$(zenity --file-selection --directory \
                      --title="Choose your notes folder" || true)
    fi
  elif [ -t 0 ]; then
    # no dialogs available, but there is a terminal: ask in text
    say "Which notes should the assistant answer from?"
    read -rp "Path to your notes folder (Enter = demo vault): " folder
  else
    # no dialog AND no terminal (rare): stay quietly on the demo and
    # do not record a choice, so an interactive run can still ask
    return 0
  fi

  if [ -z "$folder" ]; then
    say "Using the demo vault. (Your own notes later: make vault VAULT=/abs/path)"
    printf '#VAULT_CHOICE=demo\n' >> .env
    return 0
  fi

  # typed-path hygiene: a literal ~, a Windows path pasted inside WSL,
  # or a relative path all get resolved before validation
  folder="${folder/#\~/$HOME}"
  case "$folder" in
    [A-Za-z]:\\*|[A-Za-z]:/*)
      command -v wslpath >/dev/null 2>&1 && folder=$(wslpath -a "$folder" 2>/dev/null || printf '%s' "$folder") ;;
  esac
  case "$folder" in
    /*) ;;
    *) folder=$(realpath "$folder" 2>/dev/null || printf '%s' "$folder") ;;
  esac

  if [ ! -d "$folder" ]; then
    say "Not a folder: $folder"
    say "Staying on the demo vault. (Try again later: make vault VAULT=/abs/path)"
    printf '#VAULT_CHOICE=demo\n' >> .env
    return 0
  fi

  sed -i '/^VAULT_PATH=/d' .env 2>/dev/null || true
  printf 'VAULT_PATH=%s\n' "$folder" >> .env
  say "Vault set: $folder  (back to the demo: make vault VAULT=demo)"
}

grep -Eq '^VAULT_PATH=|^#VAULT_CHOICE=demo' .env 2>/dev/null || choose_vault

# 5. start the stack, with the classic failures explained
say "Starting the stack — the first run downloads images and a basic local model (~4 GB)..."
if ! docker compose up -d; then
  say "The stack failed to start. The two usual causes:"
  say "  - 'port is already allocated': another service uses that port;"
  say "    change APP_PORT / ES_PORT / ... in .env and rerun"
  say "  - no disk space: the first run needs about 4 GB free"
  die "Details in the messages above; full logs: docker compose logs"
fi

# 6. wait for the app, patiently: the first boot also downloads the
#    embedding model. APP_PORT read without sourcing .env (a malformed
#    line there must not kill the launcher).
PORT=$(grep -E '^APP_PORT=' .env 2>/dev/null | tail -1 | cut -d= -f2)
PORT="${PORT:-8501}"
say "Waiting for the app on port ${PORT} (first run can take a few minutes)..."
tries=0
until curl -fsS "http://localhost:${PORT}/_stcore/health" >/dev/null 2>&1; do
  tries=$((tries + 1))
  if [ "$tries" -ge 150 ]; then
    die "The app did not come up after 5 minutes. Check: docker compose logs app"
  fi
  [ $((tries % 15)) -eq 0 ] && say "Still starting (downloads in progress)..."
  sleep 2
done

say "Ready: http://localhost:${PORT}"
# open the browser: xdg-open (Linux), open (macOS),
# powershell.exe (WSL opens the Windows browser)
if command -v xdg-open >/dev/null 2>&1; then xdg-open "http://localhost:${PORT}" >/dev/null 2>&1 || true
elif command -v open >/dev/null 2>&1; then open "http://localhost:${PORT}" || true
elif command -v powershell.exe >/dev/null 2>&1; then powershell.exe -NoProfile Start-Process "http://localhost:${PORT}" >/dev/null 2>&1 || true
fi

say "No OpenAI key? The basic local model already answers."
say "Useful commands: make urls | make vault VAULT=/abs/path | docker compose down"