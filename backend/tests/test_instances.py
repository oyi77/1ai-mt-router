"""B6 tests for the instances API (app.api.instances).

Uses a fake docker client so no docker daemon is required. Each test that
exercises an instance operation seeds a real ``Instance`` row in the shared
test database because ``get_owned_instance`` enforces ownership against the
DB before any docker call is made.
"""
import uuid
from types import SimpleNamespace

import docker
import pytest

from app.auth.jwt import create_access_token
from app.models.database import Instance, User

from app.api import instances as instances_module


# --- per-request fake client IP, so the shared rate-limit bucket never trips ---
_ip_counter = [0]


def _xff():
    _ip_counter[0] += 1
    return f"203.0.113.{_ip_counter[0] % 240 + 1}"


def _headers(user_id, username="tester"):
    token = create_access_token(
        {"sub": str(user_id), "username": username, "role": "user"}
    )
    return {"Authorization": f"Bearer {token}", "X-Forwarded-For": _xff()}


def _make_user(db, username=None):
    username = username or f"u{uuid.uuid4().hex[:8]}"
    user = User(
        email=f"{username}@example.com",
        username=username,
        hashed_password="x",
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _make_instance(db, user, container=None):
    cid = container.id if container is not None else uuid.uuid4().hex
    row = Instance(
        id=cid[:12],
        name="mt5-test",
        user_id=user.id,
        docker_container_id=cid,
        status="running",
        rpyc_port=18812,
        vnc_port=6081,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


class FakeContainer:
    def __init__(
        self,
        name="mt5-test",
        status="running",
        ports=None,
        labels=None,
        logs=b"line1\nline2\n",
        stats=None,
    ):
        self.id = uuid.uuid4().hex
        self.name = name
        self.status = status
        self.image = SimpleNamespace(tags=["mt5-router:latest"])
        self.attrs = {"Created": "2026-01-01T00:00:00Z"}
        self.ports = (
            ports
            if ports is not None
            else {
                "18812/tcp": [{"HostPort": "18812"}],
                "6081/tcp": [{"HostPort": "6081"}],
            }
        )
        self.labels = (
            labels if labels is not None else {"mt5-router.instance": "true"}
        )
        self._logs = logs
        self._stats = stats or {
            "cpu_stats": {
                "cpu_usage": {"total_usage": 2000},
                "system_cpu_usage": 100000,
            },
            "precpu_stats": {
                "cpu_usage": {"total_usage": 1000},
                "system_cpu_usage": 50000,
            },
            "memory_stats": {"usage": 209715200, "limit": 1073741824},
            "networks": {"eth0": {"rx_bytes": 1024, "tx_bytes": 2048}},
        }
        self.started = 0
        self.stopped = 0
        self.restarted = 0
        self.removed = False
        self.reload_count = 0

    def reload(self):
        self.reload_count += 1

    def start(self):
        self.started += 1

    def stop(self, timeout=30):
        self.stopped += 1

    def restart(self, timeout=30):
        self.restarted += 1

    def remove(self, force=True):
        self.removed = True

    def logs(self, tail=100):
        return self._logs

    def stats(self, stream=False):
        return self._stats


class FakeContainersAPI:
    def __init__(self, containers=None, run_container=None, get_error=None):
        self.containers = list(containers or [])
        self.run_container = run_container or FakeContainer()
        self.get_error = get_error
        self.run_kwargs = []
        self.list_calls = []

    def list(self, all=True, filters=None):
        self.list_calls.append({"all": all, "filters": filters})
        return list(self.containers)

    def get(self, container_id):
        if self.get_error is not None:
            raise self.get_error
        for c in self.containers:
            if c.id == container_id or c.id.startswith(container_id):
                return c
        raise docker.errors.NotFound(f"No such container: {container_id}")

    def run(self, image, **kwargs):
        self.run_kwargs.append({"image": image, **kwargs})
        return self.run_container


class FakeDockerClient:
    def __init__(self, containers=None, run_container=None, get_error=None):
        self.containers = FakeContainersAPI(
            containers=containers,
            run_container=run_container,
            get_error=get_error,
        )


@pytest.fixture(autouse=True)
def _fresh_client(monkeypatch):
    """Install a fresh fake docker client for every test."""
    fake = FakeDockerClient()
    monkeypatch.setattr(instances_module, "get_docker_client", lambda: fake)
    yield fake


def test_create_instance_defaults(client, db, _fresh_client):
    user = _make_user(db)
    resp = client.post("/api/v1/instances", json={}, headers=_headers(user.id))
    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "mt5-test"
    assert body["status"] == "running"

    kwargs = _fresh_client.containers.run_kwargs[0]
    assert kwargs["detach"] is True
    assert kwargs["ports"] == {"18812/tcp": None, "6081/tcp": None}
    assert kwargs["labels"] == {
        "mt5-router.instance": "true",
        "mt5-router.created": "auto",
    }
    assert kwargs["shm_size"] == "2gb"
    assert kwargs["cap_add"] == ["SYS_ADMIN"]
    assert kwargs["restart_policy"] == {"Name": "unless-stopped"}
    assert "nano_cpus" not in kwargs
    assert "mem_limit" not in kwargs
    assert "pids_limit" not in kwargs

    row = (
        db.query(Instance)
        .filter(Instance.user_id == user.id)
        .first()
    )
    assert row is not None
    assert row.id == body["id"]
    assert row.docker_container_id == _fresh_client.containers.run_container.id


def test_create_instance_with_limits(client, db, _fresh_client):
    user = _make_user(db)
    resp = client.post(
        "/api/v1/instances",
        json={"cpu_limit": 2.5, "memory_limit_mb": 1024, "pids_limit": 200},
        headers=_headers(user.id),
    )
    assert resp.status_code == 200
    kwargs = _fresh_client.containers.run_kwargs[0]
    assert kwargs["nano_cpus"] == 2_500_000_000
    assert kwargs["mem_limit"] == 1024 * 1024 * 1024
    assert kwargs["pids_limit"] == 200


def test_create_instance_invalid_name_422(client, db, _fresh_client):
    user = _make_user(db)
    resp = client.post(
        "/api/v1/instances",
        json={"name": "bad name!"},
        headers=_headers(user.id),
    )
    assert resp.status_code == 422


def test_create_instance_invalid_limits_422(client, db, _fresh_client):
    user = _make_user(db)
    resp = client.post(
        "/api/v1/instances",
        json={"cpu_limit": 0, "memory_limit_mb": 100, "pids_limit": 10},
        headers=_headers(user.id),
    )
    assert resp.status_code == 422


def test_list_instances_empty(client, db):
    user = _make_user(db)
    resp = client.get("/api/v1/instances", headers=_headers(user.id))
    assert resp.status_code == 200
    assert resp.json() == []


def test_list_instances_matches_owned(client, db, _fresh_client):
    user = _make_user(db)
    container = FakeContainer(name="mt5-owned")
    _fresh_client.containers.containers.append(container)
    _make_instance(db, user, container)

    resp = client.get("/api/v1/instances", headers=_headers(user.id))
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["id"] == container.id[:12]
    assert body[0]["name"] == "mt5-owned"


def test_list_instances_ignores_unowned(client, db, _fresh_client):
    owner = _make_user(db)
    other = _make_user(db)
    container = FakeContainer(name="mt5-owned")
    _fresh_client.containers.containers.append(container)
    _make_instance(db, owner, container)

    resp = client.get("/api/v1/instances", headers=_headers(other.id))
    assert resp.status_code == 200
    assert resp.json() == []


def test_get_instance(client, db, _fresh_client):
    user = _make_user(db)
    container = FakeContainer()
    _fresh_client.containers.containers.append(container)
    _make_instance(db, user, container)

    resp = client.get(
        f"/api/v1/instances/{container.id[:12]}", headers=_headers(user.id)
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == container.id[:12]
    assert body["status"] == "running"
    assert body["rpyc_port"] == "18812"
    assert body["vnc_port"] == "6081"
    assert body["image"] == "mt5-router:latest"
    assert container.reload_count == 1


def test_get_instance_not_owner_404(client, db, _fresh_client):
    owner = _make_user(db)
    other = _make_user(db)
    container = FakeContainer()
    _fresh_client.containers.containers.append(container)
    _make_instance(db, owner, container)

    resp = client.get(
        f"/api/v1/instances/{container.id[:12]}", headers=_headers(other.id)
    )
    assert resp.status_code == 404


def test_get_instance_docker_not_found_404(client, db, _fresh_client):
    user = _make_user(db)
    container = FakeContainer()
    _make_instance(db, user, container)
    _fresh_client.containers.get_error = docker.errors.NotFound("no such container")

    resp = client.get(
        f"/api/v1/instances/{container.id[:12]}", headers=_headers(user.id)
    )
    assert resp.status_code == 404


def test_get_instance_docker_error_503(client, db, _fresh_client):
    user = _make_user(db)
    container = FakeContainer()
    _make_instance(db, user, container)
    _fresh_client.containers.get_error = RuntimeError("docker daemon down")

    resp = client.get(
        f"/api/v1/instances/{container.id[:12]}", headers=_headers(user.id)
    )
    assert resp.status_code == 503


@pytest.mark.parametrize(
    "action,status_key",
    [("start", "started"), ("stop", "stopped"), ("restart", "restarted")],
)
def test_instance_lifecycle_actions(client, db, _fresh_client, action, status_key):
    user = _make_user(db)
    container = FakeContainer()
    _fresh_client.containers.containers.append(container)
    _make_instance(db, user, container)

    resp = client.post(
        f"/api/v1/instances/{container.id[:12]}/{action}",
        headers=_headers(user.id),
    )
    assert resp.status_code == 200
    assert resp.json() == {"status": status_key, "instance_id": container.id[:12]}


def test_delete_instance(client, db, _fresh_client):
    user = _make_user(db)
    container = FakeContainer()
    _fresh_client.containers.containers.append(container)
    _make_instance(db, user, container)

    resp = client.delete(
        f"/api/v1/instances/{container.id[:12]}", headers=_headers(user.id)
    )
    assert resp.status_code == 200
    assert resp.json() == {"status": "deleted", "instance_id": container.id[:12]}
    assert container.removed is True


def test_get_instance_logs(client, db, _fresh_client):
    user = _make_user(db)
    container = FakeContainer(logs=b"boot ok\nerror trace\n")
    _fresh_client.containers.containers.append(container)
    _make_instance(db, user, container)

    resp = client.get(
        f"/api/v1/instances/{container.id[:12]}/logs",
        params={"lines": 5},
        headers=_headers(user.id),
    )
    assert resp.status_code == 200
    assert resp.json() == {"logs": ["boot ok", "error trace", ""]}


def test_get_instance_stats(client, db, _fresh_client):
    user = _make_user(db)
    container = FakeContainer()
    _fresh_client.containers.containers.append(container)
    _make_instance(db, user, container)

    resp = client.get(
        f"/api/v1/instances/{container.id[:12]}/stats", headers=_headers(user.id)
    )
    assert resp.status_code == 200
    body = resp.json()
    # cpu delta 1000 / system delta 50000 = 2.0%
    assert body["cpu_percent"] == 2.0
    assert body["memory_usage_mb"] == 200.0
    assert body["memory_limit_mb"] == 1024.0
    assert body["memory_percent"] == 19.53
    assert body["network_rx"] == 1024
    assert body["network_tx"] == 2048


def test_get_instance_stats_zero_delta(client, db, _fresh_client):
    user = _make_user(db)
    stats = {
        "cpu_stats": {"cpu_usage": {"total_usage": 1000}, "system_cpu_usage": 50000},
        "precpu_stats": {"cpu_usage": {"total_usage": 1000}, "system_cpu_usage": 50000},
        "memory_stats": {"usage": 0, "limit": 0},
        "networks": {},
    }
    container = FakeContainer(stats=stats)
    _fresh_client.containers.containers.append(container)
    _make_instance(db, user, container)

    resp = client.get(
        f"/api/v1/instances/{container.id[:12]}/stats", headers=_headers(user.id)
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["cpu_percent"] == 0.0
    assert body["memory_percent"] == 0
    assert body["network_rx"] == 0
