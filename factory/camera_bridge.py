#!/usr/bin/env python3
"""
factory/camera_bridge.py

Converts Tapo TC60 RTSP stream → MJPEG HTTP server.
Uses ffmpeg subprocess directly (more reliable than OpenCV for RTSP).
Ignition Perspective Image component connects to:
    http://localhost:8090/stream

Requirements:
    brew install ffmpeg
    pip install termcolor

Usage:
    python3 camera_bridge.py
    python3 camera_bridge.py --ip 192.168.1.100 --port 8090
"""

import argparse
import os
import queue
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

# ─── CONFIG (override via .envrc or environment variables) ───────────────────
DEFAULT_CAMERA_IP   = os.environ.get("CAMERA_IP",   "192.168.3.148")
DEFAULT_CAMERA_USER = os.environ.get("CAMERA_USER", "greg%40netroworx.com")
DEFAULT_CAMERA_PASS = os.environ.get("CAMERA_PASS", "")
DEFAULT_PORT        = int(os.environ.get("CAMERA_PORT", "8090"))
DEFAULT_FPS         = 10
DEFAULT_WIDTH       = 1280
DEFAULT_HEIGHT      = 720
# ──────────────────────────────────────────────────────────────────────────────

try:
    from termcolor import cprint
except ImportError:
    subprocess.check_call([sys.executable, "-m", "pip", "install", "termcolor", "-q"])
    from termcolor import cprint

# Global latest JPEG frame shared between capture thread and HTTP handlers
_frame_lock   = threading.Lock()
_latest_frame = None


def check_ffmpeg():
    """Ensure ffmpeg is available."""
    try:
        subprocess.run(["ffmpeg", "-version"], capture_output=True, check=True)
    except FileNotFoundError:
        cprint("[camera] ❌ ffmpeg not found. Install with: brew install ffmpeg", "red")
        sys.exit(1)


def capture_thread(rtsp_url: str, width: int, height: int, fps: int):
    """
    Background thread: runs ffmpeg to decode RTSP → raw JPEG frames,
    reads them from stdout, stores latest in _latest_frame.
    Auto-reconnects on failure.
    """
    global _latest_frame

    # ffmpeg command:
    #   -rtsp_transport tcp   : more reliable than UDP on home networks
    #   -i <url>              : RTSP input
    #   -vf fps=N,scale=WxH   : limit frame rate and resize
    #   -f image2pipe         : output as raw image stream
    #   -vcodec mjpeg         : encode each frame as JPEG
    #   -q:v 5                : JPEG quality (2=best, 31=worst)
    #   pipe:1                : write to stdout
    cmd = [
        "ffmpeg",
        "-loglevel", "warning",
        "-rtsp_transport", "tcp",
        "-i", rtsp_url,
        "-vf", f"fps={fps},scale={width}:{height}",
        "-f", "image2pipe",
        "-vcodec", "mjpeg",
        "-q:v", "5",
        "pipe:1"
    ]

    while True:
        cprint(f"[camera] Connecting to {rtsp_url}", "cyan")
        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=0
            )
        except Exception as exc:
            cprint(f"[camera] ❌ Failed to start ffmpeg: {exc} — retrying in 5s", "red")
            time.sleep(5)
            continue

        # Stream ffmpeg stderr to console in a background thread so errors are visible
        def _log_stderr(p):
            for line in p.stderr:
                txt = line.decode(errors="replace").rstrip()
                if txt:
                    cprint(f"[ffmpeg] {txt}", "yellow")
        threading.Thread(target=_log_stderr, args=(proc,), daemon=True).start()

        cprint("[camera] ✅ ffmpeg started — waiting for first frame...", "green")
        buf = b""
        first_frame = True

        try:
            while True:
                chunk = proc.stdout.read(4096)
                if not chunk:
                    # ffmpeg exited
                    break
                buf += chunk

                # JPEG frames are delimited by SOI (FFD8) and EOI (FFD9) markers
                while True:
                    start = buf.find(b"\xff\xd8")
                    end   = buf.find(b"\xff\xd9", start + 2)
                    if start == -1 or end == -1:
                        break
                    jpeg = buf[start:end + 2]
                    buf  = buf[end + 2:]

                    with _frame_lock:
                        _latest_frame = jpeg

                    if first_frame:
                        cprint("[camera] ✅ First frame received — stream live", "green")
                        first_frame = False

        except Exception as exc:
            cprint(f"[camera] ⚠️  Stream error: {exc}", "yellow")
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()

        rc = proc.returncode
        cprint(f"[camera] ⚠️  ffmpeg exited (rc={rc}) — reconnecting in 3s", "yellow")
        time.sleep(3)


class MJPEGHandler(BaseHTTPRequestHandler):
    """HTTP handler that streams MJPEG to Ignition Perspective."""

    def log_message(self, format, *args):
        pass  # Suppress per-request access logs

    def do_GET(self):
        if self.path == "/stream":
            self._stream()
        elif self.path == "/snapshot":
            self._snapshot()
        elif self.path == "/health":
            self._health()
        else:
            self.send_error(404)

    def _stream(self):
        """Multipart MJPEG stream — use this URL in Ignition Image component."""
        self.send_response(200)
        self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()

        cprint(f"[http] Client connected: {self.client_address[0]}", "cyan")
        try:
            while True:
                with _frame_lock:
                    frame = _latest_frame

                if frame is None:
                    time.sleep(0.05)
                    continue

                self.wfile.write(b"--frame\r\n")
                self.wfile.write(b"Content-Type: image/jpeg\r\n\r\n")
                self.wfile.write(frame)
                self.wfile.write(b"\r\n")
                time.sleep(1.0 / 10)  # ~10 fps to clients
        except (BrokenPipeError, ConnectionResetError):
            cprint(f"[http] Client disconnected: {self.client_address[0]}", "yellow")

    def _snapshot(self):
        """Single JPEG — useful for low-frequency polling."""
        with _frame_lock:
            frame = _latest_frame
        if frame is None:
            self.send_error(503, "No frame available yet")
            return
        self.send_response(200)
        self.send_header("Content-Type", "image/jpeg")
        self.send_header("Content-Length", str(len(frame)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(frame)

    def _health(self):
        """Health check — returns JSON."""
        with _frame_lock:
            ok = _latest_frame is not None
        body = b'{"status":"ok"}' if ok else b'{"status":"no_frame"}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)


def main():
    parser = argparse.ArgumentParser(description="Tapo TC60 RTSP → MJPEG bridge")
    parser.add_argument("--ip",        default=DEFAULT_CAMERA_IP,   help="Camera IP address")
    parser.add_argument("--user",      default=DEFAULT_CAMERA_USER, help="Camera username (@ as %%40)")
    parser.add_argument("--password",  default=DEFAULT_CAMERA_PASS, help="Camera password")
    parser.add_argument("--port",      default=DEFAULT_PORT,  type=int, help="HTTP server port")
    parser.add_argument("--fps",       default=DEFAULT_FPS,   type=int, help="Target frame rate")
    parser.add_argument("--width",     default=DEFAULT_WIDTH, type=int)
    parser.add_argument("--height",    default=DEFAULT_HEIGHT, type=int)
    parser.add_argument("--substream", action="store_true",
                        help="Use sub-stream (lower res, less CPU)")
    args = parser.parse_args()

    check_ffmpeg()

    stream_path = "stream2" if args.substream else "stream1"
    rtsp_url = f"rtsp://{args.user}:{args.password}@{args.ip}:554/{stream_path}"

    cprint("═══════════════════════════════════════════════", "cyan")
    cprint(" HUMN Factory — Tapo TC60 Camera Bridge", "cyan", attrs=["bold"])
    cprint("═══════════════════════════════════════════════", "cyan")
    cprint(f" RTSP   : {rtsp_url}", "white")
    cprint(f" Stream : http://localhost:{args.port}/stream", "green")
    cprint(f" Snap   : http://localhost:{args.port}/snapshot", "green")
    cprint(f" Health : http://localhost:{args.port}/health", "white")
    cprint("───────────────────────────────────────────────", "cyan")
    cprint(" Ignition Perspective → Image component source:", "white")
    cprint(f"   http://localhost:{args.port}/stream", "yellow", attrs=["bold"])
    cprint("═══════════════════════════════════════════════\n", "cyan")

    # Start ffmpeg capture thread
    t = threading.Thread(
        target=capture_thread,
        args=(rtsp_url, args.width, args.height, args.fps),
        daemon=True
    )
    t.start()

    # Start MJPEG HTTP server
    # Allow address reuse so restarts don't hit "Address already in use"
    HTTPServer.allow_reuse_address = True
    server = HTTPServer(("0.0.0.0", args.port), MJPEGHandler)
    cprint(f"[http] MJPEG server listening on port {args.port}", "green")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        cprint("\n[camera] Shutting down.", "yellow")
        server.shutdown()


if __name__ == "__main__":
    main()
