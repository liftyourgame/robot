#!/usr/bin/env python3
"""
factory/bambu_bridge.py

Bridges Bambu Lab P1S local MQTT → Ignition tag provider via OPC-UA.

Architecture:
    P1S (LAN MQTT port 8883, TLS) ──► this script ──► Ignition OPC-UA server
                                                      (built-in, port 62541,
                                                       no extra modules needed)

Requirements:
    pip install paho-mqtt termcolor asyncua

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

SMTP2GO_API_KEY      = os.environ.get("SMTP2GO_API_KEY", "")
ALERT_FROM           = os.environ.get("ALERT_FROM", "")
ALERT_TO             = os.environ.get("ALERT_TO", "")

IGNITION_HOST        = os.environ.get("IGNITION_HOST", "localhost")
IGNITION_OPCUA_PORT  = int(os.environ.get("IGNITION_OPCUA_PORT", "62541"))
# OPC-UA node path — must match tags created in Ignition Designer
# Format: ns=1;s=[default]Factory/Printer/<tag_name>
IGNITION_TAG_PREFIX  = os.environ.get("IGNITION_TAG_PREFIX", "[default]Factory/Printer")
IGNITION_USER        = os.environ.get("IGNITION_USER", "admin")
IGNITION_PASS        = os.environ.get("IGNITION_PASS", "")

HEARTBEAT_INTERVAL   = 30
# ──────────────────────────────────────────────────────────────────────────────


def install_deps():
    """Install required packages if missing."""
    for pkg, module in [("paho-mqtt", "paho"), ("termcolor", "termcolor"), ("asyncua", "asyncua")]:
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
        # Bambu reports wifi_signal as e.g. '-22dBm' — strip non-numeric chars
        raw_wifi = str(msg["wifi_signal"]).replace("dBm", "").strip()
        try:
            data["wifi_signal"] = int(raw_wifi)
        except ValueError:
            data["wifi_signal"] = 0

    data["last_updated"] = datetime.now(timezone.utc).isoformat()
    return data


def send_alert(subject: str, body: str, cprint_fn):
    """Send an email alert via SMTP2GO HTTP API (works through any firewall)."""
    if not SMTP2GO_API_KEY or not ALERT_FROM or not ALERT_TO:
        cprint_fn("[alert] ⚠️  SMTP2GO not configured — skipping email", "yellow")
        return
    import requests
    try:
        resp = requests.post(
            "https://api.smtp2go.com/v3/email/send",
            json={
                "api_key":  SMTP2GO_API_KEY,
                "to":       [ALERT_TO],
                "sender":   ALERT_FROM,
                "subject":  subject,
                "text_body": body,
            },
            timeout=10,
        )
        if resp.status_code == 200 and resp.json().get("data", {}).get("succeeded"):
            cprint_fn(f"[alert] ✅ Email sent to {ALERT_TO}", "green")
        else:
            cprint_fn(f"[alert] ⚠️  SMTP2GO error: {resp.text[:120]}", "yellow")
    except Exception as exc:
        cprint_fn(f"[alert] ❌ {exc}", "red")


def push_to_ignition(tag_data: dict, cprint_fn, args):
    """
    Write tag values to Ignition via its built-in OPC-UA server (port 62541).

    No extra Ignition modules required — OPC-UA is always available.

    Each tag must exist in Ignition Designer as a Memory tag under:
        [default]Factory/Printer/<tag_name>

    OPC-UA node IDs use namespace 1 and the full Ignition tag path:
        ns=1;s=[default]Factory/Printer/bed_temp
    """
    import asyncio
    from asyncua import Client as OpcuaClient, ua

    # Explicit OPC-UA variant types — required when tag has null value in Ignition
    TAG_TYPES = {
        "bed_temp":          ua.VariantType.Float,
        "nozzle_temp":       ua.VariantType.Float,
        "nozzle_target":     ua.VariantType.Float,
        "chamber_temp":      ua.VariantType.Float,
        "fan_speed_pct":     ua.VariantType.Int32,
        "print_percent":     ua.VariantType.Int32,
        "layer_num":         ua.VariantType.Int32,
        "total_layer_num":   ua.VariantType.Int32,
        "remaining_minutes": ua.VariantType.Int32,
        "gcode_state":       ua.VariantType.String,
        "subtask_name":      ua.VariantType.String,
        "wifi_signal":       ua.VariantType.Int32,
        "last_updated":      ua.VariantType.String,
    }

    async def _write():
        url = f"opc.tcp://{args.ignition_host}:{args.ignition_opcua_port}"
        # OPC-UA None security policy cannot encrypt passwords — use anonymous auth.
        # Enable anonymous access in Ignition: Config → OPC-UA Server → User Token Policies → Anonymous
        client = OpcuaClient(url=url, timeout=5)
        async with client:
            ok = 0
            for name, value in tag_data.items():
                # Tag Providers are exposed at ns=2 in Ignition 8 OPC-UA
                node_id = f"ns=2;s={args.tag_prefix}/{name}"
                try:
                    node     = client.get_node(node_id)
                    vtype    = TAG_TYPES.get(name)
                    dv       = ua.DataValue(ua.Variant(value, vtype))
                    await node.write_value(dv)
                    ok += 1
                except Exception as exc:
                    cprint_fn(f"[opcua] ⚠️  {name}: {exc}", "yellow")
            cprint_fn(f"[ignition] ✅ Pushed {ok}/{len(tag_data)} tags via OPC-UA", "green")

    try:
        asyncio.run(_write())
    except ConnectionRefusedError:
        cprint_fn(f"[ignition] ❌ OPC-UA connection refused — is Ignition running on port {args.ignition_opcua_port}?", "red")
    except Exception as exc:
        cprint_fn(f"[ignition] ❌ OPC-UA error: {exc}", "red")


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

    last_gcode_state = {"value": None}  # track state changes for alerting

    def on_message(client, userdata, msg):
        nonlocal last_push
        try:
            payload = json.loads(msg.payload.decode())
        except json.JSONDecodeError:
            return

        tag_data = extract_print_data(payload)
        if not tag_data:
            return

        # Alert on state transitions to PAUSE or FAILED
        new_state = tag_data.get("gcode_state")
        if new_state and new_state != last_gcode_state["value"]:
            if new_state in ("PAUSE", "FAILED"):
                subtask = tag_data.get("subtask_name", "unknown")
                progress = tag_data.get("print_percent", "?")
                send_alert(
                    subject=f"🖨️ Printer {new_state} — {subtask}",
                    body=f"Printer state changed to {new_state}.\nFile: {subtask}\nProgress: {progress}%\nAction required — check the printer.",
                    cprint_fn=cprint_fn,
                )
            last_gcode_state["value"] = new_state

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
    parser.add_argument("--ignition_host",       default=IGNITION_HOST)
    parser.add_argument("--ignition_opcua_port", default=IGNITION_OPCUA_PORT, type=int)
    parser.add_argument("--ignition_user",       default=IGNITION_USER)
    parser.add_argument("--ignition_pass",       default=IGNITION_PASS)
    parser.add_argument("--tag_prefix",    default=IGNITION_TAG_PREFIX,
                        help="Ignition tag path prefix (e.g. [default]Factory/Printer)")
    args = parser.parse_args()

    cprint_fn("═══════════════════════════════════════════════", "cyan")
    cprint_fn(" HUMN Factory — Bambu P1S MQTT Bridge", "cyan")
    cprint_fn("═══════════════════════════════════════════════", "cyan")
    cprint_fn(f" Printer  : {args.printer_ip}  (serial: {args.serial})", "white")
    cprint_fn(f" Ignition : opc.tcp://{args.ignition_host}:{args.ignition_opcua_port}", "white")
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
