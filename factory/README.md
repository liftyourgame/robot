# HUMN Factory — Ignition 3D Print Monitor

Monitors the **Bambu Lab P1S** printer and **Tapo TC60** webcam inside
Ignition 8.3.3 Perspective.

```
Bambu P1S ──MQTT/TLS──► bambu_bridge.py ──HTTP──► Ignition tags
Tapo TC60 ──RTSP──────► camera_bridge.py ──MJPEG─► Perspective Image
                                                          │
                                              perspective_dashboard.json
```

---

## Files

| File | Purpose |
|---|---|
| `camera_bridge.py` | RTSP → MJPEG HTTP bridge for the Tapo TC60 |
| `bambu_bridge.py` | Bambu P1S local MQTT → Ignition tag writer |
| `ignition_tags.json` | Import this into Ignition Tag Browser to create all tags |
| `perspective_dashboard.json` | Import into Perspective as a new View |
| `README.md` | This file |

---

## Setup — Step by Step

### 1. Install Python dependencies

```bash
cd factory
pip3 install opencv-python paho-mqtt requests termcolor
```

### 2. Import Ignition tags

1. Open **Ignition Designer** → Tag Browser
2. Right-click `[default]` provider → **Import Tags**
3. Select `ignition_tags.json`
4. All 14 tags will appear under `Factory/Printer/`

> **Enable history** on the temperature tags:
> Select `bed_temp`, `nozzle_temp`, `chamber_temp` → Properties → History →
> tick **History Enabled**, set deadband 0.5°C, store in your Historian module.

### 3. Configure credentials

Edit `bambu_bridge.py` top section:

```python
DEFAULT_PRINTER_IP   = "192.168.1.YYY"   # P1S IP from your router
DEFAULT_SERIAL       = "AABBCCDD0000000" # Printer → Settings → Device Info
DEFAULT_ACCESS_CODE  = "12345678"        # Printer → Settings → WLAN → Access Code
IGNITION_PASS        = "password"        # Your Ignition gateway admin password
```

Edit `camera_bridge.py` top section:

```python
CAMERA_IP   = "192.168.1.XXX"    # TC60 IP from your router / Tapo app
CAMERA_USER = "admin"
CAMERA_PASS = "your_password"   # Set when you configured the camera in Tapo app
```

### 4. Start the camera bridge

```bash
python3 camera_bridge.py
# Or with args:
python3 camera_bridge.py --ip 192.168.1.100 --port 8090
```

Test it: open `http://localhost:8090/stream` in a browser — you should see
the live feed.

### 5. Start the Bambu bridge

```bash
python3 bambu_bridge.py
# Or with args:
python3 bambu_bridge.py --printer_ip 192.168.1.101 \
    --serial AABBCCDD0000000 --access_code 12345678
```

You should see coloured output like:
```
[mqtt] ✅ Connected to Bambu P1S MQTT
[mqtt] state=RUNNING progress=42% bed=65.0°C nozzle=220.0°C
[ignition] ✅ Pushed 14 tags
```

### 6. Import the Ignition project

The easiest method — imports project + view in one step:

1. Open **Ignition Gateway** → `http://localhost:8088`
2. Go to **Config → Projects → Import Project**
3. Upload `factory/HumnFactory.zip`
4. Name it `HumnFactory` → click **Import**
5. Open **Ignition Designer**, select the `HumnFactory` project
6. The `PrintMonitor` Perspective view will already be there

> Alternatively, paste `perspective_dashboard.json` manually:
> Designer → Perspective → New View `PrintMonitor` → JSON tab → paste → save.

The dashboard includes:
- **Live camera feed** (top left — MJPEG stream from camera_bridge)
- **Print status card** (state, file name, progress bar, layers, time remaining)
- **Temperature card** (nozzle, bed, chamber, fan) + 1-hour trend chart

### 7. Auto-start on Mac login (optional)

Create `~/Library/LaunchAgents/com.humn.camera_bridge.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>         <string>com.humn.camera_bridge</string>
  <key>ProgramArguments</key>
  <array>
    <string>/usr/bin/python3</string>
    <string>/Users/greg/local_development/humn/robot/factory/camera_bridge.py</string>
  </array>
  <key>RunAtLoad</key>     <true/>
  <key>KeepAlive</key>     <true/>
  <key>StandardOutPath</key> <string>/tmp/camera_bridge.log</string>
  <key>StandardErrorPath</key> <string>/tmp/camera_bridge.err</string>
</dict>
</plist>
```

Do the same for `bambu_bridge.py` →  `com.humn.bambu_bridge.plist`.

Then load:
```bash
launchctl load ~/Library/LaunchAgents/com.humn.camera_bridge.plist
launchctl load ~/Library/LaunchAgents/com.humn.bambu_bridge.plist
```

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| Camera shows blank / error | Check `CAMERA_IP`, `CAMERA_PASS`; ensure TC60 is on same LAN |
| RTSP connection refused | TC60 RTSP must be enabled in Tapo app: Camera Settings → Advanced |
| `bambu_bridge` can't connect | Confirm printer IP, serial, access code; ensure LAN-only mode is enabled on printer |
| Ignition tags not updating | Verify `IGNITION_PASS`; check Gateway is on port 8088; tags must exist before writing |
| `403 Forbidden` from Ignition | Gateway user needs **Tag Write** permission in User Management |
| Chart shows no history | History must be enabled on tags **and** Historian module must be configured with a DB |
