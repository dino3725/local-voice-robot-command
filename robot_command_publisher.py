#!/usr/bin/env python3
"""Thin, safety-filtered ROS2 publisher for robot command dictionaries."""

from __future__ import annotations

import json
from typing import Any

import rclpy
from rclpy.context import Context
from rclpy.node import Node
from std_msgs.msg import String


TOPIC_NAME = "/robot_command"
VALID_OBJECTS = frozenset({"coke", "tissue", "snack"})


def command_payload(command: Any) -> str | None:
    """Return canonical JSON only for an allowed fetch command."""
    if not isinstance(command, dict) or set(command) != {"action", "object"}:
        return None
    if command.get("action") != "fetch" or command.get("object") not in VALID_OBJECTS:
        return None
    canonical = {"action": "fetch", "object": command["object"]}
    return json.dumps(canonical, ensure_ascii=False, separators=(",", ":"))


class RobotCommandPublisher:
    """Own a local ROS context and publish validated JSON String messages."""

    def __init__(self, node_name: str = "robot_command_publisher") -> None:
        self.context = Context()
        self.context.init(args=None)
        self.node = Node(node_name, context=self.context)
        self.publisher = self.node.create_publisher(String, TOPIC_NAME, 10)
        self._closed = False

    def publish_command(self, command: Any) -> bool:
        payload = command_payload(command)
        if payload is None:
            return False
        message = String()
        message.data = payload
        self.publisher.publish(message)
        return True

    def close(self) -> None:
        if self._closed:
            return
        self.node.destroy_node()
        self.context.shutdown()
        self._closed = True

    def __enter__(self) -> "RobotCommandPublisher":
        return self

    def __exit__(self, _exc_type: object, _exc: object, _traceback: object) -> None:
        self.close()


__all__ = [
    "RobotCommandPublisher",
    "TOPIC_NAME",
    "VALID_OBJECTS",
    "command_payload",
]
