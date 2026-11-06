"""Integração opcional de transcrição Groq para Mark-LVI.

Não altera Gemini Live: devolve texto ao mesmo chat. A gravação é manual (PTT),
sem VAD ou cortes por silêncio. Não grava credenciais nem as imprime.
"""
from __future__ import annotations

import io
import os
import threading
import time
import wave
from functools import lru_cache
from pathlib import Path
from typing import Optional

API_URL = "https://api.groq.com/openai/v1/audio/transcriptions"
KEYRING_SERVICE = "GroqTeste-Jarvis"
KEYRING_USERNAME = "GROQ_API_KEY"
DEFAULT_MODEL = "whisper-large-v3"
MAX_SECONDS = 50


class GroqRecorder:
    """Armazenamento barato de PCM16 mono, seguro para callback do PortAudio."""
    def __init__(self):
        self._lock = threading.Lock()
        self._parts: list[bytes] = []
        self._rate = 16000
        self._active = False
        self._size = 0

    def set_rate(self, rate: int) -> None:
        if not 8000 <= rate <= 192000:
            raise ValueError(f"Taxa de microfone inválida: {rate}")
        with self._lock:
            self._rate = int(rate)

    @property
    def recording(self) -> bool:
        with self._lock:
            return self._active

    def start(self) -> None:
        with self._lock:
            self._parts = []
            self._size = 0
            self._active = True

    def feed(self, pcm16: bytes) -> None:
        """Sem operações de rede/arquivo e sem concatenação de blocos no callback."""
        if not pcm16:
            return
        with self._lock:
            if not self._active:
                return
            if self._size + len(pcm16) > self._rate * MAX_SECONDS * 2:
                self._active = False  # limite máximo explícito, não descarta em silêncio
                return
            self._parts.append(bytes(pcm16))
            self._size += len(pcm16)

    def finish(self) -> tuple[bytes, int]:
        with self._lock:
            pcm = b"".join(self._parts)
            sr = self._rate
            self._parts = []
            self._size = 0
            self._active = False
            return pcm, sr


@lru_cache(maxsize=1)
def _cached_windows_key() -> str:
    try:
        import keyring
        return (keyring.get_password(KEYRING_SERVICE, KEYRING_USERNAME) or "").strip()
    except ImportError as exc:
        raise RuntimeError("Instale o pacote keyring: python -m pip install keyring") from exc
    except Exception as exc:
        raise RuntimeError(f"Falha ao acessar a credencial Groq: {exc}") from exc


def read_groq_key() -> str:
    # Environment override remains dynamic; Windows vault is read once/process.
    return os.environ.get("GROQ_API_KEY", "").strip() or _cached_windows_key()


_worker_local = threading.local()


def _http_session():
    """Keep-alive TCP/TLS on the transcription worker thread; no global session sharing."""
    import requests
    session = getattr(_worker_local, "session", None)
    if session is None:
        session = requests.Session()
        _worker_local.session = session
    return session


def pcm_to_wav(pcm16: bytes, rate: int) -> bytes:
    if not 8000 <= rate <= 192000:
        raise ValueError("Taxa de áudio fora do intervalo aceito")
    if not pcm16 or len(pcm16) % 2:
        raise ValueError("Áudio PCM16 inválido")
    with io.BytesIO() as buf:
        with wave.open(buf, "wb") as writer:
            writer.setnchannels(1)
            writer.setsampwidth(2)
            writer.setframerate(rate)
            writer.writeframes(pcm16)
        return buf.getvalue()


def transcribe_recording(
    pcm16: bytes, sample_rate: int, project_dir: str | Path,
    *, model: str = DEFAULT_MODEL, prompt: str = "",
) -> tuple[str, float, Optional[Path]]:
    """Executar apenas em worker (asyncio.to_thread). (texto, segundos, WAV)."""
    duration = len(pcm16) / (2 * sample_rate)
    if duration < 0.35:
        return "", 0.0, None
    if duration > MAX_SECONDS + 1:
        raise ValueError("Gravação acima do limite de 50 segundos")
    if not pcm16.strip(b"\x00"):
        return "", 0.0, None

    wav_bytes = pcm_to_wav(pcm16, sample_rate)
    # Mantém o último WAV para auditar cortes. Nunca contém chaves/tokens.
    output_dir = Path(project_dir) / "diagnostico_groq"
    output_dir.mkdir(parents=True, exist_ok=True)
    debug_path = output_dir / "ultima_captura.wav"
    debug_path.write_bytes(wav_bytes)

    api_key = read_groq_key()
    if not api_key:
        raise RuntimeError("Chave Groq não encontrada. Salve-a no GroqTeste ou configure GROQ_API_KEY.")
    if model not in ("whisper-large-v3", "whisper-large-v3-turbo"):
        raise ValueError("Modelo de transcrição não permitido")

    fields = {
        "model": model,
        "language": "pt",
        "response_format": "json",
        "temperature": "0",
    }
    prompt = prompt.strip()
    if prompt:
        fields["prompt"] = prompt[:500]

    started = time.perf_counter()
    response = _http_session().post(
        API_URL,
        headers={"Authorization": f"Bearer {api_key}"},
        files={"file": ("gravacao.wav", wav_bytes, "audio/wav")},
        data=fields,
        timeout=(8, 30),
    )
    elapsed = time.perf_counter() - started
    if not response.ok:
        try:
            problem = response.json()
            message = (problem.get("error") or {}).get("message") or "Falha da API de transcrição"
        except (ValueError, AttributeError):
            message = response.text[:200]
        raise RuntimeError(f"Groq HTTP {response.status_code}: {str(message)[:250]}")
    try:
        transcript = str(response.json()["text"]).strip()
    except (ValueError, TypeError, KeyError) as exc:
        raise RuntimeError("Resposta da Groq sem transcrição válida") from exc
    return transcript, elapsed, debug_path
