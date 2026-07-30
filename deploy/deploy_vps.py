from __future__ import annotations

import posixpath
import shlex
import sys
import time
from pathlib import Path

import paramiko


ROOT = Path(__file__).resolve().parents[1]
PROJECT_FILES = [
    "bot.py",
    "config.py",
    "documents.py",
    "email_sender.py",
    "openai_service.py",
    "questionnaire.py",
    "requirements.txt",
    "storage.py",
    "telegram_sender.py",
    "web_app.py",
    "web_storage.py",
    "README.md",
]


def main() -> None:
    vps = read_env(ROOT / ".vps.env")
    app_env_path = ROOT / ".env"
    if not app_env_path.exists():
        raise RuntimeError(".env is missing")

    host = required(vps, "VPS_HOST")
    port = int(vps.get("VPS_PORT") or "22")
    user = required(vps, "VPS_USER")
    password = vps.get("VPS_PASSWORD") or None
    key_path = vps.get("VPS_KEY_PATH") or None
    app_dir = vps.get("APP_DIR") or "/opt/wedding-bot"

    print(f"Connecting to {user}@{host}:{port}...")
    client = connect(host, port, user, password, key_path)
    try:
        run(client, "uname -a")
        run(client, f"mkdir -p {shlex.quote(app_dir)}/data/voice {shlex.quote(app_dir)}/data/web_voice {shlex.quote(app_dir)}/outputs")
        upload_project(client, app_dir, app_env_path)

        run(client, "DEBIAN_FRONTEND=noninteractive apt-get update", timeout=600)
        run(client, "DEBIAN_FRONTEND=noninteractive apt-get install -y python3 python3-venv python3-pip", timeout=600)
        run(
            client,
            (
                f"cd {shlex.quote(app_dir)} && "
                "python3 -m venv .venv && "
                ".venv/bin/python -m pip install --upgrade pip && "
                ".venv/bin/python -m pip install -r requirements.txt"
            ),
            timeout=600,
        )

        service_text = (ROOT / "deploy" / "wedding-bot.service").read_text(encoding="utf-8")
        write_remote_file(client, "/etc/systemd/system/wedding-bot.service", service_text)
        web_service_text = (ROOT / "deploy" / "wedding-web.service").read_text(encoding="utf-8")
        write_remote_file(client, "/etc/systemd/system/wedding-web.service", web_service_text)
        run(client, "systemctl daemon-reload")
        run(client, "systemctl enable wedding-bot")
        run(client, "systemctl enable wedding-web")
        run(client, "systemctl restart wedding-bot")
        run(client, "systemctl restart wedding-web")
        run(client, "ufw allow 8080/tcp || true", check=False)
        time.sleep(3)
        run(client, "systemctl --no-pager --full status wedding-bot", check=False)
        run(client, "systemctl --no-pager --full status wedding-web", check=False)
        print("Deployment finished.")
    finally:
        client.close()


def read_env(path: Path) -> dict[str, str]:
    if not path.exists():
        raise RuntimeError(f"{path.name} is missing")
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def required(values: dict[str, str], key: str) -> str:
    value = values.get(key, "").strip()
    if not value:
        raise RuntimeError(f"{key} is empty")
    return value


def connect(
    host: str,
    port: int,
    user: str,
    password: str | None,
    key_path: str | None,
) -> paramiko.SSHClient:
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    kwargs: dict[str, object] = {
        "hostname": host,
        "port": port,
        "username": user,
        "timeout": 20,
        "banner_timeout": 20,
        "auth_timeout": 20,
    }
    if password:
        kwargs["password"] = password
    if key_path:
        path = Path(key_path)
        if path.exists():
            kwargs["key_filename"] = str(path)
    client.connect(**kwargs)
    return client


def upload_project(client: paramiko.SSHClient, app_dir: str, app_env_path: Path) -> None:
    with client.open_sftp() as sftp:
        mkdir_p(sftp, app_dir)
        for name in PROJECT_FILES:
            upload_file(sftp, ROOT / name, posixpath.join(app_dir, name))
        upload_file(sftp, app_env_path, posixpath.join(app_dir, ".env"))
        access_codes_path = ROOT / "data" / "access_codes.txt"
        if access_codes_path.exists():
            mkdir_p(sftp, posixpath.join(app_dir, "data"))
            upload_file(sftp, access_codes_path, posixpath.join(app_dir, "data", "access_codes.txt"))
    print(f"Uploaded project files to {app_dir}.")


def mkdir_p(sftp: paramiko.SFTPClient, path: str) -> None:
    parts = [part for part in path.split("/") if part]
    current = ""
    for part in parts:
        current += "/" + part
        try:
            sftp.stat(current)
        except FileNotFoundError:
            sftp.mkdir(current)


def upload_file(sftp: paramiko.SFTPClient, local: Path, remote: str) -> None:
    sftp.put(str(local), remote)


def write_remote_file(client: paramiko.SSHClient, remote_path: str, text: str) -> None:
    with client.open_sftp() as sftp:
        with sftp.file(remote_path, "w") as remote_file:
            remote_file.write(text.replace("\r\n", "\n"))


def run(client: paramiko.SSHClient, command: str, timeout: int = 120, check: bool = True) -> str:
    print(f"$ {command}")
    stdin, stdout, stderr = client.exec_command(command, timeout=timeout)
    del stdin
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    exit_code = stdout.channel.recv_exit_status()
    if out.strip():
        print(out.strip())
    if err.strip():
        print(err.strip(), file=sys.stderr)
    if check and exit_code != 0:
        raise RuntimeError(f"Command failed with exit code {exit_code}: {command}")
    return out + err


if __name__ == "__main__":
    main()
