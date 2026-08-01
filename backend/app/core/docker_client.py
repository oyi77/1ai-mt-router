"""Centralized Docker client construction.

All docker-py client construction goes through :func:`get_docker_client` so
the socket URL and timeout are configured in one place instead of being
scattered across the codebase as ad-hoc ``docker.from_env()`` calls.
"""

from typing import Optional, TYPE_CHECKING

from app.config import settings

if TYPE_CHECKING:
    import docker


def get_docker_client(
    timeout: int = 30, base_url: Optional[str] = None
) -> "docker.DockerClient":
    """Build a DockerClient for the configured socket (or an override).

    ``docker`` is imported lazily inside the body so modules that import this
    helper do not pay the import cost unless a client is actually needed.

    ``base_url`` overrides ``settings.DOCKER_SOCKET``; this lets remote
    ``ssh://`` transports (e.g. a ``ServerCreate.docker_socket`` for a remote
    host) pass through cleanly — docker-py supports ``ssh://`` base URLs via
    paramiko (installed).
    """
    import docker

    return docker.DockerClient(
        base_url=base_url or settings.DOCKER_SOCKET, timeout=timeout
    )
