#!/usr/bin/env python3
"""Install global mail search on a separate server's existing IMAP MCP stack."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
from urllib.parse import urlsplit


APP_ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIR = APP_ROOT / "docker" / "mail-mcp"


def make_override(source: Path, jmap_url: str) -> dict:
    url = urlsplit(jmap_url)
    if url.scheme != "https" or not url.hostname or url.username or url.password or url.query or url.fragment:
        raise ValueError("Use the Stalwart HTTPS base URL without credentials, query or fragment.")
    return {
        "services": {
            "mail-proxy": {
                "environment": {
                    "UPSTREAM_URL": "http://mail-mcp:9557",
                    "JMAP_URL": jmap_url.rstrip("/"),
                    "JMAP_ACCOUNT_NAME": "${MAIL_MCP_ACCOUNT_NAME:-archiv}",
                    "JMAP_USERNAME": "${MAIL_MCP_JMAP_USERNAME:-${MAIL_MCP_EMAIL_ADDRESS:?Mail username missing}}",
                    "JMAP_PASSWORD": "${MAIL_MCP_PASSWORD:?Existing mail password missing}",
                },
                "volumes": [
                    {"type": "bind", "source": str(source / name), "target": "/mail-proxy/" + name, "read_only": True}
                    for name in ("server.js", "jmap.js")
                ],
            }
        }
    }


def patch_gateway(text: str) -> str:
    """Change the existing authenticated mail route, retaining the surrounding config."""
    pattern = r"(?m)^([ \t]*)reverse_proxy mail-(?:mcp:9557|proxy:9558)(?=[ \t{]|$)"
    matches = list(re.finditer(pattern, text))
    if len(matches) != 1:
        raise ValueError("Expected exactly one existing mail MCP gateway route.")
    match = matches[0]
    start = text.rfind("handle @mail {", 0, match.start())
    if start < 0:
        raise ValueError("Existing mail gateway route not recognised; configure it manually.")
    auth = text[start:match.start()]
    if "import require_bearer /mail/mcp" not in auth or "import check_token /mail/mcp" not in auth:
        raise ValueError("Existing mail route must retain its OAuth bearer/token checks.")
    return text[:match.start()] + match.group(1) + "reverse_proxy mail-proxy:9558" + text[match.end():]


def run(command: list[str], *, env: dict | None = None, capture: bool = False) -> str:
    # Do not print Compose's expanded configuration: it contains existing credentials.
    result = subprocess.run(command, env=env, check=True, text=True, stdout=subprocess.PIPE if capture else None)
    return result.stdout.strip() if capture else ""


def install(path: Path, content: str) -> None:
    """Back up and replace a configuration without following temporary-file names."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    if path.exists():
        backup = path.with_name(path.name + ".bak." + stamp)
        with open(backup, "x", opener=lambda name, flags: os.open(name, flags, 0o600)) as file:
            file.write(path.read_text())
    with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as file:
        file.write(content)
        temporary = Path(file.name)
    # This is a local Compose/gateway file, without mail credentials.
    temporary.chmod(path.stat().st_mode & 0o777 if path.exists() else 0o644)
    temporary.replace(path)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--docker-root", type=Path, required=True)
    parser.add_argument("--jmap-url", required=True, help="Stalwart HTTPS URL reachable from this server")
    parser.add_argument("--mail-compose", default="ai-clients/compose.yaml")
    parser.add_argument("--mail-env", default="ai-clients/.env")
    parser.add_argument("--gateway-config", type=Path, help="Existing Caddyfile; default: DOCKER_ROOT/mcp-funnel/Caddyfile if present")
    parser.add_argument("--gateway-container", help="Running Caddy container, if its Compose file is not at mcp-funnel/compose.yaml")
    parser.add_argument("--check-only", action="store_true", help="Validate prerequisites and Compose without changing services/configuration")
    args = parser.parse_args()
    root = args.docker_root.resolve()
    compose_file = root / args.mail_compose
    env_file = root / args.mail_env
    if not compose_file.is_file() or not env_file.is_file():
        parser.error("The existing mail Compose file and its local .env must exist on this server.")
    for name in ("server.js", "jmap.js"):
        if not (SOURCE_DIR / name).is_file():
            parser.error(f"Missing portable proxy source: {name}")
    if not args.check_only and run(["git", "-C", str(APP_ROOT), "status", "--porcelain"], capture=True):
        parser.error("Commit/push and git pull first; the Hausverwaltung checkout must be clean.")

    override = json.dumps(make_override(SOURCE_DIR, args.jmap_url), indent=2) + "\n"
    compose = ["docker", "compose", "--env-file", str(env_file), "-f", str(compose_file), "--profile", "mail"]
    services = run(compose + ["config", "--services"], capture=True).splitlines()
    if not {"mail-mcp", "mail-proxy"}.issubset(services):
        parser.error("The existing stack must contain mail-mcp and mail-proxy; this update does not create a new stack.")
    gateway = args.gateway_config.resolve() if args.gateway_config else root / "mcp-funnel" / "Caddyfile"
    gateway_text = patch_gateway(gateway.read_text()) if gateway.is_file() else None
    if args.gateway_config and gateway_text is None:
        parser.error("The specified gateway configuration does not exist.")
    gateway_container = args.gateway_container
    gateway_compose = root / "mcp-funnel" / "compose.yaml"
    if gateway_text is not None and not gateway_container:
        if not gateway_compose.is_file():
            parser.error("Use --gateway-container for the existing Caddy service.")
        gateway_container = run(["docker", "compose", "-f", str(gateway_compose), "ps", "-q", "caddy"], capture=True)
        if not gateway_container:
            parser.error("The existing Caddy gateway must be running.")

    with tempfile.TemporaryDirectory(prefix="hv-mail-mcp-") as temporary:
        preview = Path(temporary) / "compose.mail-jmap.json"
        preview.write_text(override)
        run(compose + ["-f", str(preview), "config", "--quiet"])
        # Validate the candidate gateway before replacing its live configuration.
        if gateway_text is not None:
            candidate = Path(temporary) / "Caddyfile"
            candidate.write_text(gateway_text)
            remote = "/tmp/hv-mail-jmap-" + Path(temporary).name + ".Caddyfile"
            run(["docker", "cp", str(candidate), f"{gateway_container}:{remote}"])
            try:
                run(["docker", "exec", gateway_container, "caddy", "validate", "--config", remote, "--adapter", "caddyfile"])
            finally:
                run(["docker", "exec", gateway_container, "rm", "-f", remote])
    if args.check_only:
        print("Compose and available gateway prerequisites valid; no services or configuration changed.")
        if gateway_text is None:
            print("No local Caddyfile found: keep existing authentication and route external mail MCP to mail-proxy:9558/mcp.")
        return

    generated = compose_file.parent / "compose.mail-jmap.generated.json"
    install(generated, override)
    active = compose + ["-f", str(generated)]
    run(active + ["up", "-d", "--no-deps", "--force-recreate", "mail-proxy"])
    if gateway_text is not None:
        # Write in place: Docker's single-file bind mount must keep the same inode.
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        backup = gateway.with_name(gateway.name + ".bak." + stamp)
        with open(backup, "x", opener=lambda name, flags: os.open(name, flags, 0o600)) as file:
            file.write(gateway.read_text())
        gateway.write_text(gateway_text)
        run(["docker", "restart", gateway_container])
    else:
        print("External gateway still needs configuration: retain its authentication and route mail MCP to mail-proxy:9558/mcp.")
    print("Mail proxy updated on THIS server. No ERPNext image rebuild or site migration was needed.")
    print(f"Use both {compose_file} and {generated} with future mail Compose commands.")
    print("Reload the external client's MCP catalog and verify search_all_emails/get_archive_emails_content.")


if __name__ == "__main__":
    main()
