"""The socket-free installed harness waits and wakes real executor callbacks."""

import asyncio
import threading

import pytest

from tests.unit.scripts.script_support import load_script

probe = load_script("accel003_wheel_probe")
_NoIoLoop, _NoIoSelector, request = probe._NoIoLoop, probe._NoIoSelector, probe.request


def test_selector_blocks_until_woken_and_zero_timeout_does_not_block():
    selector = _NoIoSelector()
    entered = threading.Event()
    returned = threading.Event()

    def wait():
        entered.set()
        selector.select()
        returned.set()

    worker = threading.Thread(target=wait, daemon=True)
    worker.start()
    try:
        assert entered.wait(1)
        assert not returned.wait(0.05)
        selector.wake()
        assert returned.wait(1)
        selector.select(0)
    finally:
        selector.wake()
        worker.join(1)
        selector.close()
    assert not worker.is_alive()


def test_threadsafe_callbacks_wake_without_descriptor_polling():
    selector = _NoIoSelector()
    calls = []
    original = selector.select

    def counted(timeout=None):
        calls.append(timeout)
        return original(timeout)

    selector.select = counted

    async def execute():
        await asyncio.to_thread(threading.Event().wait, 0.03)
        return 42

    with asyncio.Runner(loop_factory=lambda: _NoIoLoop(selector=selector)) as runner:
        assert runner.run(execute()) == 42
    assert len(calls) < 30


def test_asgi_roundtrip_keeps_body_and_headers_with_real_thread_work():
    async def app(scope, receive, send):
        assert scope["path"] == "/owned"
        message = await receive()
        body = await asyncio.to_thread(lambda: message["body"])
        await send(
            {"type": "http.response.start", "status": 201, "headers": [(b"x-owned", b"yes")]}
        )
        await send({"type": "http.response.body", "body": body})

    code, headers, body = request(app, "/owned", method="POST", body={"owned": True})
    assert (code, headers, body) == (201, {"x-owned": "yes"}, b'{"owned":true}')


def test_preset_wake_and_timers_are_delivered():
    selector = _NoIoSelector()
    selector.wake()
    selector.select()

    async def execute():
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        loop.call_later(0.01, future.set_result, "timer")
        return await future

    with asyncio.Runner(loop_factory=lambda: _NoIoLoop(selector=selector)) as runner:
        assert runner.run(execute()) == "timer"


def test_repeated_threadsafe_callbacks_are_never_lost():
    async def execute():
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        received = []

        def produce():
            for number in range(200):
                loop.call_soon_threadsafe(received.append, number)
            loop.call_soon_threadsafe(future.set_result, True)

        producer = threading.Thread(target=produce, daemon=True)
        producer.start()
        try:
            assert await future
        finally:
            producer.join(1)
        assert not producer.is_alive()
        return received

    with asyncio.Runner(loop_factory=lambda: _NoIoLoop(selector=_NoIoSelector())) as runner:
        assert runner.run(execute()) == list(range(200))


def test_closed_loop_wakeup_is_safe_and_registered_descriptors_are_refused(monkeypatch):
    loop = _NoIoLoop(selector=_NoIoSelector())
    loop.close()
    loop._write_to_self()
    selector = _NoIoSelector()
    monkeypatch.setattr(selector, "get_map", lambda: {1: object()})
    try:
        with pytest.raises(AssertionError, match="registered an IO descriptor"):
            selector.select(0)
    finally:
        selector.close()
