---
tags: [project, operations]
---

# Starting it, the automated way

The rule this note documents: nobody should need a terminal, a make
command or a `.env` edit to *use* the assistant. Three launcher files
carry that rule, one per way of arriving at the project, and they all
converge on the same job: check the machine, ask which vault to
answer from, start the stack, wait until it is truly ready, open the
browser. This is the door [[09-running-it]] calls automated; the
manual door, for whoever wants to change the project rather than use
it, is [[12-starting-manual]].

## Three files, one launcher

- `Start Assistant.bat` — the Windows double-click. A batch file
  exists only because `.bat` is what Windows runs on a double-click:
  it confirms the start with a native yes/no window, decides which
  side of the machine should do the work (the gate below), and hands
  off.
- `start.ps1` — the actual Windows launcher, in PowerShell:
  prechecks, the vault window, the stack start, the two waits, the
  browser.
- `start.sh` — the same launcher for everyone else: Debian/Ubuntu,
  macOS, WSL and Git Bash. Double-clicked on a Linux desktop it asks
  through zenity dialogs; run in a terminal it asks in text, with the
  same options.

The gesture per system: on Windows, double-click
`Start Assistant.bat`. On Debian/Ubuntu, macOS or inside WSL, run
`./start.sh` (on a Linux desktop with zenity installed, double-click
works too, and the questions arrive as windows).

## The WSL gate

The first thing both Windows files do is ask *where the repo lives*,
because docker compose must run on the side of the machine that owns
the files. A repo cloned inside WSL appears to Windows under a
`\\wsl.localhost\...` path; compose launched from the Windows side
against those files resolves the relative bind mounts on the wrong
side, and the app container boots with an empty `/app` — a "File
does not exist: app.py" crash loop that looks like a broken project
and is really a mount resolved from the wrong world. So: a repo path
starting with `\\` makes the batch file delegate the entire job to
the WSL side (`wsl.exe --cd <repo> -e bash ./start.sh`), in the same
console window, and the Linux launcher continues from there; a repo
on `C:\` runs the native PowerShell flow. The person double-clicks
the same file in both worlds and never learns any of this happened —
which is the point.

## Prechecks that explain themselves

Before touching the stack, the launcher verifies the machine, and
every failure states its own fix instead of a stack trace: curl
missing (the health checks need it) prints the install line; docker
missing prints the install link for the platform; docker installed
but unusable distinguishes the two classic causes, a stopped daemon
("start Docker Desktop" / "sudo systemctl start docker") versus a
permission problem (`sudo usermod -aG docker $USER`, then log out and
back in); an old compose prints that v2 is required. The principle
threaded through the whole script: the launcher never fails with less
information than it had.

## The vault question, asked on every run

Every start asks the same question in a small native window: **"Which
vault should the assistant answer from?"**, with the current vault
named below it. The buttons say what they do rather than yes/no:
**Keep** (also Enter, also closing the window — the safe path is
always the current state), **Choose...** (a native folder picker),
and **Demo** — which only exists when a custom vault is active,
because without one the current vault already *is* the demo.

Choosing a folder starts a validation loop, not a trust fall: the
folder must contain at least one markdown note, checked recursively.
A folder without any re-asks — "That folder has no markdown notes.
Choose another?" — with the demo as the other exit. The reason is
scar tissue, not zeal: an empty mount once wiped the index and left
the assistant answering from a void, and the guard now lives at every
level ([[03-ingestion-pipeline]] describes the pipeline's own fence).

Without a graphical session the same question arrives in text, with
the same behavior: Enter keeps, `demo` switches back, a typed path is
validated in the same loop. Typed paths also get hygiene — `~`
expands, a Windows `C:\...` path typed inside WSL is converted with
`wslpath`, a relative path becomes absolute. And on Debian/Ubuntu
without zenity, the text prompt teaches the one-time upgrade to
windows: `sudo apt install zenity`.

The launcher is also the only writer the choice needs: it lands as
`VAULT_PATH` in `.env` (or removes the line, for the demo). Because
the question repeats on every run, switching vaults stops being a
configuration task — it is just a different answer next time.

One deliberate non-feature: on a Windows-hosted repo the chosen path
is written exactly as picked, even a `\\wsl.localhost\...` one.
Docker Desktop mounts those UNC paths natively; an earlier version
that "translated" the path through the Linux shell only corrupted it.
The correct amount of path transformation turned out to be none.

## Starting, and the two waits

Then `docker compose up -d`, with the first run announced honestly —
images plus a basic local model, about 4 GB of downloads — and the
classic failures explained on the spot: a taken port names the `.env`
override to change; a full disk names the space needed.

What follows is the part built from a real bad first impression. The
browser used to open the moment the app process was healthy — while
the one-shot ingest was still building the index. First contact with
the project was an empty folder list and answers from nothing, with
no explanation. So the launcher now waits twice, and both waits
narrate themselves, because a silent screen reads as a hang:

1. **The index.** The launcher watches the one-shot ingest container
   until it exits, and every few seconds it echoes the ingest's own
   last log line with the elapsed time, so the console shows real
   progress instead of a cursor. A failed indexing is loud: the
   reason is printed (the ingest's last lines), and the app still
   opens — with the launcher itself and the app's Reingest button as
   the two recovery paths. A detail for the curious: `docker compose
   wait` errors out on a one-shot that has *already* exited, so the
   launcher inspects the container directly by name instead.
2. **The app.** Health-checked every two seconds for up to five
   minutes (the first boot also downloads the embedding model), with
   an elapsed-seconds heartbeat so even this wait is visibly alive.

## Ready, and the browser chain

On healthy, the launcher prints the address and opens the browser by
trying every door in order until one works: `xdg-open` (Linux),
`open` (macOS), `powershell.exe` from the PATH, PowerShell by its
absolute Windows path, and `explorer.exe` — the interop door that
always exists on WSL. If literally none worked, it says so and prints
the URL to open by hand. The chain exists because a delegated WSL
session sometimes lacks the Windows PATH entries; "could not open a
browser automatically" as a printed sentence beats a silently missing
browser. The last lines remind that no key is needed (the basic local
model already answers) and how to stop the stack.

## The black box

Every stage stamps a timestamped line into `/tmp/vault-start.log`,
and the exits stamp themselves too: a normal end, a Ctrl+C and a kill
each leave a distinct signature. When a run looks frozen or dies
without a word, the log is the autopsy — which stage was reached,
which door opened the browser, what status it ended with:

```bash
cat /tmp/vault-start.log
```

The habit behind all of it is the project's usual one, applied to
operations: nothing silent. Every wait says what it is waiting for,
every failure says what to do next, and even a dead launcher leaves a
record of where it was when it stopped.
