from __future__ import annotations

import json
import mailbox
import tempfile
import unittest
from email.message import EmailMessage
from pathlib import Path

from thunderbird_mbox_to_dovecot import MAILDIR_DATA_DIRECTORY, main, report_path_for


def add_message(path: Path, subject: str, status: str, body: str, keys: str = "") -> None:
    box = mailbox.mbox(path, create=True)
    message = EmailMessage()
    message["From"] = "sender@example.test"
    message["To"] = "receiver@example.test"
    message["Date"] = "Tue, 18 Aug 2026 12:00:00 +0200"
    message["Subject"] = subject
    message["X-Mozilla-Status"] = status
    message["X-Mozilla-Status2"] = "00000000"
    if keys:
        message["X-Mozilla-Keys"] = keys
    message.set_content(body)
    box.add(message)
    box.flush()
    box.close()


class ConverterTest(unittest.TestCase):
    def test_hierarchy_flags_deleted_and_literal_periods(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            destination = root / "destination"
            source.mkdir()

            parent = source / "PRIVAT"
            parent.touch()
            (source / "PRIVAT.msf").touch()
            children = source / "PRIVAT.sbd"
            children.mkdir()
            child = children / "Year.2024"
            add_message(child, "kept", "1007", "A body line\nFrom must survive\n", "$label1 custom")
            add_message(child, "deleted", "0008", "deleted body")
            (children / "Year.2024.msf").touch()

            self.assertEqual(main([str(source), str(destination)]), 0)
            data = (
                destination
                / "Thunderbird-Archiv"
                / "PRIVAT"
                / "Year.2024"
                / MAILDIR_DATA_DIRECTORY
            )
            messages = list((data / "cur").iterdir())
            self.assertEqual(len(messages), 1)
            self.assertIn(":2,FPRS", messages[0].name)
            self.assertIn(b"\nFrom must survive\n", messages[0].read_bytes())
            keywords = (data / "dovecot-keywords").read_text(encoding="utf-8")
            self.assertIn("$label1", keywords)
            self.assertIn("custom", keywords)

            report = json.loads(report_path_for(destination).read_text())
            self.assertEqual(report["totals"]["folders"], 2)
            self.assertEqual(report["totals"]["messages"], 1)
            self.assertEqual(report["totals"]["expunged_skipped"], 1)

    def test_orphan_sbd_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            destination = root / "destination"
            source.mkdir()
            (source / "orphan.sbd").mkdir()
            self.assertEqual(main([str(source), str(destination)]), 1)


if __name__ == "__main__":
    unittest.main()
