#!/usr/bin/env python3
"""
factory/bambu_bridge.py

Bridges Bambu Lab P1S local MQTT → Ignition tag provider via HTTP/WebDev.

Architecture:
    P1S (LAN MQTT port 8883, TLS) ──► this script ──► Ignition WebDev module
                                                      (writes tag values via
                                                       HTTP POST to a WebDev
                                                       endpoint, OR directly
                                                       via Ignition's built-in
                                                       Tag REST API on port 8088)

Requirements:
    pip install paho-mqtt requests termcolor

Usage:
    python3 bambu_bridge.py --printer_ip 192.168.1.YYY --serial AABBCCDD \
            --access_code 12345678

Finding your printer credentials:
    - Serial number: Printer touchscreen → Settings → Device Info
    - Access code  : Printer touchscreen → Settings → WLAN → Access Code
    - IP address   : Your router DHCP table, or Bambu Handy app

Ignition Tag path written to (under [default] tag provider):
    Factory/Printer/bed_temp
    Factory/Printer/nozzle_temp
    Factory/Printer/nozzle_target
    Factory/Printer/chamber_temp
    Factory/Printer/fan_speed_pct
    Factory/Printer/print_percent
    Factory/Printer/layer_num
    Factory/Printer/total_layer_num
    Factory/Printer/remaining_minutes
    Factory/Printer/gcode_state          (IDLE / PREPARE / RUNNING / PAUSE / FINISH / FAILED)
    Factory/Printer/subtask_name         (current file name)
    Factory/Printer/wifi_signal
    Factory/Printer/last_updated         (ISO timestamp)
"""

import argparse
import json
import ssl
import sys
import subprocess
import time
from datetime import datetime, timezone

# ─── CONFIG (override via .envrc or environment variables) ───────────────────
import os
DEFAULT_PRINTER_IP   = os.environ.get("BAMBU_PRINTER_IP",  "192.168.1.YYY")
DEFAULT_SERIAL       = os.environ.get("BAMBU_SERIAL",       "AABBCCDD0000000")
DEFAULT_ACCESS_CODE  = os.environ.get("BAMBU_ACCESS_CODE",  "12345678")
MQTT_PORT            = 8883              # Bambu local MQTT port (TLS)

IGNITION_HOST        = os.environ.get("IGNITION_HOST", "localhost")
IGNITION_PORT        = int(os.environ.get("IGNITION_PORT", "8088"))
IGNITION_TAG_PREFIX  = "[default]Factory/Printer"
IGNITION_USER        = os.environ.get("IGNITION_USER", "admin")
IGNITION_PASS        = os.environ.get("IGNITION_PASS", "")

HEARTBEAT_INTERVAL   = 30
# ──────────────────────────────────────────────────────────────────────────────


def install_deps():
    """Install required packages if missing."""
    for pkg in ["paho-mqtt", "requests", "termcolor"]:
        module = pkg.replace("-", "_").split("==")[0]
        try:
            __import__(module)
        except ImportError:
            subprocess.check_call([sys.executable, "-m", "pip", "install", pkg])


def get_cprint():
    """Return termcolor.cprint, falling back to plain print."""
    try:
        from termcolor import cprint
        return cprint
    except ImportError:
        return lambda msg, *a, **kw: print(msg)


def extract_print_data(payload: dict) -> dict:
    """
    Parse the Bambu MQTT 'print' message and return a flat dict of
    tag_name → value. Returns empty dict if payload doesn't contain
    print telemetry.
    """
    data = {}
    msg = payload.get("print", {})
    if not msg:
        return data

    # Temperatures
    if "bed_temper" in msg:
        data["bed_temp"]       = round(float(msg["bed_temper"]), 1)
    if "nozzle_temper" in msg:
        data["nozzle_temp"]    = round(float(msg["nozzle_temper"]), 1)
    if "nozzle_target_temper" in msg:
        data["nozzle_target"]  = round(float(msg["nozzle_target_temper"]), 1)
    if "chamber_temper" in msg:
        data["chamber_temp"]   = round(float(msg["chamber_temper"]), 1)

    # Fan
    if "cooling_fan_speed" in msg:
        # P1S reports 0–15; convert to 0–100 %
        raw = int(msg["cooling_fan_speed"])
        data["fan_speed_pct"] = round(raw / 15 * 100)

    # Progress
    if "mc_percent" in msg:
        data["print_percent"]  = int(msg["mc_percent"])
    if "layer_num" in msg:
        data["layer_num"]      = int(msg["layer_num"])
    if "total_layer_num" in msg:
        data["total_layer_num"] = int(msg["total_layer_num"])
    if "mc_remaining_time" in msg:
        data["remaining_minutes"] = int(msg["mc_remaining_time"])

    # State / file
    if "gcode_state" in msg:
        data["gcode_state"]    = str(msg["gcode_state"])
    if "subtask_name" in msg:
        data["subtask_name"]   = str(msg["subtask_name"])
    if "wifi_signal" in msg:
        data["wifi_signal"]    = int(msg["wifi_signal"])

    data["last_updated"] = datetime.now(timezone.utc).isoformat()
    return data


def push_to_ignition(tag_data: dict, cprint_fn, args):
    """
    Write tag values to Ignition via the Gateway REST API (port 8088).
    Each tag must already exist in Ignition under IGNITION_TAG_PREFIX.
    Create them as Memory tags in Ignition Designer first.
    """
    import requests

    url = f"http://{args.ignition_host}:{args.ignition_port}/data/tag-provider/default/tag/write"

    tag_writes = []
    for name, value in tag_data.items():
        tag_writes.append({
            "path": f"{args.tag_prefix}/{name}",
            "value": value
        })

    try:
        resp = requests.post(
            url,
            json=tag_writes,
            auth=(args.ignition_user, args.ignition_pass),
            timeout=5
        )
        if resp.status_code == 200:
            cprint_fn(f"[ignition] ✅ Pushed {len(tag_writes)} tags", "green")
        else:
            cprint_fn(f"[ignition] ⚠️  HTTP {resp.status_code}: {resp.text[:120]}", "yellow")
    except requests.exceptions.ConnectionError:
        cprint_fn("[ignition] ❌ Cannot reach Ignition — is the gateway running?", "red")
    except Exception as exc:
        cprint_fn(f"[ignition] ❌ Error: {exc}", "red")


def run_bridge(args, cprint_fn):
    """Main loop: subscribe to Bambu MQTT and forward to Ignition."""
    import paho.mqtt.client as mqtt

    topic_report = f"device/{args.serial}/report"
    topic_request = f"device/{args.serial}/request"
    last_push     = 0.0

    def on_connect(client, userdata, flags, rc):
        if rc == 0:
            cprint_fn("[mqtt] ✅ Connected to Bambu P1S MQTT", "green")
            # Subscribe to all printer reports
            client.subscribe(topic_report)
            # Request full status immediately
            client.publish(
                topic_request,
                json.dumps({"pushing": {"sequence_id": "0", "command": "pushall"}})
            )
        else:
            cprint_fn(f"[mqtt] ❌ Connection failed, rc={rc}", "red")

    def on_disconnect(client, userdata, rc):
        cprint_fn(f"[mqtt] ⚠️  Disconnected (rc={rc}) — will auto-reconnect", "yellow")

    def on_message(client, userdata, msg):
        nonlocal last_push
        try:
            payload = json.loads(msg.payload.decode())
        except json.JSONDecodeError:
            return

        tag_data = extract_print_data(payload)
        if not tag_data:
            return

        now = time.time()
        # Rate-limit pushes: max 1 per second, or on heartbeat interval
        if now - last_push >= 1.0:
            cprint_fn(
                f"[mqtt] state={tag_data.get('gcode_state','?')} "
                f"progress={tag_data.get('print_percent','?')}% "
                f"bed={tag_data.get('bed_temp','?')}°C "
                f"nozzle={tag_data.get('nozzle_temp','?')}°C",
                "cyan"
            )
            push_to_ignition(tag_data, cprint_fn, args)
            last_push = now

    client = mqtt.Client(client_id="humn_factory_bridge", clean_session=True)
    client.username_pw_set("bblp", args.access_code)

    # Bambu local MQTT uses self-signed TLS — disable cert verification
    tls_ctx = ssl.create_default_context()
    tls_ctx.check_hostname = False
    tls_ctx.verify_mode    = ssl.CERT_NONE
    client.tls_set_context(tls_ctx)

    client.on_connect    = on_connect
    client.on_disconnect = on_disconnect
    client.on_message    = on_message

    while True:
        try:
            cprint_fn(f"[mqtt] Connecting to {args.printer_ip}:{MQTT_PORT}...", "cyan")
            client.connect(args.printer_ip, MQTT_PORT, keepalive=60)
            client.loop_forever()
        except KeyboardInterrupt:
            cprint_fn("\n[mqtt] Shutting down.", "yellow")
            break
        except Exception as exc:
            cprint_fn(f"[mqtt] ❌ {exc} — retrying in 10s", "red")
            time.sleep(10)


def main():
    install_deps()
    cprint_fn = get_cprint()

    parser = argparse.ArgumentParser(description="Bambu P1S MQTT → Ignition bridge")
    parser.add_argument("--printer_ip",    default=DEFAULT_PRINTER_IP,  help="P1S IP address")
    parser.add_argument("--serial",        default=DEFAULT_SERIAL,       help="Printer serial number")
    parser.add_argument("--access_code",   default=DEFAULT_ACCESS_CODE,  help="8-digit WLAN access code")
    parser.add_argument("--ignition_host", default=IGNITION_HOST)
    parser.add_argument("--ignition_port", default=IGNITION_PORT, type=int)
    parser.add_argument("--ignition_user", default=IGNITION_USER)
    parser.add_argument("--ignition_pass", default=IGNITION_PASS)
    parser.add_argument("--tag_prefix",    default=IGNITION_TAG_PREFIX,
                        help="Ignition tag path prefix (e.g. [default]Factory/Printer)")
    args = parser.parse_args()

    cprint_fn("═══════════════════════════════════════════════", "cyan")
    cprint_fn(" HUMN Factory — Bambu P1S MQTT Bridge", "cyan")
    cprint_fn("═══════════════════════════════════════════════", "cyan")
    cprint_fn(f" Printer  : {args.printer_ip}  (serial: {args.serial})", "white")
    cprint_fn(f" Ignition : http://{args.ignition_host}:{args.ignition_port}", "white")
    cprint_fn(f" Tag path : {args.tag_prefix}/<name>", "white")
    cprint_fn("───────────────────────────────────────────────", "cyan")
    cprint_fn(" Tags written:", "white")
    cprint_fn("   bed_temp, nozzle_temp, nozzle_target, chamber_temp", "white")
    cprint_fn("   fan_speed_pct, print_percent, layer_num, total_layer_num", "white")
    cprint_fn("   remaining_minutes, gcode_state, subtask_name, wifi_signal", "white")
    cprint_fn("   last_updated", "white")
    cprint_fn("═══════════════════════════════════════════════\n", "cyan")

    run_bridge(args, cprint_fn)


if __name__ == "__main__":
    main()
