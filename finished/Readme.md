Voraussetzungen
Python 3 muss auf dem Node installiert sein.
Installiere die benötigten Python-Pakete über pip:

pip install proxmoxer pyyaml requests

Manuelle Ausführung
Dateien kopieren:
Lege beide Dateien (proxlb_daemon.py und proxlb_app.yaml) in ein Verzeichnis deiner Wahl, z. B. /opt/proxlb/.


Ausführbar machen:
Gib dem Skript Ausführungsrechte:

chmod +x /opt/proxlb/proxlb_daemon.py
Skript starten:
Führe das Skript aus:

cd /opt/proxlb/
./proxlb_daemon.py

python3 /opt/proxlb/proxlb_daemon.py
Als Systemd Service (optional)
Um den Daemon dauerhaft als Service laufen zu lassen, erstelle eine Systemd-Service-Datei, z. B. /etc/systemd/system/proxlb.service:
"
[Unit]
Description=ProxLB Daemon Service
After=network.target

[Service]
User=root
WorkingDirectory=/opt/proxlb
ExecStart=/usr/bin/python3 /opt/proxlb/proxlb_daemon.py
Restart=always
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
Service laden und aktivieren:
"


"systemctl daemon-reload"
"systemctl enable proxlb"
"systemctl start proxlb"

Logs ansehen:
Mit folgendem Befehl kannst du die Logs in Echtzeit betrachten:
"journalctl -u proxlb -f"
