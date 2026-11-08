#!/bin/bash
# Runs the concert robot every day at 7:23pm (while your Mac is awake).
# Usage:  bash robot/install-mac.sh          # install / update
#         bash robot/install-mac.sh remove   # uninstall
set -euo pipefail
LABEL="com.concerts.robot"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
REPO="$(cd "$(dirname "$0")/.." && pwd)"
NODE="$(command -v node || true)"

if [[ "${1:-}" == "remove" ]]; then
  launchctl bootout "gui/$(id -u)" "$PLIST" 2>/dev/null || true
  rm -f "$PLIST"
  echo "Removed."
  exit 0
fi

[[ -n "$NODE" ]] || { echo "Install Node.js first: https://nodejs.org"; exit 1; }
(cd "$REPO/robot" && npm install --silent)

mkdir -p "$HOME/Library/LaunchAgents"
cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key><array>
    <string>$NODE</string><string>$REPO/robot/scrape.mjs</string>
  </array>
  <key>WorkingDirectory</key><string>$REPO</string>
  <key>EnvironmentVariables</key><dict>
    <key>PATH</key><string>$(dirname "$NODE"):/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin</string>
  </dict>
  <key>StartCalendarInterval</key><dict><key>Hour</key><integer>19</integer><key>Minute</key><integer>23</integer></dict>
  <key>StandardOutPath</key><string>$HOME/Library/Logs/concert-robot.log</string>
  <key>StandardErrorPath</key><string>$HOME/Library/Logs/concert-robot.log</string>
</dict></plist>
EOF
launchctl bootout "gui/$(id -u)" "$PLIST" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"
echo "Installed. Runs daily at 7:23pm. Log: ~/Library/Logs/concert-robot.log"
echo "Run it now with:  launchctl kickstart gui/$(id -u)/$LABEL"
