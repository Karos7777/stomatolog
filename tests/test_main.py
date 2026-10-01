import socket

from app import RELEASE, app_version
from main import free_port


def test_free_port_skips_port_taken_by_old_copy():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        s.listen()
        busy = s.getsockname()[1]
        assert free_port(busy) != busy


def test_version_is_shown():
    assert app_version().startswith(RELEASE)
