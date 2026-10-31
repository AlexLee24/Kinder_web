#!/usr/bin/env bash
# Run Kinder (gunicorn) as a launchd service on macOS, like a systemd unit on Linux:
# it starts on its own, comes back if it crashes, and restarts with one command.
#
#   scripts/kinder_service.sh install      write the plist and start the service (once)
#   scripts/kinder_service.sh restart      stop + start (new code, new kinder.env)
#   scripts/kinder_service.sh deploy       git pull --ff-only (Kinder, then app/vendor/CASTOR), uv sync, restart,
#                                          wait until it answers
#   scripts/kinder_service.sh status       running? pid, last exit, does the port answer
#   scripts/kinder_service.sh logs [-f]    the service's own output (~/Library/Logs/Kinder/tw.edu.ncu.kinder.log)
#   scripts/kinder_service.sh start | stop | uninstall
#
# Two kinds (pick at install; the other commands find which one is installed):
#   install            LaunchAgent  ~/Library/LaunchAgents   runs while this user is logged in on the Mac
#                      (the console session; turn on automatic login to survive a reboot). No sudo needed,
#                      also over ssh.
#   install --system   LaunchDaemon /Library/LaunchDaemons   runs from boot without anyone logged in, as
#                      this user. Needs sudo for install / restart / stop.
#
# What it runs, from the project root (same as by hand):
#   .venv/bin/gunicorn --workers 4 --worker-class gthread --threads 4 --bind 127.0.0.1:8000 wsgi:app
# Change it at install with KINDER_BIND / KINDER_WORKERS / KINDER_THREADS; KINDER_ENV_FILE (if set) is passed
# on. The plist keeps the PATH of the shell that installed it, so tools the app calls (uv, solve-field,
# conda …) are found as in your terminal. Re-run install after changing any of these.
# install first checks that a launchd job may read the project (an external disk needs Full Disk Access for
# the venv's Python) and says what to do if not.
set -euo pipefail

LABEL="${KINDER_LABEL:-tw.edu.ncu.kinder}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BIND="${KINDER_BIND:-127.0.0.1:8000}"
WORKERS="${KINDER_WORKERS:-4}"
THREADS="${KINDER_THREADS:-4}"
LOG="$HOME/Library/Logs/Kinder/$LABEL.log"     # outside the project: launchd itself may not write there
AGENT_PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
DAEMON_PLIST="/Library/LaunchDaemons/$LABEL.plist"
UID_NUM="$(id -u)"

die() { echo "kinder_service: $*" >&2; exit 1; }

# which kind is installed: sets PLIST, DOMAIN, SUDO, and BIND from the installed plist
detect() {
    if [[ -f "$DAEMON_PLIST" ]]; then
        PLIST="$DAEMON_PLIST"; DOMAIN="system"; SUDO="sudo"
        if [[ "$UID_NUM" == 0 ]]; then SUDO=""; fi
    elif [[ -f "$AGENT_PLIST" ]]; then
        PLIST="$AGENT_PLIST"; DOMAIN="gui/$UID_NUM"; SUDO=""
    else
        die "not installed (run: scripts/kinder_service.sh install   or   install --system)"
    fi
    local b
    b="$(plutil -extract EnvironmentVariables.KINDER_BIND raw "$PLIST" 2>/dev/null || true)"
    if [[ -n "$b" ]]; then BIND="$b"; fi
}

loaded() { $SUDO launchctl print "$DOMAIN/$LABEL" >/dev/null 2>&1; }

xml() { local s="${1//&/&amp;}"; s="${s//</&lt;}"; printf '%s' "${s//>/&gt;}"; }

write_plist() {        # $1 = target path, $2 = 1 for a LaunchDaemon (adds UserName)
    local target="$1" daemon="$2" user_line="" env_extra=""
    [[ "$daemon" == 1 ]] && user_line="    <key>UserName</key><string>$(xml "$(id -un)")</string>"
    [[ -x "$ROOT/.venv/bin/gunicorn" ]] || die "no $ROOT/.venv/bin/gunicorn — run: uv sync"
    if [[ -n "${KINDER_ENV_FILE:-}" ]]; then
        env_extra="        <key>KINDER_ENV_FILE</key><string>$(xml "$KINDER_ENV_FILE")</string>"
    fi
    mkdir -p "$(dirname "$LOG")"
    # launchd only starts the venv's real Python (it lives outside the project): launchd itself may not enter a
    # project on an external disk, so no WorkingDirectory, and Python changes into it and runs gunicorn
    local py tmp
    py="$("$ROOT/.venv/bin/python" -c 'import os, sys; print(os.path.realpath(sys.executable))')"
    tmp="$(mktemp)"
    cat > "$tmp" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<!-- Written by scripts/kinder_service.sh install; edit the script (or its KINDER_* settings) and re-install. -->
<plist version="1.0">
<dict>
    <key>Label</key><string>$(xml "$LABEL")</string>
$user_line
    <key>ProgramArguments</key>
    <array>
        <string>$(xml "$py")</string><string>-c</string>
        <string>import os, sys; os.chdir(sys.argv[1]); p = os.path.join(sys.argv[1], '.venv', 'bin', 'python'); os.execv(p, [p, '-m', 'gunicorn'] + sys.argv[2:])</string>
        <string>$(xml "$ROOT")</string>
        <string>--workers</string><string>$(xml "$WORKERS")</string>
        <string>--worker-class</string><string>gthread</string>
        <string>--threads</string><string>$(xml "$THREADS")</string>
        <string>--bind</string><string>$(xml "$BIND")</string>
        <string>wsgi:app</string>
    </array>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key><string>$(xml "$ROOT/.venv/bin:$PATH")</string>
        <key>HOME</key><string>$(xml "$HOME")</string>
        <key>LANG</key><string>en_US.UTF-8</string>
        <key>PYTHONUNBUFFERED</key><string>1</string>
        <key>KINDER_BIND</key><string>$(xml "$BIND")</string>
$env_extra
    </dict>
    <key>RunAtLoad</key><true/>
    <key>KeepAlive</key><true/>
    <key>ThrottleInterval</key><integer>10</integer>
    <key>ExitTimeOut</key><integer>30</integer>
    <key>SoftResourceLimits</key><dict><key>NumberOfFiles</key><integer>8192</integer></dict>
    <key>HardResourceLimits</key><dict><key>NumberOfFiles</key><integer>8192</integer></dict>
    <key>StandardOutPath</key><string>$(xml "$LOG")</string>
    <key>StandardErrorPath</key><string>$(xml "$LOG")</string>
</dict>
</plist>
PLIST
    plutil -lint "$tmp" >/dev/null || { cat "$tmp" >&2; rm -f "$tmp"; die "the generated plist is not valid"; }
    if [[ "$daemon" == 1 ]]; then
        sudo install -m 644 -o root -g wheel "$tmp" "$target"
    else
        mkdir -p "$(dirname "$target")"; install -m 644 "$tmp" "$target"
    fi
    rm -f "$tmp"
}

# HTTP status of the bound address ("000" = nothing answers). Any status means gunicorn is up.
probe() { curl -s -o /dev/null -m 5 -w '%{http_code}' "http://$BIND/" 2>/dev/null || true; }

# launchd appends to the log forever: keep one old copy once it passes 50 MB (before a (re)start)
rotate_log() {
    if [[ -f "$LOG" ]] && [[ "$(stat -f%z "$LOG")" -gt 52428800 ]]; then mv -f "$LOG" "$LOG.1"; fi
}

wait_up() {
    local i code
    for i in $(seq 1 60); do
        code="$(probe)"
        if [[ "$code" != "000" && -n "$code" ]]; then echo "Kinder answers on http://$BIND (HTTP $code)"; return 0; fi
        sleep 1
    done
    echo "Kinder does not answer on http://$BIND after 60 s; last lines of $LOG:" >&2
    tail -n 30 "$LOG" >&2 || true
    return 1
}

# launchd jobs do not get Terminal's privacy permissions: a project on an external disk, or in ~/Documents,
# ~/Desktop or ~/Downloads, is "Operation not permitted" to them unless the Python that runs gunicorn has Full Disk
# Access. Find out with a throwaway job (same Python, same launchd domain) before installing.
check_access() {   # $1 = domain, $2 = 1 for the system domain
    local domain="$1" daemon="$2" label="$LABEL.access-check" out plist py ok=""
    py="$("$ROOT/.venv/bin/python" -c 'import os, sys; print(os.path.realpath(sys.executable))')"
    out="$(mktemp /tmp/kinder-access.XXXXXX)"; chmod 666 "$out"
    plist="/tmp/$label.plist"
    $SUDO rm -f "$plist"
    cat > "$out.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
    <key>Label</key><string>$(xml "$label")</string>
$( if [[ "$daemon" == 1 ]]; then echo "    <key>UserName</key><string>$(xml "$(id -un)")</string>"; fi )
    <key>ProgramArguments</key><array>
        <string>$(xml "$py")</string><string>-c</string>
        <string>import os, sys; os.chdir(sys.argv[1]); open('wsgi.py').read(1); open(sys.argv[2], 'w').write('ok')</string>
        <string>$(xml "$ROOT")</string><string>$(xml "$out")</string>
    </array>
    <key>RunAtLoad</key><true/>
</dict></plist>
PLIST
    if [[ "$daemon" == 1 ]]; then sudo install -m 644 -o root -g wheel "$out.plist" "$plist"; else install -m 644 "$out.plist" "$plist"; fi
    rm -f "$out.plist"
    $SUDO launchctl bootout "$domain/$label" 2>/dev/null || true
    $SUDO launchctl bootstrap "$domain" "$plist"
    for _ in 1 2 3 4 5 6 7 8 9 10; do
        if [[ "$(cat "$out" 2>/dev/null)" == "ok" ]]; then ok=1; break; fi
        sleep 0.5
    done
    $SUDO launchctl bootout "$domain/$label" 2>/dev/null || true
    $SUDO rm -f "$plist"; rm -f "$out"
    if [[ -z "$ok" ]]; then
        cat >&2 <<MSG
kinder_service: launchd jobs cannot read $ROOT
(macOS privacy protection: your Terminal may, a background job may not). Either
  - give this Python Full Disk Access, then run install again:
        $py
    System Settings > Privacy & Security > Full Disk Access > + (press Cmd+Shift+G and paste the path above),
    or open the pane with:  open "x-apple.systempreferences:com.apple.preference.security?Privacy_AllFiles"
  - or move the project to a folder on the internal disk outside Documents / Desktop / Downloads.
(A new Python version, e.g. after "uv python upgrade", is a new path and needs the permission again.)
MSG
        exit 1
    fi
}

cmd_install() {
    local daemon=0
    [[ "${1:-}" == "--system" ]] && daemon=1
    [[ -x "$ROOT/.venv/bin/gunicorn" ]] || die "no $ROOT/.venv/bin/gunicorn — run: uv sync"
    if [[ -f "$AGENT_PLIST" || -f "$DAEMON_PLIST" ]]; then      # re-install: stop the old one first
        detect; loaded && $SUDO launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
        [[ "$daemon" == 1 && -f "$AGENT_PLIST" ]] && rm -f "$AGENT_PLIST"
        [[ "$daemon" == 0 && -f "$DAEMON_PLIST" ]] && sudo rm -f "$DAEMON_PLIST"
    fi
    if [[ "$daemon" == 1 ]]; then SUDO="sudo"; check_access system 1; else SUDO=""; check_access "gui/$UID_NUM" 0; fi
    rotate_log
    if [[ "$daemon" == 1 ]]; then
        write_plist "$DAEMON_PLIST" 1; PLIST="$DAEMON_PLIST"; DOMAIN="system"; SUDO="sudo"
    else
        write_plist "$AGENT_PLIST" 0; PLIST="$AGENT_PLIST"; DOMAIN="gui/$UID_NUM"; SUDO=""
    fi
    $SUDO launchctl enable "$DOMAIN/$LABEL"
    $SUDO launchctl bootstrap "$DOMAIN" "$PLIST"
    echo "Installed $PLIST ($DOMAIN/$LABEL)"
    wait_up
}

cmd_start() {
    detect
    rotate_log
    if loaded; then $SUDO launchctl kickstart "$DOMAIN/$LABEL"; else $SUDO launchctl bootstrap "$DOMAIN" "$PLIST"; fi
    wait_up
}

cmd_stop() {       # bootout: KeepAlive would bring a killed process straight back
    detect
    if loaded; then $SUDO launchctl bootout "$DOMAIN/$LABEL" && echo "Stopped ($DOMAIN/$LABEL)"; else echo "Not running"; fi
}

cmd_restart() {
    detect
    rotate_log
    if loaded; then
        echo "Restarting $DOMAIN/$LABEL …"
        $SUDO launchctl kickstart -k "$DOMAIN/$LABEL"
    else
        $SUDO launchctl bootstrap "$DOMAIN" "$PLIST"
    fi
    sleep 2
    wait_up
}

cmd_status() {
    detect
    echo "Service : $DOMAIN/$LABEL"
    echo "Plist   : $PLIST"
    if loaded; then
        $SUDO launchctl print "$DOMAIN/$LABEL" | grep -E "^$(printf '\t')(state|pid|last exit code|runs) =" \
            | sed 's/^[[:space:]]*/          /' || true
    else
        echo "          not loaded (stopped)"
    fi
    local code; code="$(probe)"
    if [[ "$code" == "000" || -z "$code" ]]; then echo "HTTP    : nothing answers on http://$BIND"; else echo "HTTP    : http://$BIND answers ($code)"; fi
    echo "Log     : $LOG"
}

cmd_logs() {
    [[ -f "$LOG" ]] || die "no log yet ($LOG)"
    if [[ "${1:-}" == "-f" ]]; then tail -n 50 -f "$LOG"; else tail -n 100 "$LOG"; fi
}

cmd_deploy() {
    detect
    cd "$ROOT"
    echo "== git pull ($(git rev-parse --abbrev-ref HEAD))"
    git pull --ff-only
    if [[ -d app/vendor/CASTOR/.git ]]; then      # the exposure-time engine is its own clone (git-ignored here)
        echo "== git pull app/vendor/CASTOR ($(git -C app/vendor/CASTOR rev-parse --abbrev-ref HEAD))"
        git -C app/vendor/CASTOR pull --ff-only
    else
        echo "== app/vendor/CASTOR is not a git clone: skipped"
    fi
    echo "== uv sync"
    local uv                                  # over ssh PATH often lacks Homebrew
    uv="$(command -v uv || true)"
    for c in /opt/homebrew/bin/uv /usr/local/bin/uv "$HOME/.local/bin/uv" "$HOME/.cargo/bin/uv"; do
        if [[ -z "$uv" && -x "$c" ]]; then uv="$c"; fi
    done
    [[ -n "$uv" ]] || die "uv not found"
    "$uv" sync --frozen
    echo "== restart"
    cmd_restart
    echo "== now at $(git log --oneline -1)"
    if [[ -d app/vendor/CASTOR/.git ]]; then echo "   CASTOR $(git -C app/vendor/CASTOR log --oneline -1)"; fi
}

cmd_uninstall() {
    detect
    loaded && $SUDO launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
    $SUDO rm -f "$PLIST"
    echo "Removed $PLIST"
}

case "${1:-}" in
    install)   shift; cmd_install "$@" ;;
    start)     cmd_start ;;
    stop)      cmd_stop ;;
    restart)   cmd_restart ;;
    status)    cmd_status ;;
    logs)      shift; cmd_logs "$@" ;;
    deploy)    cmd_deploy ;;
    uninstall) cmd_uninstall ;;
    *) sed -n '2,26p' "$0" | sed 's/^# \{0,1\}//'; exit 1 ;;
esac
