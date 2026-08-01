from unittest.mock import patch

from app.config import settings
from app.core.docker_client import get_docker_client


def test_get_docker_client_passes_base_url_and_timeout(monkeypatch):
    fake_client = object()
    with patch("docker.DockerClient", return_value=fake_client) as mock_cls:
        monkeypatch.setattr(settings, "DOCKER_SOCKET", "unix:///tmp/test.sock")
        client = get_docker_client(timeout=45)
    assert client is fake_client
    mock_cls.assert_called_once_with(base_url="unix:///tmp/test.sock", timeout=45)


def test_get_docker_client_defaults(monkeypatch):
    fake_client = object()
    with patch("docker.DockerClient", return_value=fake_client) as mock_cls:
        monkeypatch.setattr(
            settings, "DOCKER_SOCKET", "unix:///var/run/docker.sock"
        )
        client = get_docker_client()
    assert client is fake_client
    mock_cls.assert_called_once_with(
        base_url="unix:///var/run/docker.sock", timeout=30
    )


def test_get_docker_client_ssh_base_url_override():
    fake_client = object()
    with patch("docker.DockerClient", return_value=fake_client) as mock_cls:
        client = get_docker_client(base_url="ssh://user@host:22")
    assert client is fake_client
    mock_cls.assert_called_once_with(base_url="ssh://user@host:22", timeout=30)
