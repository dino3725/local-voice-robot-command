#!/usr/bin/env python3
"""Record one voice command, transcribe it, and classify it locally."""

from __future__ import annotations

import argparse
import audioop
import json
import math
import subprocess
import sys
import time
import urllib.request
import wave
from pathlib import Path

from faster_whisper import WhisperModel

from llm_test import MODEL as LLM_MODEL
from llm_test import classify_command


WHISPER_MODEL = "small"
SAMPLE_RATE = 16_000
CHANNELS = 1
SAMPLE_WIDTH = 2
RECORD_SECONDS = 10
OLLAMA_TAGS_URL = "http://127.0.0.1:11434/api/tags"


class PipelineError(RuntimeError):
    """An expected integration-stage failure with user-facing context."""

    def __init__(self, stage: str, message: str, debug: str = "") -> None:
        super().__init__(message)
        self.stage = stage
        self.debug = debug


def load_whisper_model() -> tuple[WhisperModel, float]:
    started = time.perf_counter()
    try:
        model = WhisperModel(WHISPER_MODEL, device="cpu", compute_type="int8")
    except Exception as exc:
        raise PipelineError(
            "STT 모델 로드",
            "Whisper 모델을 로드할 수 없습니다.",
            f"{type(exc).__name__}: {exc}",
        ) from exc
    return model, time.perf_counter() - started


def ensure_ollama_ready() -> None:
    try:
        with urllib.request.urlopen(OLLAMA_TAGS_URL, timeout=5) as response:
            payload = json.load(response)
    except Exception as exc:
        raise PipelineError(
            "LLM 준비",
            "Ollama Local API에 연결할 수 없습니다.",
            f"{type(exc).__name__}: {exc}",
        ) from exc

    installed_models = {
        model.get("name") for model in payload.get("models", []) if model.get("name")
    }
    if LLM_MODEL not in installed_models:
        raise PipelineError(
            "LLM 준비",
            f"필요한 Ollama 모델이 등록되어 있지 않습니다: {LLM_MODEL}",
            f"installed_models={sorted(installed_models)}",
        )


def get_default_source() -> str:
    try:
        completed = subprocess.run(
            ["pactl", "get-default-source"],
            capture_output=True,
            text=True,
            check=True,
        )
    except FileNotFoundError as exc:
        raise PipelineError(
            "녹음 준비",
            "pactl 실행 파일을 찾을 수 없습니다.",
            f"{type(exc).__name__}: {exc}",
        ) from exc
    except subprocess.CalledProcessError as exc:
        raise PipelineError(
            "녹음 준비",
            "PulseAudio default source를 확인할 수 없습니다.",
            f"exit={exc.returncode}; stderr={exc.stderr.strip()}",
        ) from exc

    source = completed.stdout.strip()
    if not source:
        raise PipelineError("녹음 준비", "PulseAudio default source가 비어 있습니다.")
    return source


def _read_exact(stream: object, byte_count: int) -> bytes:
    chunks: list[bytes] = []
    remaining = byte_count
    while remaining:
        chunk = stream.read(remaining)  # type: ignore[attr-defined]
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def _stop_capture_process(process: subprocess.Popen[bytes]) -> str:
    if process.poll() is None:
        process.terminate()
    try:
        process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=2)
    assert process.stderr is not None
    return process.stderr.read().decode("utf-8", errors="replace").strip()


def record_audio(output_path: Path) -> float:
    output_path = output_path.resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.exists():
        raise PipelineError(
            "녹음",
            f"기존 녹음 파일을 덮어쓰지 않습니다: {output_path}",
        )

    source = get_default_source()
    command = [
        "parec",
        "--device",
        source,
        "--raw",
        "--format=s16le",
        f"--rate={SAMPLE_RATE}",
        f"--channels={CHANNELS}",
    ]
    capture_bytes = SAMPLE_RATE * CHANNELS * SAMPLE_WIDTH * RECORD_SECONDS

    print("[REC]", flush=True)
    print("지금부터 10초간 녹음합니다.", flush=True)
    print("지금 말씀해주세요.", flush=True)

    started = time.perf_counter()
    try:
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=0,
        )
    except FileNotFoundError as exc:
        raise PipelineError(
            "녹음 준비",
            "parec 실행 파일을 찾을 수 없습니다.",
            f"{type(exc).__name__}: {exc}",
        ) from exc

    assert process.stdout is not None
    assert process.stderr is not None
    audio_data = _read_exact(process.stdout, capture_bytes)
    stderr = _stop_capture_process(process)

    if len(audio_data) != capture_bytes:
        raise PipelineError(
            "녹음",
            "PulseAudio stream에서 10초 분량을 받지 못했습니다.",
            f"captured={len(audio_data)}/{capture_bytes}; stderr={stderr}",
        )

    try:
        with wave.open(str(output_path), "wb") as wav_file:
            wav_file.setnchannels(CHANNELS)
            wav_file.setsampwidth(SAMPLE_WIDTH)
            wav_file.setframerate(SAMPLE_RATE)
            wav_file.writeframes(audio_data)
    except (OSError, wave.Error) as exc:
        raise PipelineError(
            "녹음 저장",
            "WAV 파일을 저장할 수 없습니다.",
            f"{type(exc).__name__}: {exc}",
        ) from exc

    record_seconds = time.perf_counter() - started

    if not output_path.is_file() or output_path.stat().st_size <= 44:
        raise PipelineError(
            "녹음",
            "WAV 파일이 생성되지 않았거나 유효한 오디오 데이터가 없습니다.",
            stderr,
        )
    print("[REC]", flush=True)
    print("녹음 완료", flush=True)
    return record_seconds


def inspect_audio(audio_path: Path) -> dict[str, float | int | bool]:
    try:
        with wave.open(str(audio_path), "rb") as wav_file:
            channels = wav_file.getnchannels()
            sample_rate = wav_file.getframerate()
            sample_width = wav_file.getsampwidth()
            frame_count = wav_file.getnframes()
            audio_data = wav_file.readframes(frame_count)
    except (OSError, wave.Error) as exc:
        raise PipelineError(
            "오디오 검사",
            "녹음된 WAV 파일을 검사할 수 없습니다.",
            f"{type(exc).__name__}: {exc}",
        ) from exc

    rms = audioop.rms(audio_data, sample_width)
    peak = audioop.max(audio_data, sample_width)
    full_scale = float(1 << (sample_width * 8 - 1))
    rms_dbfs = 20 * math.log10(rms / full_scale) if rms else float("-inf")
    peak_dbfs = 20 * math.log10(peak / full_scale) if peak else float("-inf")
    result: dict[str, float | int | bool] = {
        "duration_seconds": frame_count / sample_rate,
        "sample_rate": sample_rate,
        "channels": channels,
        "rms": rms,
        "rms_dbfs": rms_dbfs,
        "peak": peak,
        "peak_dbfs": peak_dbfs,
        "silent": peak == 0,
    }
    print("\n[AUDIO]")
    print(f"DURATION: {result['duration_seconds']:.3f} sec")
    print(f"SAMPLE_RATE: {sample_rate} Hz")
    print(f"CHANNELS: {channels}")
    print(f"RMS: {rms} ({rms_dbfs:.2f} dBFS)")
    print(f"PEAK: {peak} ({peak_dbfs:.2f} dBFS)")
    print(f"SILENT: {result['silent']}")
    return result


def transcribe_audio(model: WhisperModel, audio_path: Path) -> tuple[str, float]:
    if not audio_path.is_file():
        raise PipelineError("STT", f"WAV 파일을 찾을 수 없습니다: {audio_path}")

    started = time.perf_counter()
    try:
        segment_iter, _ = model.transcribe(str(audio_path), language="ko")
        segments = list(segment_iter)
        text = "".join(segment.text for segment in segments).strip()
    except Exception as exc:
        raise PipelineError(
            "STT",
            "Whisper 전사에 실패했습니다.",
            f"{type(exc).__name__}: {exc}",
        ) from exc
    stt_seconds = time.perf_counter() - started

    if not text:
        raise PipelineError("STT", "Whisper 전사 결과가 비어 있습니다.")
    return text, stt_seconds


def classify_text(text: str) -> tuple[dict[str, str], float]:
    started = time.perf_counter()
    try:
        command = classify_command(text)
    except Exception as exc:
        raise PipelineError(
            "LLM",
            "Ollama 연결 또는 LLM JSON 응답 검증에 실패했습니다.",
            f"{type(exc).__name__}: {exc}",
        ) from exc
    return command, time.perf_counter() - started


class VoiceCommandPipeline:
    """Reusable single-process STT and command-classification pipeline."""

    def __init__(self) -> None:
        self.whisper_model, self.model_load_seconds = load_whisper_model()
        ensure_ollama_ready()

    def run_once(
        self, output_path: Path, expected_object: str | None = None
    ) -> dict[str, object]:
        started = time.perf_counter()
        record_seconds = record_audio(output_path)
        audio_status = inspect_audio(output_path)
        text, stt_seconds = transcribe_audio(self.whisper_model, output_path)
        command, llm_seconds = classify_text(text)
        total_seconds = time.perf_counter() - started

        print("\n[STT]")
        print(text)
        print("\n[COMMAND]")
        print(json.dumps(command, ensure_ascii=False, separators=(",", ":")))
        print("\n[TIME]")
        print(f"WHISPER_MODEL_LOAD: {self.model_load_seconds:.3f} sec")
        print(f"RECORD: {record_seconds:.3f} sec")
        print(f"STT: {stt_seconds:.3f} sec")
        print(f"LLM: {llm_seconds:.3f} sec")
        print(f"TOTAL: {total_seconds:.3f} sec")

        success = expected_object is None or command["object"] == expected_object
        if expected_object is not None:
            print("\n[VERIFY]")
            print(f"EXPECTED_OBJECT: {expected_object}")
            print(f"RESULT: {'SUCCESS' if success else 'FAILURE'}")

        return {
            "audio_path": str(output_path.resolve()),
            "transcript": text,
            "command": command,
            "expected_object": expected_object,
            "success": success,
            "model_load_seconds": self.model_load_seconds,
            "record_seconds": record_seconds,
            "audio_status": audio_status,
            "stt_seconds": stt_seconds,
            "llm_seconds": llm_seconds,
            "total_seconds": total_seconds,
        }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("recordings/command.wav"),
        help="New WAV path; an existing file is never overwritten",
    )
    parser.add_argument(
        "--expected-object",
        choices=("coke", "tissue", "none"),
        help="Optional expected object for this test",
    )
    args = parser.parse_args()

    try:
        pipeline = VoiceCommandPipeline()
        result = pipeline.run_once(args.output, args.expected_object)
    except PipelineError as exc:
        print(f"\n[ERROR]\n{exc.stage}: {exc}", file=sys.stderr)
        if exc.debug:
            print(f"[DEBUG]\n{exc.debug}", file=sys.stderr)
        return 1
    except Exception as exc:
        print("\n[ERROR]\n예상하지 못한 통합 프로그램 오류가 발생했습니다.", file=sys.stderr)
        print(f"[DEBUG]\n{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    return 0 if result["success"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
