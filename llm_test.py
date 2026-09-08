#!/usr/bin/env python3
"""Classify Korean service-robot commands with a local Ollama model."""

from __future__ import annotations

import argparse
import json
import time
import urllib.request
from typing import Any


OLLAMA_CHAT_URL = "http://127.0.0.1:11434/api/chat"
MODEL = "qwen3:4b-instruct"

SYSTEM_PROMPT = """당신은 서비스 로봇의 자연어 명령을 제한된 행동으로 변환하는 명령 해석기다.
로봇이 가져올 수 있는 물체는 coke와 tissue뿐이다.

분류 규칙:
1. 콜라, 음료, 마실 것 요청, 목마름, "목이 마르다"·"목이 말랐다", 마시고 싶다는 표현은 직접 가져오라는 동사가 없어도 coke를 가져오는 요청이다.
2. 휴지나 닦을 것을 요청하거나, 물건·물·음료 등을 흘리거나 쏟아 닦아야 하는 상황은 tissue를 가져오는 요청이다.
3. 흘림·쏟음·닦기 문맥이 있으면 음료라는 단어가 있어도 tissue 규칙을 우선한다.
4. 위 두 행동 이외의 요청, 인사, 질문, 이동·정지·기기 제어 요청은 unknown이다.
5. 지원되는 물체는 coke와 tissue뿐이다. 다른 물체를 임의로 대체하지 않는다.

사용자: 목마른데 마실 거 가져다줘
결과: {"action":"fetch","object":"coke"}
사용자: 목이 너무 말라
결과: {"action":"fetch","object":"coke"}
사용자: 목마름대 마실거 가져다줘
결과: {"action":"fetch","object":"coke"}
사용자: 뭐 흘렸는데 닦을 거 가져다줘
결과: {"action":"fetch","object":"tissue"}
사용자: 바닥에 뭐 쏟았는데 어떡하지
결과: {"action":"fetch","object":"tissue"}
사용자: 오늘 날씨 어때
결과: {"action":"unknown","object":"none"}

설명, markdown, 인사말, reasoning 또는 추가 문장 없이 JSON 객체만 출력하라."""

OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "action": {"type": "string", "enum": ["fetch", "unknown"]},
        "object": {"type": "string", "enum": ["coke", "tissue", "none"]},
    },
    "required": ["action", "object"],
    "additionalProperties": False,
    "oneOf": [
        {
            "properties": {
                "action": {"const": "fetch"},
                "object": {"const": "coke"},
            }
        },
        {
            "properties": {
                "action": {"const": "fetch"},
                "object": {"const": "tissue"},
            }
        },
        {
            "properties": {
                "action": {"const": "unknown"},
                "object": {"const": "none"},
            }
        },
    ],
}

ALLOWED_RESULTS = {
    ("fetch", "coke"),
    ("fetch", "tissue"),
    ("unknown", "none"),
}


def _validate_result(value: Any) -> dict[str, str]:
    if not isinstance(value, dict) or set(value) != {"action", "object"}:
        raise ValueError(f"Invalid result structure: {value!r}")

    action = value.get("action")
    obj = value.get("object")
    if not isinstance(action, str) or not isinstance(obj, str):
        raise ValueError(f"Result values must be strings: {value!r}")
    if (action, obj) not in ALLOWED_RESULTS:
        raise ValueError(f"Invalid action/object combination: {value!r}")
    return {"action": action, "object": obj}


def classify_command_with_metrics(text: str) -> tuple[dict[str, str], dict[str, float]]:
    if not isinstance(text, str) or not text.strip():
        raise ValueError("text must be a non-empty string")

    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": text.strip()},
        ],
        "stream": False,
        "think": False,
        "format": OUTPUT_SCHEMA,
        "keep_alive": "10m",
        "options": {
            "temperature": 0,
            "seed": 0,
            "num_ctx": 2048,
            "num_predict": 32,
        },
    }
    request = urllib.request.Request(
        OLLAMA_CHAT_URL,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )

    started = time.perf_counter()
    with urllib.request.urlopen(request, timeout=120) as response:
        api_result = json.load(response)
    wall_seconds = time.perf_counter() - started

    content = api_result["message"]["content"]
    result = _validate_result(json.loads(content))
    metrics = {
        "wall_seconds": wall_seconds,
        "total_seconds": api_result.get("total_duration", 0) / 1_000_000_000,
        "load_seconds": api_result.get("load_duration", 0) / 1_000_000_000,
        "prompt_eval_seconds": api_result.get("prompt_eval_duration", 0)
        / 1_000_000_000,
        "eval_seconds": api_result.get("eval_duration", 0) / 1_000_000_000,
    }
    return result, metrics


def classify_command(text: str) -> dict[str, str]:
    result, _ = classify_command_with_metrics(text)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("text", help="Natural-language command to classify")
    args = parser.parse_args()
    print(json.dumps(classify_command(args.text), ensure_ascii=False, separators=(",", ":")))


if __name__ == "__main__":
    main()
