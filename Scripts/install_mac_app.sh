#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_NAME="MML Food Tracking"
REQUESTED_APP_INSTALL_DIR="${APP_INSTALL_DIR:-}"
if [[ -n "$REQUESTED_APP_INSTALL_DIR" ]]; then
  APP_INSTALL_DIR="$REQUESTED_APP_INSTALL_DIR"
elif [[ -w /Applications ]]; then
  APP_INSTALL_DIR="/Applications"
else
  APP_INSTALL_DIR="$HOME/Applications"
fi
APP_BUILD_PATH="$PROJECT_ROOT/.build/$APP_NAME.app"
APP_INSTALL_PATH="$APP_INSTALL_DIR/$APP_NAME.app"
LAUNCH_AGENT_LABEL="local.mml-food-tracking"
LAUNCH_AGENT_PATH="$HOME/Library/LaunchAgents/$LAUNCH_AGENT_LABEL.plist"
LOG_DIR="$HOME/Library/Logs/MML Food Tracking"
DATA_DIR="$HOME/Library/Application Support/MML Food Tracking"
DB_PATH="$DATA_DIR/mml_food_tracking.db"
LAUNCH_EXECUTABLE="$APP_INSTALL_PATH/Contents/MacOS/MMLFoodTracking"
LOGIN_LAUNCHER_PATH="$DATA_DIR/start-login-server.sh"

"$PROJECT_ROOT/Scripts/package_app.sh"

mkdir -p "$APP_INSTALL_DIR" "$HOME/Library/LaunchAgents" "$LOG_DIR" "$DATA_DIR"
rm -rf "$APP_INSTALL_PATH"
cp -R "$APP_BUILD_PATH" "$APP_INSTALL_PATH"
/usr/bin/xattr -cr "$APP_INSTALL_PATH" 2>/dev/null || true
if [[ ! -f "$DB_PATH" && -f "$PROJECT_ROOT/mml_food_tracking.db" ]]; then
  cp "$PROJECT_ROOT/mml_food_tracking.db" "$DB_PATH" || true
fi

cat > "$LOGIN_LAUNCHER_PATH" <<SCRIPT
#!/usr/bin/env bash
set -euo pipefail

APP_NAME="$APP_NAME"
PREFERRED_EXECUTABLE="$LAUNCH_EXECUTABLE"

CANDIDATES=(
  "\$PREFERRED_EXECUTABLE"
  "/Applications/$APP_NAME.app/Contents/MacOS/MMLFoodTracking"
  "\$HOME/Applications/$APP_NAME.app/Contents/MacOS/MMLFoodTracking"
  "$APP_BUILD_PATH/Contents/MacOS/MMLFoodTracking"
)

for executable in "\${CANDIDATES[@]}"; do
  if [[ -x "\$executable" ]]; then
    exec "\$executable" --server-only
  fi
done

echo "MML Food Tracking app executable was not found. Re-run Scripts/install_mac_app.sh from the project folder." >&2
exit 1
SCRIPT
chmod +x "$LOGIN_LAUNCHER_PATH"

cat > "$LAUNCH_AGENT_PATH" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>$LAUNCH_AGENT_LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>$LOGIN_LAUNCHER_PATH</string>
  </array>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <dict>
    <key>SuccessfulExit</key>
    <false/>
  </dict>
  <key>StandardOutPath</key>
  <string>$LOG_DIR/launch-agent.log</string>
  <key>StandardErrorPath</key>
  <string>$LOG_DIR/launch-agent.log</string>
</dict>
</plist>
PLIST

launchctl bootout "gui/$(id -u)" "$LAUNCH_AGENT_PATH" >/dev/null 2>&1 || true
launchctl bootstrap "gui/$(id -u)" "$LAUNCH_AGENT_PATH"
launchctl enable "gui/$(id -u)/$LAUNCH_AGENT_LABEL" >/dev/null 2>&1 || true

echo "Installed: $APP_INSTALL_PATH"
echo "Login auto-start enabled: $LAUNCH_AGENT_PATH"
echo "Double-click the app to open MML Food Tracking in your browser."
echo "App URL: http://127.0.0.1:8787"
