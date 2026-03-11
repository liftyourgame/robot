#!/usr/bin/env python3
"""
pi/voice_loop.py

HUMN Robot — Voice interaction loop.
Pipeline: microphone → Whisper STT → Ollama/Phi-3 → pyttsx3 TTS → speaker

Requirements (on Pi):
    pip install openai-whisper pyttsx3 pyaudio requests termcolor
    sudo apt install espeak espeak-ng portaudio19-dev

Usage:
    python3 voice_loop.py              # uses default mic
    python3 voice_loop.py --list-mics  # show available input devices
    python3 voice_loop.py --mic 1      # use specific mic device index
    python3 voice_loop.py --demo       # run without mic (type input instead)
"""

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
import wave

# ─── CONFIG ───────────────────────────────────────────────────────────────────
OLLAMA_URL       = "http://localhost:11434/api/generate"
#OLLAMA_MODEL     = "phi3:mini"
OLLAMA_MODEL     = "qwen2:0.5b"
# 💡 Faster alternative: "qwen2:0.5b" (~400MB, ~4x faster, slightly less capable)
# Switch with: ollama pull qwen2:0.5b  then change OLLAMA_MODEL above
WHISPER_MODEL    = "tiny"       # tiny/base/small — tiny is fastest on Pi
RECORD_SECONDS   = 5            # how long to listen each turn
SAMPLE_RATE      = 16000        # Hz — Whisper expects 16kHz
SILENCE_THRESH   = 500          # RMS below this = silence (skip transcription)
TTS_RATE         = 175          # words per minute for espeak
TTS_VOICE        = "en"         # espeak voice

#SYSTEM_PROMPT = "You are HUMN, a friendly robot that can sing and dance. Reply in 1-2 short sentences only."
SYSTEM_PROMPT = "You are HUMN, a friendly robot that can sing and dance."
# ──────────────────────────────────────────────────────────────────────────────

try:
    from termcolor import cprint
except ImportError:
    subprocess.check_call([sys.executable, "-m", "pip", "install", "termcolor", "-q"])
    from termcolor import cprint


def install_deps():
    """Install required packages if missing."""
    deps = {
        "whisper":  "openai-whisper",
        "pyttsx3":  "pyttsx3",
        "pyaudio":  "pyaudio",
        "requests": "requests",
    }
    for module, pkg in deps.items():
        try:
            __import__(module)
        except ImportError:
            cprint(f"Installing {pkg}...", "yellow")
            subprocess.check_call([sys.executable, "-m", "pip", "install",
                                   "--break-system-packages", pkg, "-q"])


def init_tts():
    """Initialise pyttsx3 TTS engine."""
    import pyttsx3
    engine = pyttsx3.init()
    engine.setProperty("rate", TTS_RATE)
    voices = engine.getProperty("voices")
    # Prefer espeak English voice
    for v in voices:
        if "english" in v.name.lower() or v.id.endswith(TTS_VOICE):
            engine.setProperty("voice", v.id)
            break
    return engine


def speak(engine, text: str):
    """Speak text aloud and print it."""
    cprint(f"🤖 HUMN: {text}", "cyan", attrs=["bold"])
    engine.say(text)
    engine.runAndWait()


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


def ask_ollama_stream(prompt: str, history: list, on_sentence=None) -> str:
    """
    Stream response from Ollama token by token.
    Calls on_sentence(sentence) each time a complete sentence is ready
    so TTS can start speaking immediately rather than waiting for full response.
    Returns the full response string.
    """
    import requests

    # Short context — only last 2 exchanges to keep prompt small
    context = SYSTEM_PROMPT + "\n\n"
    for turn in history[-2:]:
        context += f"Human: {turn['human']}\nHUMN: {turn['assistant']}\n\n"
    context += f"Human: {prompt}\nHUMN:"

    try:
        resp = requests.post(
            OLLAMA_URL,
            json={
                "model":       OLLAMA_MODEL,
                "prompt":      context,
                "stream":      True,
                "options": {
                    "num_predict": 80,    # max tokens — keeps responses short
                    "num_ctx":     512,   # small context window = faster
                    "temperature": 0.7,
                }
            },
            stream=True,
            timeout=60
        )
        resp.raise_for_status()

        full_response = ""
        sentence_buf  = ""

        for line in resp.iter_lines():
            if not line:
                continue
            try:
                chunk = json.loads(line)
            except json.JSONDecodeError:
                continue

            token = chunk.get("response", "")
            full_response += token
            sentence_buf  += token

            # Speak each sentence as it completes
            if on_sentence and any(sentence_buf.rstrip().endswith(p) for p in ".!?"):
                sentence = sentence_buf.strip()
                if sentence:
                    on_sentence(sentence)
                sentence_buf = ""

            if chunk.get("done"):
                break

        # Speak any remaining text
        if on_sentence and sentence_buf.strip():
            on_sentence(sentence_buf.strip())

        return full_response.strip()

    except requests.exceptions.ConnectionError:
        return "Sorry, I cannot reach my brain right now. Is Ollama running?"
    except Exception as exc:
        return f"Error: {exc}"


def run_demo_mode(tts_engine):
    """Text input mode — for testing without a microphone."""
    cprint("Demo mode — type your message (or 'quit' to exit)", "yellow")
    history = []
    while True:
        try:
            user_input = input("\n👤 You: ").strip()
        except (KeyboardInterrupt, EOFError):
            break
        if not user_input or user_input.lower() in ("quit", "exit", "bye"):
            speak(tts_engine, "Goodbye!")
            break
        cprint("🧠 Thinking...", "yellow")
        sentences = []
        def on_sentence(s):
            sentences.append(s)
            speak(tts_engine, s)
        response = ask_ollama_stream(user_input, history, on_sentence=on_sentence)
        history.append({"human": user_input, "assistant": response})


def run_voice_mode(tts_engine, mic_index: int | None):
    """Main voice loop — listen → transcribe → respond → repeat."""
    cprint(f"🎤 Voice mode — listening on mic {mic_index or 'default'}", "green")
    cprint("Press Ctrl+C to stop.\n", "white")
    history = []

    speak(tts_engine, "Hello! I am HUMN. How can I help you?")

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
                speak(tts_engine, "Goodbye! It was nice talking with you.")
                break

            cprint("🧠 Thinking...", "yellow")
            t0 = time.time()
            def on_sentence(s):
                cprint(f"🤖 {s}", "cyan")
                tts_engine.say(s)
                tts_engine.runAndWait()
            response = ask_ollama_stream(text, history, on_sentence=on_sentence)
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
    args = parser.parse_args()

    install_deps()

    cprint("═══════════════════════════════════════════════", "cyan")
    cprint(" HUMN Robot — Voice Loop", "cyan", attrs=["bold"])
    cprint("═══════════════════════════════════════════════", "cyan")
    cprint(f" Whisper model : {args.model}", "white")
    cprint(f" Ollama model  : {OLLAMA_MODEL}", "white")
    cprint(f" Mode          : {'demo (text)' if args.demo else 'voice'}", "white")
    cprint("═══════════════════════════════════════════════\n", "cyan")

    if args.list_mics:
        list_mics()
        return

    tts_engine = init_tts()

    if args.demo:
        run_demo_mode(tts_engine)
    else:
        run_voice_mode(tts_engine, args.mic)


if __name__ == "__main__":
    main()
