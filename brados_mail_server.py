# brados_mail_server.py — Docker-based mail server management for BradOS

from __future__ import annotations

import json
import logging
import os
import subprocess
from dataclasses import dataclass

logger = logging.getLogger("brados.mail")

# -- Data structures ---------------------------------------------------------

@dataclass
class MailAccount:
    email      : str
    created_at : str

@dataclass
class ServerStatus:
    running      : bool
    container_id : str | None
    uptime       : str | None
    version      : str | None

# -- MailServerManager -------------------------------------------------------

class MailServerManager:
    CONFIG_DIR   = os.path.join("brados_files", "etc", "mail")
    RELAY_FILE   = os.path.join(CONFIG_DIR, "relay.json")
    COMPOSE_DIR  = os.path.join(CONFIG_DIR, "docker-mailserver")
    COMPOSE_FILE = os.path.join(COMPOSE_DIR, "docker-compose.yml")

    def __init__(self) -> None:
        self._domain: str = "brados.local"

    @property
    def config_path(self) -> str:
        return self.CONFIG_DIR

    @property
    def compose_path(self) -> str:
        return self.COMPOSE_FILE

    # -- Docker compose management -------------------------------------------

    @staticmethod
    def generate_compose(domain: str) -> str:
        return f"""services:
  mailserver:
    image: ghcr.io/docker-mailserver/docker-mailserver:latest
    container_name: {domain}-mailserver
    hostname: mail
    domainname: {domain}
    ports:
      - "25:25"
      - "143:143"
      - "587:587"
      - "993:993"
    volumes:
      - ./data/mail:/var/mail
      - ./data/state:/var/mail-state
      - ./data/logs:/var/log/mail
      - ./data/config:/tmp/docker-mailserver
      - ./data/ssl:/etc/ssl
    environment:
      - ENABLE_FAIL2BAN=1
      - ENABLE_MANAGESIEVE=1
      - OVERRIDE_HOSTNAME=mail.{domain}
      - POSTMASTER_ADDRESS=postmaster@{domain}
      - SSL_TYPE=snakeoil
      - TZ=UTC
    cap_add:
      - NET_ADMIN
      - SYS_PTRACE
    restart: always
    stop_grace_period: 1m
"""

    def write_compose(self, path: str, domain: str) -> None:
        self._domain = domain
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(self.generate_compose(domain))
        logger.info("Compose written to %s (domain=%s)", path, domain)

    def _docker_compose(self, cmd: list[str], timeout: int = 120) -> subprocess.CompletedProcess | None:
        if not self._check_docker():
            return None
        try:
            return subprocess.run(
                ["docker", "compose"] + cmd,
                cwd=os.path.dirname(self.COMPOSE_FILE),
                capture_output=True, text=True, timeout=timeout,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            return None

    def start(self) -> bool:
        compose_dir = os.path.dirname(self.COMPOSE_FILE)
        if not os.path.exists(self.COMPOSE_FILE):
            os.makedirs(compose_dir, exist_ok=True)
            self.write_compose(self.COMPOSE_FILE, self._domain)
        result = self._docker_compose(["up", "-d"], 120)
        if result is None:
            return False
        if result.returncode != 0:
            logger.warning("docker compose up failed: %s", result.stderr.strip())
            return False
        logger.info("Mail server started")
        return True

    def stop(self) -> bool:
        result = self._docker_compose(["down"], 60)
        if result is None:
            return False
        if result.returncode != 0:
            logger.warning("docker compose down failed: %s", result.stderr.strip())
            return False
        logger.info("Mail server stopped")
        return True

    def status(self) -> ServerStatus:
        result = self._docker_compose(["ps", "--format", "json"], 30)
        if result is None or result.returncode != 0 or not result.stdout.strip():
            return ServerStatus(False, None, None, None)
        try:
            lines = result.stdout.strip().splitlines()
            data = json.loads(lines[0])
            cid = data.get("ID")
            status_str = data.get("Status", "")
            running = "Up" in status_str
            uptime = status_str.replace("Up ", "").strip() if running else None
            version = data.get("Image", "").split(":")[-1] if data.get("Image") else None
            return ServerStatus(running, cid, uptime or None, version)
        except (json.JSONDecodeError, IndexError):
            return ServerStatus(False, None, None, None)

    def logs(self, lines: int = 50) -> list[str]:
        result = self._docker_compose(["logs", "--tail", str(lines), "--no-color"], 30)
        if result is None:
            return ["docker not available"]
        if result.returncode != 0:
            return [f"Error: {result.stderr.strip()}"]
        return [line for line in result.stdout.splitlines() if line.strip()]

    # -- Account management --------------------------------------------------

    def _container_name(self) -> str:
        return f"{self._domain}-mailserver"

    def _exec(self, cmd: list[str]) -> subprocess.CompletedProcess | None:
        if not self._check_docker():
            return None
        try:
            return subprocess.run(
                ["docker", "exec", self._container_name()] + cmd,
                capture_output=True, text=True, timeout=30,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            return None

    def add_account(self, email: str, password: str) -> bool:
        r = self._exec(["setup", "email", "add", email, password])
        if r is None:
            return False
        if r.returncode != 0:
            logger.warning("add_account failed for %s: %s", email, r.stderr.strip())
            return False
        logger.info("Account added: %s", email)
        return True

    def remove_account(self, email: str) -> bool:
        r = self._exec(["setup", "email", "del", email])
        if r is None:
            return False
        if r.returncode != 0:
            logger.warning("remove_account failed for %s: %s", email, r.stderr.strip())
            return False
        logger.info("Account removed: %s", email)
        return True

    def list_accounts(self) -> list[str]:
        r = self._exec(["setup", "email", "list"])
        if r is None or r.returncode != 0:
            return []
        return [line.strip() for line in r.stdout.splitlines()
                if line.strip() and not line.startswith("*")]

    def update_password(self, email: str, password: str) -> bool:
        r = self._exec(["setup", "email", "update", email, password])
        if r is None:
            return False
        if r.returncode != 0:
            logger.warning("update_password failed for %s: %s", email, r.stderr.strip())
            return False
        logger.info("Password updated for %s", email)
        return True

    # -- Configuration helpers -----------------------------------------------

    def configure_spf(self, domain: str, ip: str) -> str:
        return f"v=spf1 mx a ip4:{ip} ~all"

    def configure_dkim(self, domain: str) -> str:
        r = self._exec(["setup", "config", "dkim", "domain", domain])
        if r is None:
            return "DKIM setup requires a running container"
        dkim_file = os.path.join(
            self.CONFIG_DIR, "docker-mailserver",
            "data", "config", "opendkim", "keys", domain, "mail.txt",
        )
        try:
            if os.path.exists(dkim_file):
                with open(dkim_file) as f:
                    return f.read().strip()
        except OSError as e:
            logger.warning("Could not read DKIM key: %s", e)
        return "DKIM key generated — check container logs for details"

    def configure_dmarc(self, domain: str) -> str:
        return (f"v=DMARC1; p=quarantine; "
                f"rua=mailto:postmaster@{domain}; "
                f"ruf=mailto:postmaster@{domain}; pct=100")

    def set_relay(self, host: str, port: int,
                  username: str, password: str) -> None:
        os.makedirs(os.path.dirname(self.RELAY_FILE), exist_ok=True)
        with open(self.RELAY_FILE, "w") as f:
            json.dump({"host": host, "port": port,
                       "username": username, "password": password}, f, indent=2)
        logger.info("Relay configured: %s:%d", host, port)

    # -- IMAP / SMTP integration ---------------------------------------------

    def imap_connect(self, username: str, password: str) -> bool:
        try:
            import imaplib
        except ImportError:
            logger.warning("imaplib not available")
            return False
        if not self.status().running:
            logger.warning("IMAP connect failed: server not running")
            return False
        try:
            mail = imaplib.IMAP4("127.0.0.1", 143)
            mail.login(username, password)
            mail.logout()
            return True
        except Exception as e:
            logger.warning("IMAP connection failed: %s", e)
            return False

    def fetch_mail(self, username: str, password: str,
                   folder: str = "INBOX") -> list[dict]:
        try:
            import imaplib
            import email as email_lib
            from email.header import decode_header
        except ImportError:
            logger.warning("imaplib not available")
            return []
        if not self.status().running:
            logger.warning("fetch_mail failed: server not running")
            return []
        messages: list[dict] = []
        try:
            mail = imaplib.IMAP4("127.0.0.1", 143)
            mail.login(username, password)
            mail.select(folder)
            _typ, data = mail.search(None, "ALL")
            for num in data[0].split():
                _typ, msg_data = mail.fetch(num, "(RFC822)")
                raw = msg_data[0][1] if msg_data else b""
                if not raw:
                    continue
                msg = email_lib.message_from_bytes(raw)

                def _decode(s: str | None) -> str:
                    if not s:
                        return ""
                    parts = decode_header(s)
                    return " ".join(
                        p.decode(charset or "utf-8", errors="replace")
                        if isinstance(p, bytes) else str(p)
                        for p, charset in parts
                    )

                messages.append({
                    "from":    _decode(msg.get("From")),
                    "to":      _decode(msg.get("To")),
                    "subject": _decode(msg.get("Subject")),
                    "date":    msg.get("Date", ""),
                    "body":    _get_body(msg),
                    "starred": False,
                })
            mail.logout()
        except Exception as e:
            logger.warning("fetch_mail failed: %s", e)
        return messages

    def send_mail(self, smtp_host: str, port: int,
                  username: str, password: str,
                  from_addr: str, to_addr: str,
                  subject: str, body: str) -> bool:
        try:
            import smtplib
            from email.mime.text import MIMEText
        except ImportError:
            logger.warning("smtplib not available")
            return False
        try:
            msg = MIMEText(body)
            msg["Subject"] = subject
            msg["From"]    = from_addr
            msg["To"]      = to_addr
            with smtplib.SMTP(smtp_host, port, timeout=30) as server:
                server.starttls()
                server.login(username, password)
                server.sendmail(from_addr, [to_addr], msg.as_string())
            return True
        except Exception as e:
            logger.warning("send_mail failed: %s", e)
            return False

    # -- Docker availability check -------------------------------------------

    @staticmethod
    def _check_docker() -> bool:
        try:
            r = subprocess.run(["docker", "--version"],
                               capture_output=True, text=True, timeout=10)
            return r.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            return False

    # -- CLI interface -------------------------------------------------------

    def cli(self, args: list[str]) -> int:
        if not args:
            self._print_help()
            return 0
        cmd = args[0].lower()
        if cmd == "start":
            ok = self.start()
            print("Mail server started." if ok else "Failed to start mail server.")
            return 0 if ok else 1
        if cmd == "stop":
            ok = self.stop()
            print("Mail server stopped." if ok else "Failed to stop mail server.")
            return 0 if ok else 1
        if cmd == "status":
            s = self.status()
            if s.running:
                print(f"Container: {s.container_id}\nUptime:    {s.uptime}\nVersion:   {s.version}")
            else:
                print("Mail server is not running.")
            return 0
        if cmd == "add" and len(args) >= 2:
            import getpass
            email = args[1]
            pw  = getpass.getpass(f"Password for {email}: ")
            pw2 = getpass.getpass("Confirm: ")
            if not pw or pw != pw2:
                print("Passwords do not match or are empty.")
                return 1
            ok = self.add_account(email, pw)
            print(f"Account {'added' if ok else 'failed'} for {email}.")
            return 0 if ok else 1
        if cmd == "remove" and len(args) >= 2:
            ok = self.remove_account(args[1])
            print(f"Account {'removed' if ok else 'failed to remove'} {args[1]}.")
            return 0 if ok else 1
        if cmd == "list":
            accounts = self.list_accounts()
            if not accounts:
                print("No mail accounts configured.")
            else:
                print(f"{'Email':<40}\n{'─' * 42}")
                for a in accounts:
                    print(f"{a:<40}")
            return 0
        if cmd == "logs":
            n = int(args[1]) if len(args) > 1 and args[1].isdigit() else 50
            for line in self.logs(n):
                print(line)
            return 0
        if cmd == "relay" and len(args) >= 3:
            import getpass
            try:
                port = int(args[2])
            except ValueError:
                print("Port must be a number.")
                return 1
            self.set_relay(args[1], port, getpass.getpass("Username: "), getpass.getpass("Password: "))
            print(f"Relay configured: {args[1]}:{port}")
            return 0
        if cmd == "dns":
            self._print_dns_records()
            return 0
        print(f"Unknown command: {cmd}")
        self._print_help()
        return 1

    def _print_dns_records(self) -> None:
        domain = self._domain
        ip = "YOUR_SERVER_IP"
        print(f"DNS records required for {domain}:\n")
        print(f"  A       mail.{domain}   ->  {ip}")
        print(f"  MX      {domain}         ->  mail.{domain}  (priority 10)")
        print(f"  TXT     {domain}         ->  {self.configure_spf(domain, ip)}")
        dkim = self.configure_dkim(domain)
        if "v=DKIM1" in dkim:
            print(f"  TXT     mail._domainkey.{domain}  ->  {dkim}")
        print(f"  TXT     _dmarc.{domain}   ->  {self.configure_dmarc(domain)}")

    @staticmethod
    def _print_help() -> None:
        print("""Mail Server Manager — BradOS

Usage: mail-server <command> [args]

Commands:
  start               Start the mail server
  stop                Stop the mail server
  status              Show container status
  add <email>         Add a mail account
  remove <email>      Remove a mail account
  list                List configured accounts
  logs [n]            Show last n log lines
  relay <host> <port> Configure SMTP relay
  dns                 Print required DNS records
""")


# -- Helpers ------------------------------------------------------------------

def _get_body(msg: object) -> str:
    try:
        if msg.is_multipart():
            for part in msg.walk():
                if part.get_content_type() == "text/plain":
                    payload = part.get_payload(decode=True)
                    if payload:
                        return payload.decode(errors="replace")
            return ""
        payload = msg.get_payload(decode=True)
        return payload.decode(errors="replace") if payload else ""
    except Exception:
        return ""


# -- Singleton ----------------------------------------------------------------

_mail_server: MailServerManager | None = None


def get_mail_server() -> MailServerManager:
    global _mail_server
    if _mail_server is None:
        _mail_server = MailServerManager()
    return _mail_server
