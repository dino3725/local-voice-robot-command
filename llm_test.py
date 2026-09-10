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
로봇이 가져올 수 있는 물체는 coke, tissue, snack뿐이다.

분류 규칙:
다음 순서로 판정하라:
1. "말고", "필요 없다", "아니다"처럼 명시적으로 부정된 후보는 긍정 의도로 세지 않는다.
2. 휴지를 명시적으로 요청하거나 닦기·청소 목적이 분명하거나 액체를 흘리고 쏟은 상황이면 tissue다. "닦아야겠다" 같은 필요 상태 서술도 직접 가져오라는 동사 없이 tissue 요청으로 해석한다. 청소 목적은 음료·음식 단어보다 우선한다. 단, 과자 같은 고체를 단순히 흘리거나 떨어뜨렸을 뿐 닦기·휴지 요청이 없으면 반드시 unknown이다.
3. 그 다음 food와 drink의 긍정 의도를 각각 확인한다. 두 의도가 모두 있으면 문장 순서나 더 구체적인 단어와 관계없이 어느 한쪽을 임의 선택하지 말고 반드시 unknown이다. 배고프면서 물·음료를 마시고 싶다는 문장도 food와 drink의 동시 의도다.
4. drink만 있으면 coke다. 콜라, 음료, 마실 것, 갈증, 목마름, 목이 마르거나 타는 상태, 마시고 싶은 의도가 이에 해당한다.
5. food만 있으면 snack이다. 먹을 것, 간식, 과자, 배고픔, 출출함, 허기, 배에서 꼬르륵거림, 간단히 먹을 음식이나 먹고 싶은 의도가 이에 해당한다. 지원되는 음식은 snack 하나뿐이다.
6. 명확한 지원 물체나 food/drink 의도가 있으면 "없어?", "부탁할 수 있을까?" 같은 질문·공손한 형식도 요청으로 해석한다. 직접 가져오라는 동사는 필수가 아니다.
7. 지원되지 않는 요청, 인사, 정보 질문, 이동·정지·기기 제어 요청 및 대상이나 목적이 불명확한 요청은 unknown이다. 모호한 표현만으로 청소 목적을 추측하지 않는다.
8. STT의 경미한 발음·띄어쓰기 오류가 있어도 핵심 의미가 분명하면 해당 의도로 분류한다.

사용자: 목마른데 마실 거 가져다줘
결과: {"action":"fetch","object":"coke"}
사용자: 뭐 흘렸는데 닦을 거 가져다줘
결과: {"action":"fetch","object":"tissue"}
사용자: 책상 좀 닦아야겠다
결과: {"action":"fetch","object":"tissue"}
사용자: 배고픈데 먹을 거 가져다줘
결과: {"action":"fetch","object":"snack"}
사용자: 오늘 날씨 어때
결과: {"action":"unknown","object":"none"}
사용자: 배고프고 목도 마른데
결과: {"action":"unknown","object":"none"}
사용자: 과자 흘렸어
결과: {"action":"unknown","object":"none"}
사용자: 배에서 꼬르륵 소리가 나
결과: {"action":"fetch","object":"snack"}
사용자: 출출한데 뭐 먹을 거 없어?
결과: {"action":"fetch","object":"snack"}
사용자: 배고픈데 물 마시고 싶어
결과: {"action":"unknown","object":"none"}

설명, markdown, 인사말, reasoning 또는 추가 문장 없이 JSON 객체만 출력하라."""

OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "action": {"type": "string", "enum": ["fetch", "unknown"]},
        "object": {
            "type": "string",
            "enum": ["coke", "tissue", "snack", "none"],
        },
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
                "action": {"const": "fetch"},
                "object": {"const": "snack"},
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
    ("fetch", "snack"),
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
