import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


SPEC = importlib.util.spec_from_file_location("update_mail_mcp", Path(__file__).with_name("update_mail_mcp.py"))
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


GATEWAY = """handle @mail {
    import require_bearer /mail/mcp
    handle {
        import check_token /mail/mcp
        reverse_proxy mail-mcp:9557 {
            header_up -Authorization
        }
    }
}
handle @zotero { reverse_proxy unix//run/zotero.sock }
"""


class MailMCPUpdateTests(unittest.TestCase):
    def test_override_uses_existing_secrets_without_copying_or_resolving_them(self):
        data = MODULE.make_override(Path("/opt/hausverwaltung/docker/mail-mcp"), "https://mail.example.com:8443/")
        service = data["services"]["mail-proxy"]
        self.assertEqual(service["environment"]["JMAP_URL"], "https://mail.example.com:8443")
        self.assertEqual(service["environment"]["JMAP_PASSWORD"], "${MAIL_MCP_PASSWORD:?Existing mail password missing}")
        self.assertEqual(len(service["volumes"]), 2)
        self.assertTrue(all(volume["read_only"] for volume in service["volumes"]))
        self.assertEqual(service["volumes"][1]["target"], "/mail-proxy/jmap.js")
        self.assertNotIn("ports", service)

    def test_invalid_or_credential_bearing_urls_are_refused(self):
        for url in ("http://mail.example.com", "https://user:secret@mail.example.com", "https://mail.example.com?secret=value", "https://mail.example.com#value", "https:///missing-host"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                MODULE.make_override(Path("/opt/app"), url)

    def test_gateway_changes_only_the_mail_upstream_and_is_idempotent(self):
        expected = GATEWAY.replace("reverse_proxy mail-mcp:9557", "reverse_proxy mail-proxy:9558")
        self.assertEqual(MODULE.patch_gateway(GATEWAY), expected)
        self.assertEqual(MODULE.patch_gateway(expected), expected)

    def test_gateway_refuses_ambiguous_or_missing_authentication(self):
        for text in (GATEWAY + GATEWAY, GATEWAY.replace("import check_token /mail/mcp", ""), GATEWAY.replace("import require_bearer /mail/mcp", ""), GATEWAY.replace("handle @mail {", "handle @other {")):
            with self.assertRaises(ValueError):
                MODULE.patch_gateway(text)

    def test_config_install_backs_up_the_previous_override_privately(self):
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "override.json"
            destination.write_text("old")
            MODULE.install(destination, "new")
            self.assertEqual(destination.read_text(), "new")
            backups = list(Path(directory).glob("override.json.bak.*"))
            self.assertEqual(len(backups), 1)
            self.assertEqual(backups[0].read_text(), "old")
            self.assertEqual(backups[0].stat().st_mode & 0o777, 0o600)

    def test_check_only_validates_the_overlay_without_writing_or_starting_services(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "ai-clients").mkdir()
            (root / "ai-clients" / "compose.yaml").write_text("services: {}")
            (root / "ai-clients" / ".env").write_text("MAIL_MCP_PASSWORD=test-placeholder\n")
            calls = []

            def run(command, **kwargs):
                calls.append(command)
                if command[-2:] == ["config", "--services"]:
                    return "mail-mcp\nmail-proxy"
                if command[-2:] == ["config", "--quiet"]:
                    override_path = Path(command[command.index("--profile") + 3])
                    data = json.loads(override_path.read_text())
                    self.assertIn("${MAIL_MCP_PASSWORD", data["services"]["mail-proxy"]["environment"]["JMAP_PASSWORD"])
                    return ""
                self.fail(f"Unexpected mutation/check: {command}")

            argv = ["update_mail_mcp.py", "--docker-root", str(root), "--jmap-url", "https://mail.example.com", "--check-only"]
            with patch("sys.argv", argv), patch.object(MODULE, "run", side_effect=run):
                MODULE.main()
            self.assertFalse((root / "ai-clients" / "compose.mail-jmap.generated.json").exists())
            self.assertEqual(len(calls), 2)
            self.assertEqual((root / "ai-clients" / ".env").read_text(), "MAIL_MCP_PASSWORD=test-placeholder\n")


if __name__ == "__main__":
    unittest.main()
