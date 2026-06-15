#!/usr/bin/env bash
# Install ifrbridge as a systemd *user* service on Linux, plus the udev rule
# that grants HID access. Run as your normal user (it will sudo for the udev
# rule only). Re-runnable.
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV="$PROJECT_DIR/.venv"
UNIT_DIR="$HOME/.config/systemd/user"
ENV_FILE="$HOME/.config/ifrbridge.env"

echo "Project: $PROJECT_DIR"

# 1) Python venv + dependencies
if [ ! -d "$VENV" ]; then
  echo "Creating venv..."
  python3 -m venv "$VENV"
fi
"$VENV/bin/pip" install -q --upgrade pip
"$VENV/bin/pip" install -q -r "$PROJECT_DIR/requirements.txt"

# 2) udev rule (needs root) so we can talk to the IFR-1 without sudo
echo "Installing udev rule (you may be prompted for sudo)..."
sudo cp "$PROJECT_DIR/linux/99-octavi-ifr1.rules" /etc/udev/rules.d/99-octavi-ifr1.rules
sudo udevadm control --reload-rules
sudo udevadm trigger
echo "  (if the panel was already plugged in, unplug/replug it once)"

# 3) systemd user service (expand @PROJECT_DIR@ to an absolute path)
mkdir -p "$UNIT_DIR"
sed "s|@PROJECT_DIR@|$PROJECT_DIR|g" \
    "$PROJECT_DIR/linux/ifrbridge.service" > "$UNIT_DIR/ifrbridge.service"

# 4) default env file (X-Plane host) — only if missing
if [ ! -f "$ENV_FILE" ]; then
  echo "IFRBRIDGE_HOST=127.0.0.1" > "$ENV_FILE"
  echo "Wrote $ENV_FILE (edit IFRBRIDGE_HOST if X-Plane runs on another machine)"
fi

# 5) enable + start
systemctl --user daemon-reload
systemctl --user enable --now ifrbridge.service

cat <<EOF

Installed and started.

  Status:   systemctl --user status ifrbridge
  Logs:     journalctl --user -u ifrbridge -f
  Stop:     systemctl --user stop ifrbridge
  Disable:  systemctl --user disable --now ifrbridge

If X-Plane is on another PC, set its IP in $ENV_FILE and run:
  systemctl --user restart ifrbridge

Headless / want it before graphical login? Run once:
  loginctl enable-linger \$USER
EOF
