#!/usr/bin/env bash
# Installazione di Giuda su macOS / Linux
set -e
cd "$(dirname "$0")"
DIR="$(pwd)"
echo "== GIUDA - Chi l'ha deciso!!! =="
command -v python3 >/dev/null 2>&1 || { echo "Python 3 non trovato. macOS: 'brew install python' | Ubuntu: 'sudo apt install python3'"; exit 1; }
python3 -c 'import sys;sys.exit(0 if sys.version_info>=(3,9) else 1)' || { echo "Serve Python 3.9+"; exit 1; }
mkdir -p data
cat > avvia.sh <<EOS
#!/usr/bin/env bash
cd "$DIR"
nohup python3 giuda.py "\$@" >> data/console.log 2>&1 &
EOS
chmod +x avvia.sh
read -r -p "Avvio automatico all'accensione? [s/N] " a
if [[ "$a" =~ ^[sS]$ ]]; then
  if [[ "$(uname)" == "Darwin" ]]; then
    mkdir -p ~/Library/LaunchAgents
    cat > ~/Library/LaunchAgents/ai.leanai.giuda.plist <<EOP
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>Label</key><string>ai.leanai.giuda</string>
<key>ProgramArguments</key><array><string>$(command -v python3)</string><string>$DIR/giuda.py</string><string>--no-browser</string></array>
<key>RunAtLoad</key><true/><key>WorkingDirectory</key><string>$DIR</string>
</dict></plist>
EOP
    launchctl load ~/Library/LaunchAgents/ai.leanai.giuda.plist 2>/dev/null || true
  else
    mkdir -p ~/.config/systemd/user
    cat > ~/.config/systemd/user/giuda.service <<EOU
[Unit]
Description=Giuda revisore di codice
[Service]
WorkingDirectory=$DIR
ExecStart=$(command -v python3) $DIR/giuda.py --no-browser
Restart=on-failure
[Install]
WantedBy=default.target
EOU
    systemctl --user daemon-reload && systemctl --user enable --now giuda.service
  fi
  echo "Avvio automatico attivato"
fi
./avvia.sh
echo "Giuda e' acceso: http://127.0.0.1:8765"
