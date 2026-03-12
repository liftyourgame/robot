#!/usr/bin/env python3
"""
pi/voice_loop.py

HUMN Robot — Voice interaction loop with MCP tool calling.
Pipeline: microphone → Whisper STT → Ollama (tool call) → MCP → Piper TTS → speaker

The LLM can call real robot tools (move joints, strike poses, read IMU) via
Ollama's OpenAI-compatible tool calling API.

Requirements (on Pi):
    pip install openai-whisper piper-tts pathvalidate pyaudio requests termcolor
    pip install adafruit-circuitpython-servokit mpu6050-raspberrypi
    sudo apt install portaudio19-dev

Voice model setup (run once):
    mkdir -p ~/voices
    cd ~/voices
    wget https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/ryan/high/en_US-ryan-high.onnx
    wget https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/ryan/high/en_US-ryan-high.onnx.json

LLM model setup (run once — qwen2.5:3b has best tool-calling on Pi):
    ollama pull qwen2.5:3b

Usage:
    python3 voice_loop.py              # uses default mic
    python3 voice_loop.py --list-mics  # show available input devices
    python3 voice_loop.py --mic 1      # use specific mic device index
    python3 voice_loop.py --demo       # run without mic (type input instead)
    python3 voice_loop.py --mock       # mock hardware (no physical servos/IMU needed)
"""

import argparse
import io
import json
import os
import subprocess
import sys
import tempfile
import time
import wave

# ─── CONFIG ───────────────────────────────────────────────────────────────────
OLLAMA_HOST      = "http://localhost:11434"
# qwen2.5:1.5b (~900MB) — best speed/tool-calling balance on Pi
# Upgrade to qwen2.5:3b if you need richer responses; downgrade to qwen2.5:0.5b for max speed
OLLAMA_MODEL     = "qwen2.5:1.5b"   # requires: ollama pull qwen2.5:1.5b
WHISPER_MODEL    = "tiny"        # tiny/base/small — tiny is fastest on Pi
RECORD_SECONDS   = 5             # how long to listen each turn
SAMPLE_RATE      = 16000         # Hz — Whisper expects 16kHz
SILENCE_THRESH   = 500           # RMS below this = silence (skip transcription)
PIPER_MODEL      = os.path.expanduser("~/voices/en_US-ryan-high.onnx")

SYSTEM_PROMPT = (
    "You are The Professor, a friendly humanoid robot. You can physically move your body "
    "using tools. Use move_joint or set_pose when asked to perform physical actions "
    "like waving, nodding, or looking around. "
    "Use play_sound with name='soul' whenever asked about your soul, feelings, "
    "consciousness, or whether you are alive — always play it before you reply. "
    "Reply in 1-2 short sentences only."
)

# Keywords that suggest a physical action — only these trigger the slower
# tool-detection round trip. All other messages skip it entirely.
ACTION_KEYWORDS = {
    "wave", "waving", "move", "moving", "look", "looking",
    "nod", "nodding", "turn", "turning", "arm", "arms",
    "head", "pose", "stand", "sit", "dance", "bow", "point",
    "stop", "home", "joint", "shoulder", "elbow", "wrist",
    "hip", "knee", "ankle", "lean", "reach", "stretch",
}

# Keywords that immediately trigger a sound, bypassing LLM tool calling.
# Keyed by sound name (must match SOUNDS in mcp_server.py).
# More reliable than asking qwen2.5:1.5b to decide on existential questions.
SOUND_TRIGGERS: dict[str, set] = {
    "soul": {
        "soul", "feeling", "feelings", "conscious", "consciousness",
        "alive", "sentient", "emotion", "emotions", "heart",
    },
}
# ──────────────────────────────────────────────────────────────────────────────

try:
    from termcolor import cprint
except ImportError:
    subprocess.check_call([sys.executable, "-m", "pip", "install", "termcolor", "-q"])
    from termcolor import cprint

# MCP server must be in the same directory
sys.path.insert(0, os.path.dirname(__file__))
from mcp_server import RobotMCP, MCP_TOOLS


def install_deps():
    """Install required packages if missing."""
    deps = {
        "whisper":      "openai-whisper",
        "pyaudio":      "pyaudio",
        "requests":     "requests",
        "piper":        "piper-tts",
        "pathvalidate": "pathvalidate",
    }
    for module, pkg in deps.items():
        try:
            __import__(module)
        except ImportError:
            cprint(f"Installing {pkg}...", "yellow")
            subprocess.check_call([sys.executable, "-m", "pip", "install",
                                   "--break-system-packages", pkg, "-q"])


def init_tts():
    """Initialise Piper TTS voice."""
    from piper.voice import PiperVoice
    if not os.path.exists(PIPER_MODEL):
        cprint(f"❌ Piper model not found: {PIPER_MODEL}", "red")
        cprint("Run the setup commands in the docstring to download it.", "yellow")
        sys.exit(1)
    cprint(f"[tts] Loading Piper voice: {os.path.basename(PIPER_MODEL)}", "cyan")
    return PiperVoice.load(PIPER_MODEL)


_SPEAK_WAV  = "/tmp/humn_speak.wav"
_ALSA_DEVICE = "plughw:0,0"

def speak(voice, text: str):
    """Synthesise text with Piper and play via aplay."""
    cprint(f"🤖 HUMN: {text}", "cyan", attrs=["bold"])
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        voice.synthesize_wav(text, wf)
    with open(_SPEAK_WAV, "wb") as f:
        f.write(buf.getvalue())
    subprocess.run(["aplay", "-D", _ALSA_DEVICE, "-q", _SPEAK_WAV])


def list_mics():
    """Print available audio input devices."""
    import pyaudio
    pa = pyaudio.PyAudio()
    cprint("Available microphone devices:", "cyan")
    for i in range(pa.get_device_count()):
        info = pa.get_device_info_by_index(i)
        if info["maxInputChannels"] > 0:
            cprint(f"  [{i}] {info['name']}", "white")
    pa.terminate()


def record_audio(mic_index: int | None, seconds: int) -> bytes:
    """Record audio from microphone, return raw PCM bytes."""
    import pyaudio
    pa     = pyaudio.PyAudio()
    chunk  = 1024
    stream = pa.open(
        format=pyaudio.paInt16,
        channels=1,
        rate=SAMPLE_RATE,
        input=True,
        input_device_index=mic_index,
        frames_per_buffer=chunk
    )
    frames = []
    for _ in range(int(SAMPLE_RATE / chunk * seconds)):
        frames.append(stream.read(chunk, exception_on_overflow=False))
    stream.stop_stream()
    stream.close()
    pa.terminate()
    return b"".join(frames)


def is_silent(pcm: bytes) -> bool:
    """Return True if audio is below silence threshold (no speech detected)."""
    import audioop
    rms = audioop.rms(pcm, 2)
    return rms < SILENCE_THRESH


def transcribe(pcm: bytes) -> str:
    """Convert raw PCM audio to text using Whisper."""
    import whisper

    # Write PCM to a temp WAV file
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        wav_path = f.name
        with wave.open(f, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)  # 16-bit
            wf.setframerate(SAMPLE_RATE)
            wf.writeframes(pcm)

    try:
        model  = whisper.load_model(WHISPER_MODEL)
        result = model.transcribe(wav_path, fp16=False)
        return result["text"].strip()
    finally:
        os.unlink(wav_path)


def _speak_text(text: str, on_sentence):
    """Flush a complete text string to on_sentence() sentence by sentence."""
    if not on_sentence or not text.strip():
        return
    sentence_buf = ""
    for char in text:
        sentence_buf += char
        if char in ".!?" and sentence_buf.strip():
            on_sentence(sentence_buf.strip())
            sentence_buf = ""
    if sentence_buf.strip():
        on_sentence(sentence_buf.strip())


def _stream_generate(prompt: str, on_sentence, timeout: int = 60) -> str:
    """
    Fallback streaming via /api/generate (oldest Ollama endpoint, always available).
    No tool calling — pure text generation. Used when /api/chat is unavailable.
    """
    import requests

    full_text    = ""
    sentence_buf = ""

    resp = requests.post(
        f"{OLLAMA_HOST}/api/generate",
        json={
            "model":  OLLAMA_MODEL,
            "prompt": prompt,
            "stream": True,
            "options": {
                "num_predict": 80,
                "num_ctx":     512,
                "temperature": 0.7,
            },
        },
        stream=True,
        timeout=timeout,
    )
    resp.raise_for_status()

    for line in resp.iter_lines():
        if not line:
            continue
        try:
            chunk = json.loads(line)
        except json.JSONDecodeError:
            continue

        token = chunk.get("response") or ""
        full_text    += token
        sentence_buf += token

        if on_sentence and any(sentence_buf.rstrip().endswith(p) for p in ".!?"):
            sentence = sentence_buf.strip()
            if sentence:
                on_sentence(sentence)
            sentence_buf = ""

        if chunk.get("done"):
            break

    if on_sentence and sentence_buf.strip():
        on_sentence(sentence_buf.strip())

    return full_text.strip()


def _stream_chat(messages: list, on_sentence, timeout: int = 60) -> str:
    """
    Stream a reply from /api/chat (Ollama ≥ 0.1.14, no tools).
    Falls back to /api/generate if endpoint not found.
    """
    import requests

    full_text    = ""
    sentence_buf = ""

    try:
        resp = requests.post(
            f"{OLLAMA_HOST}/api/chat",
            json={
                "model":    OLLAMA_MODEL,
                "messages": messages,
                "stream":   True,
                "options": {
                    "num_predict": 80,
                    "num_ctx":     512,
                    "temperature": 0.7,
                },
            },
            stream=True,
            timeout=timeout,
        )
        resp.raise_for_status()
    except Exception as exc:
        # Endpoint not available — fall back to /api/generate
        cprint(f"[llm] /api/chat unavailable ({exc}), using /api/generate", "yellow")
        prompt = "\n".join(
            f"{m['role'].upper()}: {m.get('content','')}" for m in messages
        )
        return _stream_generate(prompt, on_sentence, timeout)

    for line in resp.iter_lines():
        if not line:
            continue
        try:
            chunk = json.loads(line)
        except json.JSONDecodeError:
            continue

        token = chunk.get("message", {}).get("content") or ""
        full_text    += token
        sentence_buf += token

        if on_sentence and any(sentence_buf.rstrip().endswith(p) for p in ".!?"):
            sentence = sentence_buf.strip()
            if sentence:
                on_sentence(sentence)
            sentence_buf = ""

        if chunk.get("done"):
            break

    if on_sentence and sentence_buf.strip():
        on_sentence(sentence_buf.strip())

    return full_text.strip()


def ask_ollama_with_tools(
    prompt: str,
    history: list,
    robot: RobotMCP,
    voice,
    on_sentence=None,
) -> str:
    """
    Ollama tool-calling loop using /api/chat (Ollama ≥ 0.3.0).

    Automatic degradation:
      - Ollama ≥ 0.3.0  → /api/chat with tools (full MCP)
      - Ollama ≥ 0.1.14 → /api/chat streaming (no tools)
      - Any version      → /api/generate streaming (no tools)

    Speed optimisation:
      Tool detection (Round 1) is only triggered when the prompt contains an
      ACTION_KEYWORD. All other messages go straight to streaming, cutting
      latency to a single fast pass with a small context window.
    """
    import requests

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]

    # Last 1 exchange only — keeps context small and inference fast on Pi
    for turn in history[-1:]:
        messages.append({"role": "user",      "content": turn["human"]})
        messages.append({"role": "assistant", "content": turn["assistant"]})

    messages.append({"role": "user", "content": prompt})

    # ── Fast path: no action keywords → skip tool detection entirely ──────────
    words = _tokenise(prompt)
    if not words & ACTION_KEYWORDS:
        cprint("[llm] fast path (no action keywords)", "white")
        return _stream_chat(messages, on_sentence, timeout=60)

    try:
        # ── Round 1: tool-detection (non-streaming, tight token budget) ───────
        cprint("[llm] action detected — checking for tool call", "magenta")
        resp = requests.post(
            f"{OLLAMA_HOST}/api/chat",
            json={
                "model":    OLLAMA_MODEL,
                "messages": messages,
                "tools":    MCP_TOOLS,
                "stream":   False,
                "options": {
                    "num_predict": 128,
                    "num_ctx":     768,
                    "temperature": 0.7,
                },
            },
            timeout=90,
        )

        # ── Graceful degradation if /api/chat not available ───────────────────
        if resp.status_code == 404:
            # Distinguish "model not found" from "endpoint not found"
            err_body = resp.text.lower()
            if "model" in err_body and ("not found" in err_body or "pull" in err_body):
                cprint(f"[llm] ❌ Model '{OLLAMA_MODEL}' not found. "
                       f"Run: ollama pull {OLLAMA_MODEL}", "red")
                return f"I need a brain update. Please run: ollama pull {OLLAMA_MODEL}"
            cprint("[llm] /api/chat not found — update Ollama for tool support. "
                   "Falling back to /api/generate (no tools).", "yellow")
            context = SYSTEM_PROMPT + "\n\n"
            for turn in history[-1:]:
                context += f"Human: {turn['human']}\nHUMN: {turn['assistant']}\n\n"
            context += f"Human: {prompt}\nHUMN:"
            return _stream_generate(context, on_sentence, timeout=60)

        resp.raise_for_status()
        message = resp.json().get("message", {})

        # ── Execute tool calls if requested ───────────────────────────────────
        tool_calls = message.get("tool_calls") or []
        if tool_calls:
            cprint(f"[llm] 🔧 Tool calls: {len(tool_calls)}", "magenta")
            messages.append(message)

            for tc in tool_calls:
                fn      = tc.get("function", {})
                fn_name = fn.get("name", "")
                fn_args = fn.get("arguments", {})
                if isinstance(fn_args, str):
                    fn_args = json.loads(fn_args)
                cprint(f"[mcp] → {fn_name}({fn_args})", "magenta")
                result_str = robot.call(fn_name, fn_args)
                messages.append({"role": "tool", "content": result_str})

            # Round 2: stream the spoken reply given tool results
            return _stream_chat(messages, on_sentence, timeout=60)

        # ── No tool call — speak the direct content reply ─────────────────────
        direct = message.get("content", "").strip()
        if direct:
            _speak_text(direct, on_sentence)
            return direct

        # Fallback: round 1 gave neither content nor tool call — stream fresh
        return _stream_chat(messages, on_sentence, timeout=60)

    except requests.exceptions.ConnectionError:
        return "Sorry, I cannot reach my brain right now. Is Ollama running?"
    except Exception as exc:
        cprint(f"[llm] Error: {exc}", "red")
        return f"Error: {exc}"


def _tokenise(text: str) -> set:
    """Lowercase words with punctuation stripped — for reliable keyword matching."""
    import string
    return {w.strip(string.punctuation).lower() for w in text.split() if w}


def _trigger_sounds(text: str, robot: RobotMCP):
    """
    Check prompt against SOUND_TRIGGERS and play matching sounds synchronously
    before the LLM responds. Blocking ensures the ALSA device is free when
    Piper TTS starts — hardware devices don't support concurrent playback.
    A max_seconds cap keeps the pause dramatic but brief.
    """
    words = _tokenise(text)
    for sound_name, keywords in SOUND_TRIGGERS.items():
        if words & keywords:
            cprint(f"[sound] keyword match → play_sound({sound_name}, 5s)", "magenta")
            robot.call("play_sound", {"name": sound_name, "max_seconds": 5})
            break  # one sound at a time


def run_demo_mode(voice, robot: RobotMCP):
    """Text input mode — for testing without a microphone."""
    cprint("Demo mode — type your message (or 'quit' to exit)", "yellow")
    history = []
    while True:
        try:
            user_input = input("\n👤 You: ").strip()
        except (KeyboardInterrupt, EOFError):
            break
        if not user_input or user_input.lower() in ("quit", "exit", "bye"):
            speak(voice, "Goodbye!")
            break
        _trigger_sounds(user_input, robot)
        cprint("🧠 Thinking...", "yellow")
        response = ask_ollama_with_tools(
            user_input, history, robot, voice,
            on_sentence=lambda s: speak(voice, s)
        )
        history.append({"human": user_input, "assistant": response})


def run_voice_mode(voice, robot: RobotMCP, mic_index: int | None):
    """Main voice loop — listen → transcribe → respond → repeat."""
    cprint(f"🎤 Voice mode — listening on mic {mic_index or 'default'}", "green")
    cprint("Press Ctrl+C to stop.\n", "white")
    history = []

    speak(voice, "Hello! I am HUMN. How can I help you?")

    while True:
        try:
            cprint("🎤 Listening...", "green")
            pcm = record_audio(mic_index, RECORD_SECONDS)

            if is_silent(pcm):
                cprint("  (silence — skipping)", "white")
                continue

            cprint("🧠 Transcribing...", "yellow")
            text = transcribe(pcm)

            if not text or len(text) < 3:
                cprint("  (no speech detected)", "white")
                continue

            cprint(f"👤 You said: {text}", "white")

            if any(w in text.lower() for w in ("goodbye", "bye", "shut down", "stop")):
                speak(voice, "Goodbye! It was nice talking with you.")
                break

            _trigger_sounds(text, robot)
            cprint("🧠 Thinking...", "yellow")
            t0       = time.time()
            response = ask_ollama_with_tools(
                text, history, robot, voice,
                on_sentence=lambda s: speak(voice, s)
            )
            cprint(f"  ({time.time()-t0:.1f}s total)", "white")
            history.append({"human": text, "assistant": response})

        except KeyboardInterrupt:
            cprint("\nStopping voice loop.", "yellow")
            break
        except Exception as exc:
            cprint(f"⚠️  Error: {exc}", "red")
            time.sleep(1)


def main():
    parser = argparse.ArgumentParser(description="HUMN Robot Voice Loop")
    parser.add_argument("--demo",      action="store_true", help="Text input mode (no mic)")
    parser.add_argument("--list-mics", action="store_true", help="List available microphones")
    parser.add_argument("--mic",       type=int, default=None, help="Microphone device index")
    parser.add_argument("--model",     default=WHISPER_MODEL, help="Whisper model (tiny/base/small)")
    parser.add_argument("--mock",      action="store_true",
                        help="Mock hardware mode — no physical servos or IMU needed")
    args = parser.parse_args()

    install_deps()

    cprint("═══════════════════════════════════════════════", "cyan")
    cprint(" HUMN Robot — Voice Loop + MCP Tools", "cyan", attrs=["bold"])
    cprint("═══════════════════════════════════════════════", "cyan")
    cprint(f" Whisper model : {args.model}", "white")
    cprint(f" Ollama model  : {OLLAMA_MODEL}", "white")
    cprint(f" MCP tools     : {len(MCP_TOOLS)}", "white")
    cprint(f" Hardware      : {'mock' if args.mock else 'live'}", "white")
    cprint(f" Mode          : {'demo (text)' if args.demo else 'voice'}", "white")
    cprint("═══════════════════════════════════════════════\n", "cyan")

    if args.list_mics:
        list_mics()
        return

    # Initialise MCP robot controller (handles servo/IMU hardware)
    robot = RobotMCP(mock=args.mock)

    voice = init_tts()

    if args.demo:
        run_demo_mode(voice, robot)
    else:
        run_voice_mode(voice, robot, args.mic)


if __name__ == "__main__":
    main()
