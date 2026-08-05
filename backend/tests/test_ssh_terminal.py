"""Терминал в панели: управляющие сообщения не должны печататься в shell."""
import asyncio
import json

import pytest

from app.api.ssh_terminal import parse_control_message, ws_to_ssh_loop


class FakeChan:
    """Канал paramiko с настоящей сигнатурой resize_pty."""

    def __init__(self, resize_raises=False):
        self.sent = []
        self.resized = None
        self._resize_raises = resize_raises

    def resize_pty(self, width=80, height=24, width_pixels=0, height_pixels=0):
        if self._resize_raises:
            raise OSError("канал ещё не готов")
        self.resized = (width, height)

    def send(self, data):
        self.sent.append(data)

    def close(self):
        pass


class FakeWS:
    def __init__(self, frames):
        self._frames = list(frames) + [{"type": "websocket.disconnect"}]

    async def receive(self):
        return self._frames.pop(0)


def _run(frames, chan):
    asyncio.run(ws_to_ssh_loop(FakeWS(frames), chan))


def test_resize_is_applied_with_paramiko_parameter_names():
    """paramiko принимает width/height, а не cols/rows. С cols/rows это
    TypeError на каждом ресайзе — ресайз не применялся никогда."""
    chan = FakeChan()
    _run([{"text": json.dumps({"type": "resize", "cols": 123, "rows": 31})}], chan)
    assert chan.resized == (123, 31)


def test_resize_message_is_never_typed_into_the_shell():
    """Симптом с живого сервера: в терминале печаталось
    {"type":"resize","cols":123,"rows":31} вместо применения ресайза.
    Причина — исключение из resize_pty глоталось общим except, и управляющее
    сообщение уходило дальше, в ветку «обычный ввод пользователя»."""
    chan = FakeChan()
    _run([{"text": json.dumps({"type": "resize", "cols": 123, "rows": 31})}], chan)
    assert chan.sent == []


def test_failed_resize_still_does_not_leak_into_the_shell():
    """Даже если применить ресайз не удалось — в shell он попасть не должен."""
    chan = FakeChan(resize_raises=True)
    _run([{"text": json.dumps({"type": "resize", "cols": 80, "rows": 24})}], chan)
    assert chan.sent == []


def test_ordinary_input_still_reaches_the_shell():
    chan = FakeChan()
    _run([{"text": "ls -la\n"}], chan)
    assert chan.sent == [b"ls -la\n"]


def test_binary_frames_are_forwarded_as_user_input():
    """Фронтенд шлёт ввод пользователя бинарным кадром — это и есть
    однозначное отличие ввода от управляющего сообщения."""
    chan = FakeChan()
    _run([{"bytes": b"whoami\n"}], chan)
    assert chan.sent == [b"whoami\n"]


@pytest.mark.parametrize("payload", [
    "ls -la",
    "",
    "{not json",
    '{"type": "something-else"}',
    '["resize"]',
])
def test_non_control_text_is_not_swallowed(payload):
    """Всё, что не является нашим управляющим сообщением, обязано дойти до
    shell — иначе панель молча съедала бы часть ввода."""
    assert parse_control_message(payload) is None
