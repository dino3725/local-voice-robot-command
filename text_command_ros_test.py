#!/usr/bin/env python3
"""Verify text -> frozen Local LLM -> local ROS2 command publishing."""

from __future__ import annotations

import json
import time

from rclpy.executors import SingleThreadedExecutor
from rclpy.node import Node
from std_msgs.msg import String

from llm_test import classify_command
from robot_command_publisher import RobotCommandPublisher, TOPIC_NAME


CASES = [
    ("목마른데 마실 거 가져다줘", {"action": "fetch", "object": "coke"}, True),
    ("입술이 터서 바를 게 필요해", {"action": "fetch", "object": "vaseline"}, True),
    ("뭐 흘렸는데 닦을 거 가져다줘", {"action": "fetch", "object": "tissue"}, True),
    ("음악 들을 때 쓸 무선 이어폰 가져다줘", {"action": "fetch", "object": "airpod"}, True),
    ("로봇 당장 멈춰", {"action": "stop", "object": "none"}, True),
    ("오늘 날씨 어때", {"action": "unknown", "object": "none"}, False),
]


def spin_until(executor: SingleThreadedExecutor, predicate: object, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        executor.spin_once(timeout_sec=0.05)
        if predicate():  # type: ignore[operator]
            return True
    return False


def main() -> int:
    received: list[str] = []
    with RobotCommandPublisher("text_command_ros_publisher") as publisher:
        subscriber = Node("text_command_ros_subscriber", context=publisher.context)
        subscriber.create_subscription(
            String,
            TOPIC_NAME,
            lambda message: received.append(message.data),
            10,
        )
        executor = SingleThreadedExecutor(context=publisher.context)
        executor.add_node(publisher.node)
        executor.add_node(subscriber)
        try:
            if not spin_until(
                executor,
                lambda: publisher.publisher.get_subscription_count() >= 1,
                5.0,
            ):
                raise RuntimeError("local subscriber discovery timed out")

            expected_payloads: list[str] = []
            for text, expected, should_publish in CASES:
                command = classify_command(text)
                published = publisher.publish_command(command)
                print(f"\n[INPUT]\n{text}")
                print("\n[LLM]")
                print(json.dumps(command, ensure_ascii=False, separators=(",", ":")))
                print("\n[ROS]")
                print("published /robot_command" if published else "skipped")
                if command != expected or published != should_publish:
                    raise RuntimeError(
                        f"case mismatch: expected={expected!r}/{should_publish}, "
                        f"actual={command!r}/{published}"
                    )
                if published:
                    expected_payloads.append(
                        json.dumps(command, ensure_ascii=False, separators=(",", ":"))
                    )

            if not spin_until(executor, lambda: len(received) >= 5, 5.0):
                raise RuntimeError(f"expected 5 ROS messages, received {len(received)}")
            if received != expected_payloads:
                raise RuntimeError(f"subscriber payload mismatch: {received!r}")
            print(f"\n[SUBSCRIBER]\nreceived={len(received)} expected=5")
            print("RESULT: PASS")
        finally:
            executor.remove_node(subscriber)
            executor.remove_node(publisher.node)
            subscriber.destroy_node()
            executor.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
