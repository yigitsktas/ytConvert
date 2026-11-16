#!/bin/bash
# Tek komutla kurulum: Python ortamı + arka plan servisi (launchd) + ytConvert.app
# Kullanım: ./desktop/install.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LABEL="com.yigitsktas.ytconvert"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
LOG="$HOME/Library/Logs/ytconvert.log"

for bin in ffmpeg node; do
    command -v "$bin" >/dev/null || { echo "✗ $bin bulunamadı: brew install $bin"; exit 1; }
done

echo "→ Python ortamı"
[ -x "$ROOT/.venv/bin/python" ] || python3 -m venv "$ROOT/.venv"
"$ROOT/.venv/bin/pip" install -q --upgrade pip
"$ROOT/.venv/bin/pip" install -q --upgrade -r "$ROOT/requirements.txt"

echo "→ Arka plan servisi"
cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key><string>$LABEL</string>
    <key>WorkingDirectory</key><string>$ROOT</string>
    <key>ProgramArguments</key>
    <array>
        <string>$ROOT/.venv/bin/gunicorn</string>
        <string>--bind</string><string>127.0.0.1:5001</string>
        <string>--worker-class</string><string>gthread</string>
        <string>--threads</string><string>4</string>
        <string>--timeout</string><string>900</string>
        <string>--control-socket</string><string>$ROOT/.venv/gunicorn.ctl</string>
        <string>app:app</string>
    </array>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key><string>$(dirname "$(command -v ffmpeg)"):$(dirname "$(command -v node)"):/usr/bin:/bin:/usr/sbin:/sbin</string>
    </dict>
    <key>RunAtLoad</key><true/>
    <key>KeepAlive</key><true/>
    <key>ProcessType</key><string>Background</string>
    <key>StandardOutPath</key><string>$LOG</string>
    <key>StandardErrorPath</key><string>$LOG</string>
</dict>
</plist>
EOF
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"

echo "→ Masaüstü uygulaması"
"$ROOT/desktop/build.sh"

echo
echo "✓ Kurulum tamam. ytConvert'i Launchpad'den ya da Spotlight'tan (Cmd+Space) açabilirsin."
