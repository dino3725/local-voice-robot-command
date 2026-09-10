#!/usr/bin/env python3
"""Local ROS2 publisher/subscriber verification without the LLM or microphone."""

from __future__ import annotations

import argparse
import json
import time

from rclpy.executors import SingleThreadedExecutor
from rclpy.node import Node
from std_msgs.msg import String

from robot_command_publisher import RobotCommandPublisher, TOPIC_NAME


FETCH_COMMANDS = [
    {"action": "fetch", "object": "coke"},
    {"action": "fetch", "object": "tissue"},
    {"action": "fetch", "object": "snack"},
]
BLOCKED_COMMANDS = [
    {"action": "unknown", "object": "none"},
    {"action": "fetch", "object": "water"},
    {"action": "move", "object": "coke"},
    {"action": "fetch", "object": "none"},
    "not a command",
]


def spin_until(executor: SingleThreadedExecutor, predicate: object, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        executor.spin_once(timeout_sec=0.05)
        if predicate():  # type: ignore[operator]
            return True
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hold-seconds", type=float, default=0.0)
    args = parser.parse_args()

    received: list[str] = []
    with RobotCommandPublisher("robot_command_publisher_test") as publisher:
        subscriber = Node("robot_command_subscriber_test", context=publisher.context)
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
            discovered = spin_until(
                executor,
                lambda: publisher.publisher.get_subscription_count() >= 1,
                5.0,
            )
            if not discovered:
                raise RuntimeError("local subscriber discovery timed out")

            decisions: list[bool] = []
            for command in FETCH_COMMANDS + BLOCKED_COMMANDS:
                decisions.append(publisher.publish_command(command))
            delivered = spin_until(executor, lambda: len(received) >= 3, 5.0)
            if not delivered:
                raise RuntimeError(f"expected 3 messages, received {len(received)}")

            parsed = [json.loads(payload) for payload in received]
            expected = FETCH_COMMANDS
            if parsed != expected:
                raise RuntimeError(f"payload mismatch: {parsed!r}")
            if decisions != [True, True, True, False, False, False, False, False]:
                raise RuntimeError(f"safety filter mismatch: {decisions!r}")

            for command, payload in zip(FETCH_COMMANDS, received, strict=True):
                print(f"PUBLISHED {command['object']}: {payload}")
            print(f"UNKNOWN_AND_INVALID_BLOCKED: {len(BLOCKED_COMMANDS)}/{len(BLOCKED_COMMANDS)}")
            print(f"RECEIVED_COUNT: {len(received)}")
            print("RESULT: PASS", flush=True)

            if args.hold_seconds > 0:
                deadline = time.monotonic() + args.hold_seconds
                print(f"HOLDING_TOPIC: {args.hold_seconds:.1f}s", flush=True)
                while time.monotonic() < deadline:
                    executor.spin_once(timeout_sec=0.1)
        finally:
            executor.remove_node(subscriber)
            executor.remove_node(publisher.node)
            subscriber.destroy_node()
            executor.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
