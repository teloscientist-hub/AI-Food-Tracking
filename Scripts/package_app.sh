#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_NAME="MML Food Tracking"
APP_BUILD_DIR="$PROJECT_ROOT/.build"
APP_PATH="$APP_BUILD_DIR/$APP_NAME.app"
PYTHON_BIN="${PYTHON_BIN:-python3}"
VENV_PYTHON="$PROJECT_ROOT/.venv/bin/python"

if ! "$PYTHON_BIN" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 12) else 1)' >/dev/null 2>&1; then
  echo "Python 3.12+ is required. Set PYTHON_BIN=/path/to/python3.12 if needed." >&2
  exit 1
fi

mkdir -p "$APP_BUILD_DIR"

if [[ ! -x "$VENV_PYTHON" ]]; then
  echo "Creating project virtual environment..."
  "$PYTHON_BIN" -m venv "$PROJECT_ROOT/.venv"
fi

echo "Installing app dependencies into .venv..."
"$VENV_PYTHON" -m pip install -e "$PROJECT_ROOT"

rm -rf "$APP_PATH"
mkdir -p "$APP_PATH/Contents/MacOS" "$APP_PATH/Contents/Resources"
printf -v APP_ROOT_SHELL "%q" "$PROJECT_ROOT"

cat > "$APP_PATH/Contents/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleDevelopmentRegion</key>
  <string>en</string>
  <key>CFBundleExecutable</key>
  <string>MMLFoodTracking</string>
  <key>CFBundleIdentifier</key>
  <string>local.mml-food-tracking</string>
  <key>CFBundleInfoDictionaryVersion</key>
  <string>6.0</string>
  <key>CFBundleName</key>
  <string>MML Food Tracking</string>
  <key>CFBundleDisplayName</key>
  <string>MML Food Tracking</string>
  <key>CFBundlePackageType</key>
  <string>APPL</string>
  <key>CFBundleShortVersionString</key>
  <string>0.1.0</string>
  <key>CFBundleVersion</key>
  <string>1</string>
  <key>LSMinimumSystemVersion</key>
  <string>11.0</string>
  <key>LSUIElement</key>
  <false/>
</dict>
</plist>
PLIST

cat > "$APP_PATH/Contents/MacOS/MMLFoodTracking" <<LAUNCHER
#!/usr/bin/env bash
set -euo pipefail

APP_ROOT=$APP_ROOT_SHELL
HOST="127.0.0.1"
PORT="\${MML_FOOD_TRACKING_PORT:-8765}"
URL="http://\$HOST:\$PORT"
HEALTH_URL="\$URL/health"
LOG_DIR="\$HOME/Library/Logs/MML Food Tracking"
DATA_DIR="\$HOME/Library/Application Support/MML Food Tracking"
DB_PATH="\$DATA_DIR/mml_food_tracking.db"
LOG_FILE="\$LOG_DIR/server.log"
PYTHON="\$APP_ROOT/.venv/bin/python"

mkdir -p "\$LOG_DIR" "\$DATA_DIR"
cd "\$APP_ROOT"

if [[ ! -x "\$PYTHON" ]]; then
  /usr/bin/osascript -e 'display dialog "The MML Food Tracking Python environment is missing. Run Scripts/package_app.sh from the project folder, then open the app again." buttons {"OK"} default button "OK" with icon caution' >/dev/null 2>&1 || true
  exit 1
fi

if [[ ! -f "\$DB_PATH" && -f "\$APP_ROOT/mml_food_tracking.db" ]]; then
  cp "\$APP_ROOT/mml_food_tracking.db" "\$DB_PATH"
fi

export DATABASE_URL="sqlite:///\$DB_PATH"
export APP_ENV="local_app"

server_ready() {
  /usr/bin/curl --silent --fail --max-time 1 "\$HEALTH_URL" >/dev/null 2>&1
}

if ! server_ready; then
  echo "Starting MML Food Tracking at \$(date)" >> "\$LOG_FILE"
  nohup "\$PYTHON" -m uvicorn app.main:app --host "\$HOST" --port "\$PORT" >> "\$LOG_FILE" 2>&1 &
  for _ in {1..80}; do
    if server_ready; then
      break
    fi
    sleep 0.25
  done
fi

if server_ready; then
  /usr/bin/open "\$URL"
else
  /usr/bin/open "\$LOG_FILE" >/dev/null 2>&1 || true
  /usr/bin/osascript -e 'display dialog "MML Food Tracking did not start. The server log has been opened." buttons {"OK"} default button "OK" with icon caution' >/dev/null 2>&1 || true
  exit 1
fi
LAUNCHER

chmod +x "$APP_PATH/Contents/MacOS/MMLFoodTracking"

echo "Built: $APP_PATH"
echo "Open it with: open '$APP_PATH'"
