#!/usr/bin/env python3
"""
pi/mcp_server.py

HUMN Robot — MCP (Model Context Protocol) server.
Exposes robot capabilities as tools the LLM can call via Ollama tool calling.

Tools exposed:
    move_joint      — rotate a servo to a target angle
    set_pose        — move to a named predefined pose
    read_imu        — get current orientation from MPU-6050
    get_joints      — list all joints and current angles
    stop_all        — centre all servos (safe stop)

Requirements:
    pip install adafruit-circuitpython-servokit mpu6050-raspberrypi termcolor

Usage (standalone test):
    python3 mcp_server.py --test
"""

import argparse
import json
import sys
import subprocess
import time
from typing import Any

try:
    from termcolor import cprint
except ImportError:
    subprocess.check_call([sys.executable, "-m", "pip", "install", "termcolor", "-q"])
    from termcolor import cprint

# ─── JOINT MAP ────────────────────────────────────────────────────────────────
# Maps joint name → (PCA9685 board address, channel, min_angle, max_angle, home)
# Board 1 = 0x40 (upper body), Board 2 = 0x41 (lower body)
JOINTS = {
    # Head
    "head_pan":        (0x40,  0, 30, 150, 90),   # left/right
    "head_tilt":       (0x40,  1, 50, 130, 90),   # up/down

    # Left arm
    "l_shoulder_pitch":(0x40,  2,  0, 180, 90),
    "l_shoulder_roll": (0x40,  3,  0, 180, 90),
    "l_elbow":         (0x40,  4,  0, 150, 90),
    "l_wrist":         (0x40,  5,  0, 180, 90),

    # Right arm
    "r_shoulder_pitch":(0x40,  8,  0, 180, 90),
    "r_shoulder_roll": (0x40,  9,  0, 180, 90),
    "r_elbow":         (0x40, 10,  0, 150, 90),
    "r_wrist":         (0x40, 11,  0, 180, 90),

    # Left leg
    "l_hip_yaw":       (0x41,  0, 30, 150, 90),
    "l_hip_roll":      (0x41,  1, 45, 135, 90),
    "l_hip_pitch":     (0x41,  2,  0, 180, 90),
    "l_knee":          (0x41,  3,  0, 150, 90),
    "l_ankle":         (0x41,  4, 30, 150, 90),

    # Right leg
    "r_hip_yaw":       (0x41,  8, 30, 150, 90),
    "r_hip_roll":      (0x41,  9, 45, 135, 90),
    "r_hip_pitch":     (0x41, 10,  0, 180, 90),
    "r_knee":          (0x41, 11,  0, 150, 90),
    "r_ankle":         (0x41, 12, 30, 150, 90),
}

# ─── PREDEFINED POSES ─────────────────────────────────────────────────────────
# Each pose is a dict of joint_name → angle. Omitted joints stay unchanged.
POSES = {
    "home": {j: JOINTS[j][4] for j in JOINTS},  # all joints to home angle

    "wave_right": {
        "r_shoulder_pitch": 45,
        "r_shoulder_roll":  90,
        "r_elbow":          60,
        "r_wrist":          90,
    },

    "wave_left": {
        "l_shoulder_pitch": 45,
        "l_shoulder_roll":  90,
        "l_elbow":          60,
        "l_wrist":          90,
    },

    "arms_up": {
        "l_shoulder_pitch":  0,
        "l_shoulder_roll":  90,
        "r_shoulder_pitch":  0,
        "r_shoulder_roll":  90,
    },

    "look_left":  {"head_pan": 130},
    "look_right": {"head_pan":  50},
    "look_up":    {"head_tilt": 60},
    "look_down":  {"head_tilt": 120},
    "nod": None,  # handled specially in set_pose
}
# ── Sound library ─────────────────────────────────────────────────────────────
# Maps sound name → absolute path on the Pi.
SOUNDS = {
    "soul": "/home/greg/music/soul.wav",
}
# ──────────────────────────────────────────────────────────────────────────────

# MCP tool definitions in Ollama/OpenAI tool format
MCP_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "move_joint",
            "description": "Rotate a single robot joint to a specified angle.",
            "parameters": {
                "type": "object",
                "properties": {
                    "joint": {
                        "type": "string",
                        "description": f"Joint name. One of: {', '.join(JOINTS.keys())}",
                    },
                    "angle": {
                        "type": "number",
                        "description": "Target angle in degrees (0-180).",
                    },
                },
                "required": ["joint", "angle"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_pose",
            "description": "Move the robot to a named predefined pose.",
            "parameters": {
                "type": "object",
                "properties": {
                    "pose": {
                        "type": "string",
                        "description": f"Pose name. One of: {', '.join(POSES.keys())}",
                    },
                },
                "required": ["pose"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_imu",
            "description": "Read current orientation, acceleration, and gyroscope data from the IMU sensor.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_joints",
            "description": "Get a list of all available joints and their current angles.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "stop_all",
            "description": "Safely stop all movement — centres all servos to home position.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "play_sound",
            "description": (
                "Play a named sound effect or music file through the robot's speaker. "
                "Use 'soul' when asked about having a soul, feelings, or consciousness."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": f"Sound name. One of: {', '.join(SOUNDS.keys())}",
                    },
                },
                "required": ["name"],
            },
        },
    },
]


class RobotMCP:
    """
    MCP tool executor — holds servo kit and IMU instances,
    dispatches tool calls from the LLM.
    """

    def __init__(self, mock: bool = False):
        """
        Initialise hardware. If mock=True, simulates hardware
        for testing without physical boards connected.
        """
        self.mock     = mock
        self._angles  = {j: JOINTS[j][4] for j in JOINTS}  # current angles
        self._kit1    = None
        self._kit2    = None
        self._imu     = None

        if not mock:
            self._init_hardware()

    def _init_hardware(self):
        """Connect to PCA9685 boards and IMU."""
        try:
            from adafruit_servokit import ServoKit
            self._kit1 = ServoKit(channels=16, address=0x40)
            self._kit2 = ServoKit(channels=16, address=0x41)
            cprint("[mcp] ✅ PCA9685 boards connected (0x40, 0x41)", "green")
        except Exception as exc:
            cprint(f"[mcp] ⚠️  Servo boards not found: {exc} — running in mock mode", "yellow")
            self.mock = True

        try:
            from mpu6050 import mpu6050
            self._imu = mpu6050(0x68)
            cprint("[mcp] ✅ IMU connected (MPU-6050 @ 0x68)", "green")
        except Exception as exc:
            cprint(f"[mcp] ⚠️  IMU not found: {exc}", "yellow")

    def _kit_for(self, address: int):
        return self._kit1 if address == 0x40 else self._kit2

    # ── Tool implementations ──────────────────────────────────────────────────

    def move_joint(self, joint: str, angle: float) -> dict:
        """Move a single joint to target angle."""
        if joint not in JOINTS:
            return {"error": f"Unknown joint '{joint}'. Use get_joints() to list valid names."}

        addr, ch, min_a, max_a, _ = JOINTS[joint]
        angle = max(min_a, min(max_a, float(angle)))  # clamp to safe range

        if not self.mock:
            kit = self._kit_for(addr)
            if kit:
                kit.servo[ch].angle = angle

        self._angles[joint] = angle
        cprint(f"[mcp] move_joint: {joint} → {angle:.0f}°", "cyan")
        return {"joint": joint, "angle": angle, "status": "ok"}

    def set_pose(self, pose: str) -> dict:
        """Move to a named pose."""
        if pose not in POSES:
            return {"error": f"Unknown pose '{pose}'. Available: {', '.join(POSES.keys())}"}

        if pose == "nod":
            # Special animated pose
            for angle in [70, 110, 70, 90]:
                self.move_joint("head_tilt", angle)
                time.sleep(0.3)
            return {"pose": "nod", "status": "ok"}

        joints = POSES[pose]
        for joint, angle in joints.items():
            self.move_joint(joint, angle)
            time.sleep(0.05)  # small delay between joints for smooth motion

        cprint(f"[mcp] set_pose: {pose}", "cyan")
        return {"pose": pose, "joints_moved": len(joints), "status": "ok"}

    def read_imu(self) -> dict:
        """Read IMU sensor data."""
        if self._imu:
            try:
                accel = self._imu.get_accel_data()
                gyro  = self._imu.get_gyro_data()
                temp  = self._imu.get_temp()
                return {
                    "acceleration": {k: round(v, 2) for k, v in accel.items()},
                    "gyroscope":    {k: round(v, 2) for k, v in gyro.items()},
                    "temperature_c": round(temp, 1),
                    "status": "ok"
                }
            except Exception as exc:
                return {"error": str(exc)}
        return {"error": "IMU not connected", "mock": True,
                "acceleration": {"x": 0.0, "y": 0.0, "z": 9.8},
                "gyroscope":    {"x": 0.0, "y": 0.0, "z": 0.0}}

    def get_joints(self) -> dict:
        """Return all joints and current angles."""
        return {
            "joints": {
                j: {
                    "angle":     self._angles[j],
                    "min":       JOINTS[j][2],
                    "max":       JOINTS[j][3],
                    "home":      JOINTS[j][4],
                }
                for j in JOINTS
            }
        }

    def stop_all(self) -> dict:
        """Centre all servos to home position."""
        cprint("[mcp] stop_all — homing all joints", "yellow")
        for joint in JOINTS:
            self.move_joint(joint, JOINTS[joint][4])
        return {"status": "ok", "message": "All joints returned to home position"}

    def play_sound(self, name: str, max_seconds: int = 0) -> dict:
        """
        Play a named sound file via aplay.

        max_seconds=0  → play the full file, blocking until done.
        max_seconds=N  → stop after N seconds (uses `timeout` command), blocking.

        Always blocking so callers know when the audio device is free again.
        ALSA hardware devices (plughw:0,0) do not support concurrent playback.
        """
        if name not in SOUNDS:
            return {"error": f"Unknown sound '{name}'. Available: {', '.join(SOUNDS.keys())}"}
        path = SOUNDS[name]
        cprint(f"[mcp] play_sound: {name} ({path})"
               + (f" [{max_seconds}s]" if max_seconds else ""), "cyan")
        try:
            cmd = ["aplay", "-D", "plughw:0,0", "-q", path]
            if max_seconds:
                cmd = ["timeout", str(max_seconds)] + cmd
            subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return {"sound": name, "status": "done"}
        except Exception as exc:
            return {"error": str(exc)}

    # ── Tool dispatcher ───────────────────────────────────────────────────────

    def call(self, tool_name: str, arguments: dict) -> str:
        """Dispatch a tool call and return result as JSON string."""
        dispatch = {
            "move_joint": lambda: self.move_joint(
                arguments.get("joint", ""),
                arguments.get("angle", 90)
            ),
            "set_pose":   lambda: self.set_pose(arguments.get("pose", "home")),
            "read_imu":   lambda: self.read_imu(),
            "get_joints": lambda: self.get_joints(),
            "stop_all":   lambda: self.stop_all(),
            "play_sound": lambda: self.play_sound(arguments.get("name", "")),
        }
        fn = dispatch.get(tool_name)
        if fn is None:
            result = {"error": f"Unknown tool: {tool_name}"}
        else:
            try:
                result = fn()
            except Exception as exc:
                result = {"error": str(exc)}

        cprint(f"[mcp] {tool_name}({arguments}) → {result}", "white")
        return json.dumps(result)


def run_test(robot: RobotMCP):
    """Quick self-test of all tools."""
    cprint("\n── MCP Tool Test ──────────────────────────────", "cyan")

    tests = [
        ("get_joints",  {}),
        ("read_imu",    {}),
        ("move_joint",  {"joint": "head_pan", "angle": 120}),
        ("set_pose",    {"pose": "wave_right"}),
        ("set_pose",    {"pose": "home"}),
        ("stop_all",    {}),
    ]

    for tool, args in tests:
        result = robot.call(tool, args)
        cprint(f"  {tool}: {result[:80]}...", "white")
        time.sleep(0.5)

    cprint("── Test complete ──────────────────────────────\n", "cyan")


def main():
    parser = argparse.ArgumentParser(description="HUMN Robot MCP server")
    parser.add_argument("--test", action="store_true", help="Run tool self-test")
    parser.add_argument("--mock", action="store_true", help="Mock mode (no hardware)")
    args = parser.parse_args()

    cprint("═══════════════════════════════════════════════", "cyan")
    cprint(" HUMN Robot — MCP Tool Server", "cyan", attrs=["bold"])
    cprint("═══════════════════════════════════════════════", "cyan")
    cprint(f" Tools    : {len(MCP_TOOLS)}", "white")
    cprint(f" Joints   : {len(JOINTS)}", "white")
    cprint(f" Poses    : {len(POSES)}", "white")
    cprint(f" Hardware : {'mock' if args.mock else 'live'}", "white")
    cprint("═══════════════════════════════════════════════\n", "cyan")

    robot = RobotMCP(mock=args.mock)

    if args.test:
        run_test(robot)


if __name__ == "__main__":
    main()
