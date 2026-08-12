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

# 4.5 vault choice: asked on EVERY run, with the current choice as the
#     one-keypress default (Enter keeps it). The state lives only in
#     .env's VAULT_PATH: present = that folder, absent = the demo.
#     (Changed 2026-08-12: the old ask-once #VAULT_CHOICE marker is
#     gone — asking every run makes the launcher also the place where
#     the vault gets SWITCHED, not only chosen the first time.)
choose_vault() {
  current=$(grep -E '^VAULT_PATH=' .env 2>/dev/null | tail -1 | cut -d= -f2-)
  current_label="${current:-demo}"
  folder=""

  if command -v zenity >/dev/null 2>&1 && [ -n "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ]; then
    # buttons say what they do; Demo only offered when NOT already on it
    if [ -n "$current" ]; then
      out=$(zenity --question --title="Vault Assistant" \
                   --text="Which vault should the assistant answer from?\n\nCurrent vault: ${current_label}" \
                   --ok-label="Keep" --cancel-label="Choose..." \
                   --extra-button="Demo" 2>/dev/null); rc=$?
      if [ "$rc" -eq 0 ]; then return 0; fi
      if [ "$out" = "Demo" ]; then
        sed -i '/^VAULT_PATH=/d;/^#VAULT_CHOICE=/d' .env 2>/dev/null || true
        say "Vault: demo"
        return 0
      fi
    else
      zenity --question --title="Vault Assistant" \
             --text="Which vault should the assistant answer from?\n\nCurrent vault: demo" \
             --ok-label="Keep" --cancel-label="Choose..." && return 0
    fi
    folder=$(zenity --file-selection --directory \
                    --title="Choose your vault folder" || true)
    [ -z "$folder" ] && return 0    # picker cancelled = keep, the safe path
  elif [ -t 0 ]; then
    say "Which vault should the assistant answer from?"
    say "Current vault: ${current_label}"
    # the zenity tip, exactly where the person would miss the dialogs
    if command -v apt >/dev/null 2>&1 && ! command -v zenity >/dev/null 2>&1; then
      say "Tip: want graphical dialogs here? Install once with:  sudo apt install zenity"
    fi
    if [ -n "$current" ]; then
      read -rp "Enter keeps - or type a folder path (or 'demo') to switch: " folder
    else
      read -rp "Enter keeps - or type a folder path to switch: " folder
    fi
    [ -z "$folder" ] && return 0
    if [ "$folder" = "demo" ]; then
      sed -i '/^VAULT_PATH=/d;/^#VAULT_CHOICE=/d' .env 2>/dev/null || true
      say "Vault: demo"
      return 0
    fi
  else
    # no dialog and no terminal: keep the current state untouched
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
    say "Not a folder: $folder - keeping the current vault (${current_label})."
    return 0
  fi

  sed -i '/^VAULT_PATH=/d;/^#VAULT_CHOICE=/d' .env 2>/dev/null || true
  printf 'VAULT_PATH=%s\n' "$folder" >> .env
  say "Vault set: $folder  (switch again on any run, or: make vault VAULT=demo)"
}

choose_vault

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