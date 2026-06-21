#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_NAME="MML Food Tracking"
APP_BUILD_DIR="$PROJECT_ROOT/.build"
APP_PATH="$APP_BUILD_DIR/$APP_NAME.app"
APP_ICON_SOURCE="$PROJECT_ROOT/app/static/app-icon.svg"
APP_ICONSET_PATH="$APP_BUILD_DIR/AppIcon.iconset"
APP_ICON_PATH="$APP_PATH/Contents/Resources/AppIcon.icns"
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

if [[ -f "$APP_ICON_SOURCE" ]]; then
  rm -rf "$APP_ICONSET_PATH"
  mkdir -p "$APP_ICONSET_PATH"
  /usr/bin/sips -z 16 16 -s format png "$APP_ICON_SOURCE" --out "$APP_ICONSET_PATH/icon_16x16.png" >/dev/null
  /usr/bin/sips -z 32 32 -s format png "$APP_ICON_SOURCE" --out "$APP_ICONSET_PATH/icon_16x16@2x.png" >/dev/null
  /usr/bin/sips -z 32 32 -s format png "$APP_ICON_SOURCE" --out "$APP_ICONSET_PATH/icon_32x32.png" >/dev/null
  /usr/bin/sips -z 64 64 -s format png "$APP_ICON_SOURCE" --out "$APP_ICONSET_PATH/icon_32x32@2x.png" >/dev/null
  /usr/bin/sips -z 128 128 -s format png "$APP_ICON_SOURCE" --out "$APP_ICONSET_PATH/icon_128x128.png" >/dev/null
  /usr/bin/sips -z 256 256 -s format png "$APP_ICON_SOURCE" --out "$APP_ICONSET_PATH/icon_128x128@2x.png" >/dev/null
  /usr/bin/sips -z 256 256 -s format png "$APP_ICON_SOURCE" --out "$APP_ICONSET_PATH/icon_256x256.png" >/dev/null
  /usr/bin/sips -z 512 512 -s format png "$APP_ICON_SOURCE" --out "$APP_ICONSET_PATH/icon_256x256@2x.png" >/dev/null
  /usr/bin/sips -z 512 512 -s format png "$APP_ICON_SOURCE" --out "$APP_ICONSET_PATH/icon_512x512.png" >/dev/null
  /usr/bin/sips -z 1024 1024 -s format png "$APP_ICON_SOURCE" --out "$APP_ICONSET_PATH/icon_512x512@2x.png" >/dev/null
  /usr/bin/iconutil -c icns "$APP_ICONSET_PATH" -o "$APP_ICON_PATH"
  rm -rf "$APP_ICONSET_PATH"
fi

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
  <key>CFBundleIconFile</key>
  <string>AppIcon</string>
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
PORT="\${MML_FOOD_TRACKING_PORT:-8787}"
OPEN_BROWSER="\${MML_FOOD_TRACKING_OPEN_BROWSER:-1}"
SERVER_ONLY="0"
URL="http://\$HOST:\$PORT"
HEALTH_URL="\$URL/health"
LOG_DIR="\$HOME/Library/Logs/MML Food Tracking"
DATA_DIR="\$HOME/Library/Application Support/MML Food Tracking"
DB_PATH="\$DATA_DIR/mml_food_tracking.db"
LOG_FILE="\$LOG_DIR/server.log"
PYTHON="\$APP_ROOT/.venv/bin/python"

if [[ "\${1:-}" == "--no-open" ]]; then
  OPEN_BROWSER="0"
  shift
fi

if [[ "\${1:-}" == "--server-only" ]]; then
  OPEN_BROWSER="0"
  SERVER_ONLY="1"
  shift
fi

mkdir -p "\$LOG_DIR" "\$DATA_DIR"
cd "\$APP_ROOT"

if [[ ! -x "\$PYTHON" ]]; then
  /usr/bin/osascript -e 'display dialog "The MML Food Tracking Python environment is missing. Run Scripts/package_app.sh from the project folder, then open the app again." buttons {"OK"} default button "OK" with icon caution' >/dev/null 2>&1 || true
  exit 1
fi

if [[ ! -f "\$DB_PATH" && -f "\$APP_ROOT/mml_food_tracking.db" ]]; then
  cp "\$APP_ROOT/mml_food_tracking.db" "\$DB_PATH" 2>> "\$LOG_FILE" || true
fi

export DATABASE_URL="sqlite:///\$DB_PATH"
export APP_ENV="local_app"

server_ready() {
  /usr/bin/curl --silent --fail --max-time 1 "\$HEALTH_URL" >/dev/null 2>&1
}

if [[ "\$SERVER_ONLY" == "1" ]]; then
  echo "Starting MML Food Tracking server at \$(date)" >> "\$LOG_FILE"
  exec "\$PYTHON" -m uvicorn app.main:app --host "\$HOST" --port "\$PORT"
fi

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
  if [[ "\$OPEN_BROWSER" == "1" ]]; then
    /usr/bin/open "\$URL"
  fi
else
  /usr/bin/open "\$LOG_FILE" >/dev/null 2>&1 || true
  /usr/bin/osascript -e 'display dialog "MML Food Tracking did not start. The server log has been opened." buttons {"OK"} default button "OK" with icon caution' >/dev/null 2>&1 || true
  exit 1
fi
LAUNCHER

chmod +x "$APP_PATH/Contents/MacOS/MMLFoodTracking"

echo "Built: $APP_PATH"
echo "Open it with: open '$APP_PATH'"
