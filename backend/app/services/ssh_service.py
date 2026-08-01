import paramiko
import logging
import re
import shlex
from typing import Optional, Dict, Any, List
from cryptography.fernet import Fernet
from io import BytesIO

logger = logging.getLogger(__name__)

_CONTAINER_NAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,127}$")


def _validate_container_name(name: str) -> Optional[str]:
    """Return an error message if ``name`` is not a valid Docker container name."""
    if not name or not _CONTAINER_NAME_RE.match(name):
        return (
            "Invalid container name: use letters, digits, '.', '_' or '-' "
            "(start with a letter or digit, max 128 chars)"
        )
    return None


class SSHService:
    def __init__(self, encryption_key: str):
        self.cipher = Fernet(
            encryption_key.encode()
            if isinstance(encryption_key, str)
            else encryption_key
        )

    def encrypt_secret(self, secret: str) -> str:
        return self.cipher.encrypt(secret.encode()).decode()

    def decrypt_secret(self, encrypted: str) -> str:
        return self.cipher.decrypt(encrypted.encode()).decode()

    @staticmethod
    def _load_private_key(private_key: str) -> paramiko.PKey:
        """Parse an SSH private key, trying the supported key formats."""
        data = BytesIO(private_key.encode())
        for key_type in (paramiko.RSAKey, paramiko.Ed25519Key, paramiko.ECDSAKey):
            try:
                return key_type.from_private_key(data)
            except paramiko.SSHException:
                data.seek(0)
        raise paramiko.SSHException(
            "Unable to parse private key (unsupported format)"
        )

    def create_client(
        self,
        host: str,
        port: int,
        username: str,
        private_key: Optional[str] = None,
        password: Optional[str] = None,
        timeout: int = 10,
    ) -> Optional[paramiko.SSHClient]:
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        try:
            if private_key:
                key = self._load_private_key(private_key)
                client.connect(
                    host,
                    port=port,
                    username=username,
                    pkey=key,
                    timeout=timeout,
                    auth_timeout=timeout,
                    banner_timeout=timeout,
                    allow_agent=False,
                    look_for_keys=False,
                )
            elif password:
                client.connect(
                    host,
                    port=port,
                    username=username,
                    password=password,
                    timeout=timeout,
                    auth_timeout=timeout,
                    banner_timeout=timeout,
                    allow_agent=False,
                    look_for_keys=False,
                )
            else:
                raise ValueError("Either private_key or password required")

            logger.info("SSH connected to %s:%s", host, port)
            return client
        except Exception as e:
            logger.error("SSH connection failed to %s: %s", host, e)
            return None

    def execute_command(
        self, client: paramiko.SSHClient, command: str, timeout: int = 30
    ) -> Dict[str, Any]:
        try:
            stdin, stdout, stderr = client.exec_command(command, timeout=timeout)
            exit_code = stdout.channel.recv_exit_status()
            output = stdout.read().decode("utf-8", errors="replace")
            error = stderr.read().decode("utf-8", errors="replace")

            return {
                "success": exit_code == 0,
                "exit_code": exit_code,
                "output": output,
                "error": error,
            }
        except Exception as e:
            logger.error(f"Command execution failed: {e}")
            return {"success": False, "exit_code": -1, "output": "", "error": str(e)}

    def check_health(self, client: paramiko.SSHClient) -> Dict[str, Any]:
        result = self.execute_command(
            client,
            "uptime && free -m && df -h / && docker ps --format '{{.Names}} {{.Status}}' | wc -l",
        )

        if not result["success"]:
            return {"status": "unhealthy", "error": result["error"]}

        output = result["output"]
        lines = output.strip().split("\n")

        return {
            "status": "healthy",
            "uptime": lines[0] if lines else "unknown",
            "raw_output": output,
        }

    def get_server_metrics(self, client: paramiko.SSHClient) -> Dict[str, Any]:
        cpu_result = self.execute_command(
            client, "top -bn1 | grep 'Cpu(s)' | awk '{print $2}'"
        )
        cpu_percent = (
            float(cpu_result["output"].strip()) if cpu_result["success"] else 0
        )

        mem_result = self.execute_command(client, "free -m | grep Mem:")
        memory = {"total": 0, "used": 0, "percent": 0}
        if mem_result["success"]:
            parts = mem_result["output"].split()
            if len(parts) >= 3:
                memory["total"] = int(parts[1])
                memory["used"] = int(parts[2])
                memory["percent"] = round(memory["used"] / memory["total"] * 100, 2)

        disk_result = self.execute_command(client, "df -h / | tail -1")
        disk = {"total": "", "used": "", "percent": 0}
        if disk_result["success"]:
            parts = disk_result["output"].split()
            if len(parts) >= 5:
                disk["total"] = parts[1]
                disk["used"] = parts[2]
                disk["percent"] = int(parts[4].replace("%", ""))

        docker_result = self.execute_command(
            client, "docker ps -a --format '{{.Names}} {{.Status}}'"
        )
        containers = []
        if docker_result["success"]:
            for line in docker_result["output"].strip().split("\n"):
                if line:
                    parts = line.split(" ", 1)
                    containers.append(
                        {
                            "name": parts[0] if parts else "unknown",
                            "status": parts[1] if len(parts) > 1 else "unknown",
                        }
                    )

        return {
            "cpu_percent": cpu_percent,
            "memory": memory,
            "disk": disk,
            "containers": containers,
            "containers_total": len(containers),
            "containers_running": len(
                [c for c in containers if "Up" in c.get("status", "")]
            ),
        }

    def install_docker(self, client: paramiko.SSHClient) -> bool:
        check = self.execute_command(client, "which docker")
        if check["success"] and check["output"].strip():
            return True

        commands = [
            "curl -fsSL https://get.docker.com -o get-docker.sh",
            "sh get-docker.sh",
            "usermod -aG docker $USER",
            "systemctl enable docker",
            "systemctl start docker",
        ]

        for cmd in commands:
            result = self.execute_command(client, cmd, timeout=120)
            if not result["success"]:
                logger.error(f"Docker install failed at: {cmd}")
                return False

        return True

    def run_mt5_instance(
        self,
        client: paramiko.SSHClient,
        instance_name: str,
        image: str = "lprett/mt5linux:mt5-installed",
    ) -> Dict[str, Any]:
        name_error = _validate_container_name(instance_name)
        if name_error:
            return {"success": False, "error": name_error}

        if not self.install_docker(client):
            return {"success": False, "error": "Docker installation failed"}

        self.execute_command(client, f"docker pull {shlex.quote(image)}", timeout=300)

        cmd = (
            f"docker run -d "
            f"--name {shlex.quote(instance_name)} "
            f"--shm-size=2g "
            f"--cap-add=SYS_ADMIN "
            f"--restart unless-stopped "
            f"-p 0:18812 "
            f"-p 0:6081 "
            f"-l mt5-router.instance=true "
            f"-l mt5-router.created=auto "
            f"{shlex.quote(image)}"
        )

        result = self.execute_command(client, cmd)
        if not result["success"]:
            return {"success": False, "error": result["error"]}

        container_id = result["output"].strip()

        port_cmd = (
            f"docker port {shlex.quote(instance_name)} 18812 | cut -d: -f2 && "
            f"docker port {shlex.quote(instance_name)} 6081 | cut -d: -f2"
        )
        ports_result = self.execute_command(client, port_cmd)

        ports = (
            ports_result["output"].strip().split("\n")
            if ports_result["success"]
            else []
        )

        return {
            "success": True,
            "container_id": container_id,
            "name": instance_name,
            "rpyc_port": int(ports[0]) if len(ports) > 0 else None,
            "vnc_port": int(ports[1]) if len(ports) > 1 else None,
        }

    def control_instance(
        self, client: paramiko.SSHClient, container_name: str, action: str
    ) -> Dict[str, Any]:
        valid_actions = ["start", "stop", "restart", "rm", "pause", "unpause"]
        if action not in valid_actions:
            return {"success": False, "error": f"Invalid action: {action}"}

        cmd = (
            f"docker {action} {shlex.quote(container_name)}"
            if action != "rm"
            else f"docker rm -f {shlex.quote(container_name)}"
        )
        result = self.execute_command(client, cmd, timeout=60)

        return {
            "success": result["success"],
            "action": action,
            "output": result["output"],
            "error": result["error"],
        }

    def get_instance_logs(
        self, client: paramiko.SSHClient, container_name: str, lines: int = 100
    ) -> str:
        result = self.execute_command(
            client, f"docker logs --tail {lines} {shlex.quote(container_name)}"
        )
        return result["output"] if result["success"] else result["error"]

    def get_instance_stats(
        self, client: paramiko.SSHClient, container_name: str
    ) -> Dict[str, Any]:
        stats_cmd = (
            f"docker stats {shlex.quote(container_name)} --no-stream "
            "--format '{.CPUPerc}|{.MemUsage}|{.MemPerc}|{.NetIO}|{.BlockIO}'"
        )
        result = self.execute_command(client, stats_cmd)

        if not result["success"]:
            return {"error": result["error"]}

        parts = result["output"].strip().split("|")

        return {
            "cpu_percent": float(parts[0].replace("%", "")) if len(parts) > 0 else 0,
            "memory_usage": parts[1] if len(parts) > 1 else "",
            "memory_percent": float(parts[2].replace("%", "")) if len(parts) > 2 else 0,
            "network_io": parts[3] if len(parts) > 3 else "",
            "block_io": parts[4] if len(parts) > 4 else "",
        }

    def list_instances(self, client: paramiko.SSHClient) -> List[Dict[str, Any]]:
        ps_cmd = (
            "docker ps -a --filter label=mt5-router.instance "
            "--format '{{.ID}}|{{.Names}}|{{.Status}}|{{.Ports}}|{{.CreatedAt}}'"
        )
        result = self.execute_command(client, ps_cmd)

        instances = []
        if result["success"] and result["output"].strip():
            for line in result["output"].strip().split("\n"):
                parts = line.split("|")
                if len(parts) >= 5:
                    ports_str = parts[3]
                    rpyc_port = None
                    vnc_port = None

                    port_matches = re.findall(r"(?:0\.0\.0\.0|\[::\]):(\d+)->(\d+)/tcp", ports_str)
                    for host_port, container_port in port_matches:
                        if container_port == "18812":
                            rpyc_port = int(host_port)
                        elif container_port == "6081":
                            vnc_port = int(host_port)

                    instances.append(
                        {
                            "id": parts[0],
                            "name": parts[1],
                            "status": parts[2],
                            "rpyc_port": rpyc_port,
                            "vnc_port": vnc_port,
                            "created": parts[4],
                        }
                    )

        return instances


ssh_service: Optional[SSHService] = None


def init_ssh_service(encryption_key: str):
    global ssh_service
    ssh_service = SSHService(encryption_key)
    return ssh_service
