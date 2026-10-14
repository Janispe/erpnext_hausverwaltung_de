#!/usr/bin/env python3
"""Convert a copied Thunderbird mbox/.sbd tree to Dovecot Maildir (fs layout).

The source is opened read-only.  The destination is a new staging tree; it is
never the Stalwart data directory.  Thunderbird's container-only mbox framing
is removed, expunged messages are skipped, and common Thunderbird flags are
translated to Maildir flags for a later IMAP import with Vandelay.
"""

from __future__ import annotations

import argparse
import email.policy
import email.utils
import hashlib
import json
import mailbox
import os
import re
import sys
import time
from dataclasses import asdict, dataclass, field
from email.parser import BytesHeaderParser
from pathlib import Path

MOZILLA_READ = 0x00000001
MOZILLA_REPLIED = 0x00000002
MOZILLA_MARKED = 0x00000004
MOZILLA_EXPUNGED = 0x00000008
MOZILLA_PARTIAL = 0x00000400
MOZILLA_FORWARDED = 0x00001000
MOZILLA_LABELS = 0x0E000000
MOZILLA_LABEL_SHIFT = 25

MAILDIR_DATA_DIRECTORY = "mAildir-6f2c9a"
IGNORED_FILENAMES = {
    ".DS_Store",
    "filterlog.html",
    "feeds.json",
    "msgFilterRules.dat",
    "popstate.dat",
}


@dataclass
class FolderResult:
    source: str
    mailbox: str
    messages: int = 0
    expunged_skipped: int = 0
    partial_messages: int = 0
    output_bytes: int = 0
    keywords: list[str] = field(default_factory=list)
    keyword_overflow: list[str] = field(default_factory=list)


@dataclass
class ConversionReport:
    source: str
    destination: str
    prefix: str
    started_at: str
    finished_at: str = ""
    folders: list[FolderResult] = field(default_factory=list)
    ignored_files: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def totals(self) -> dict[str, int]:
        return {
            "folders": len(self.folders),
            "messages": sum(folder.messages for folder in self.folders),
            "expunged_skipped": sum(folder.expunged_skipped for folder in self.folders),
            "partial_messages": sum(folder.partial_messages for folder in self.folders),
            "keyword_overflow": sum(len(folder.keyword_overflow) for folder in self.folders),
            "output_bytes": sum(folder.output_bytes for folder in self.folders),
        }


class ReadOnlyMbox(mailbox.mbox):
    """A stdlib mbox reader that never opens the source with write access."""

    def __init__(self, path: Path):
        mailbox.Mailbox.__init__(self, path, factory=None, create=False)
        self._file = path.open("rb")
        self._toc = None
        self._next_key = 0
        self._pending = False
        self._pending_sync = False
        self._locked = False
        self._file_length = None

    def add(self, message):
        raise TypeError("read-only Thunderbird source")

    def remove(self, key):
        raise TypeError("read-only Thunderbird source")

    def __setitem__(self, key, message):
        raise TypeError("read-only Thunderbird source")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="Prepared Thunderbird tree containing mbox/.sbd pairs")
    parser.add_argument("destination", type=Path, help="New, empty Dovecot Maildir staging directory")
    parser.add_argument(
        "--prefix",
        default="Thunderbird-Archiv",
        help="Top-level IMAP mailbox created above the imported tree",
    )
    parser.add_argument(
        "--allow-non-mbox",
        action="store_true",
        help="Ignore unexpected non-mbox files instead of stopping",
    )
    return parser.parse_args(argv)


def is_ignored_file(path: Path) -> bool:
    return path.name.endswith(".msf") or path.name in IGNORED_FILENAMES


def looks_like_mbox(path: Path) -> bool:
    if path.stat().st_size == 0:
        return True
    with path.open("rb") as handle:
        return handle.readline().startswith(b"From ")


def logical_mailbox(source_root: Path, mbox_path: Path, prefix: str) -> tuple[str, ...]:
    relative = mbox_path.relative_to(source_root)
    components: list[str] = [prefix]
    for component in relative.parts[:-1]:
        if not component.endswith(".sbd"):
            raise ValueError(
                f"unexpected directory {component!r} in {relative}; Thunderbird subdirectories must end in .sbd"
            )
        components.append(component[:-4])
    components.append(relative.name)
    if any(not component for component in components):
        raise ValueError(f"empty mailbox component in {relative}")
    if MAILDIR_DATA_DIRECTORY in components:
        raise ValueError(
            f"mailbox component {MAILDIR_DATA_DIRECTORY!r} collides with the Dovecot data directory"
        )
    return tuple(components)


def discover_mboxes(source: Path, allow_non_mbox: bool, report: ConversionReport) -> list[Path]:
    mboxes: list[Path] = []
    for path in sorted(source.rglob("*"), key=lambda item: os.fsencode(str(item))):
        if not path.is_file():
            continue
        relative = str(path.relative_to(source))
        if is_ignored_file(path):
            report.ignored_files.append(relative)
            continue
        if not looks_like_mbox(path):
            message = f"unexpected non-mbox file: {relative}"
            if allow_non_mbox:
                report.warnings.append(message)
                report.ignored_files.append(relative)
                continue
            raise ValueError(f"{message}; inspect it or use --allow-non-mbox")
        mboxes.append(path)

    mbox_relatives = {path.relative_to(source) for path in mboxes}
    for directory in sorted(source.rglob("*.sbd"), key=lambda item: os.fsencode(str(item))):
        if not directory.is_dir():
            continue
        pair = directory.with_name(directory.name[:-4]).relative_to(source)
        if pair not in mbox_relatives:
            raise ValueError(f"orphan .sbd directory without matching mbox file: {directory.relative_to(source)}")
    return mboxes


def split_headers(raw_message: bytes) -> bytes:
    match = re.search(br"\r?\n\r?\n", raw_message)
    return raw_message[: match.start()] if match else raw_message


def read_metadata(raw_message: bytes) -> tuple[int, set[str], float | None]:
    headers = BytesHeaderParser(policy=email.policy.compat32).parsebytes(split_headers(raw_message))
    flags = 0
    for header_name in ("X-Mozilla-Status", "X-Mozilla-Status2"):
        for value in headers.get_all(header_name, []):
            token = str(value).strip().split()[0] if str(value).strip() else ""
            if token:
                try:
                    flags |= int(token, 16)
                except ValueError:
                    pass

    keywords: set[str] = set()
    for value in headers.get_all("X-Mozilla-Keys", []):
        keywords.update(token for token in str(value).split() if token)
    label = (flags & MOZILLA_LABELS) >> MOZILLA_LABEL_SHIFT
    if 1 <= label <= 5:
        keywords.add(f"$label{label}")

    timestamp: float | None = None
    date_value = headers.get("Date")
    if date_value:
        try:
            parsed = email.utils.parsedate_to_datetime(str(date_value))
            if parsed is not None:
                timestamp = parsed.timestamp()
        except (OverflowError, TypeError, ValueError):
            pass
    return flags, keywords, timestamp


def unescape_mbox_from_lines(raw_message: bytes) -> bytes:
    # mboxrd quotes body lines beginning with "From " by adding one ">".
    return re.sub(br"(?m)^>(?=>*From )", b"", raw_message)


def maildir_system_flags(mozilla_flags: int) -> set[str]:
    result: set[str] = set()
    if mozilla_flags & MOZILLA_READ:
        result.add("S")
    if mozilla_flags & MOZILLA_REPLIED:
        result.add("R")
    if mozilla_flags & MOZILLA_MARKED:
        result.add("F")
    if mozilla_flags & MOZILLA_FORWARDED:
        result.add("P")
    return result


def safe_timestamp(timestamp: float | None, fallback: float) -> float:
    if timestamp is None or timestamp < 0 or timestamp > time.time() + 366 * 24 * 60 * 60:
        return fallback
    return timestamp


def write_message_atomic(path: Path, raw_message: bytes, timestamp: float) -> None:
    temporary = path.parent.parent / "tmp" / f".{path.name}.tmp"
    with temporary.open("xb") as handle:
        handle.write(raw_message)
        handle.flush()
        os.fsync(handle.fileno())
    os.utime(temporary, (timestamp, timestamp))
    temporary.replace(path)


def convert_mbox(
    source_root: Path,
    destination: Path,
    mbox_path: Path,
    prefix: str,
) -> FolderResult:
    components = logical_mailbox(source_root, mbox_path, prefix)
    mailbox_name = "/".join(components)
    data_directory = destination.joinpath(*components, MAILDIR_DATA_DIRECTORY)
    for child in ("cur", "new", "tmp"):
        (data_directory / child).mkdir(parents=True, exist_ok=True)

    result = FolderResult(source=str(mbox_path.relative_to(source_root)), mailbox=mailbox_name)
    keyword_letters: dict[str, str] = {}
    available_letters = iter("abcdefghijklmnopqrstuvwxyz")
    source_mtime = mbox_path.stat().st_mtime
    mbox = ReadOnlyMbox(mbox_path)

    try:
        for index, key in enumerate(mbox.iterkeys()):
            message_file = mbox.get_file(key, from_=False)
            try:
                raw_message = message_file.read()
            finally:
                message_file.close()
            mozilla_flags, keywords, message_timestamp = read_metadata(raw_message)
            if mozilla_flags & MOZILLA_EXPUNGED:
                result.expunged_skipped += 1
                continue
            if mozilla_flags & MOZILLA_PARTIAL:
                result.partial_messages += 1

            maildir_flags = maildir_system_flags(mozilla_flags)
            for keyword in sorted(keywords):
                if keyword not in keyword_letters:
                    try:
                        keyword_letters[keyword] = next(available_letters)
                    except StopIteration:
                        if keyword not in result.keyword_overflow:
                            result.keyword_overflow.append(keyword)
                        continue
                maildir_flags.add(keyword_letters[keyword])

            raw_message = unescape_mbox_from_lines(raw_message)
            digest = hashlib.sha256(raw_message).hexdigest()
            unique = f"{int(source_mtime)}.{index}.{digest[:24]}.tbmig"
            filename = f"{unique}:2,{''.join(sorted(maildir_flags))}"
            target = data_directory / "cur" / filename
            timestamp = safe_timestamp(message_timestamp, source_mtime)
            write_message_atomic(target, raw_message, timestamp)
            result.messages += 1
            result.output_bytes += len(raw_message)
    finally:
        mbox.close()

    result.keywords = sorted(keyword_letters)
    if keyword_letters:
        mapping = sorted((letter, keyword) for keyword, letter in keyword_letters.items())
        lines = [f"{ord(letter) - ord('a')} {keyword}\n" for letter, keyword in mapping]
        (data_directory / "dovecot-keywords").write_text("".join(lines), encoding="utf-8")
    return result


def ensure_new_destination(destination: Path) -> None:
    if destination.exists():
        if not destination.is_dir():
            raise ValueError(f"destination exists and is not a directory: {destination}")
        if any(destination.iterdir()):
            raise ValueError(f"destination is not empty: {destination}")
    else:
        destination.mkdir(parents=True)


def report_path_for(destination: Path) -> Path:
    return destination.parent / f"{destination.name}-conversion-report.json"


def write_report(report: ConversionReport, destination: Path) -> Path:
    report.finished_at = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    report_path = report_path_for(destination)
    payload = asdict(report)
    payload["totals"] = report.totals()
    report_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report_path


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    source = args.source.expanduser().resolve()
    destination = args.destination.expanduser().resolve()
    if not source.is_dir():
        print(f"error: source is not a directory: {source}", file=sys.stderr)
        return 2
    if source == destination or source in destination.parents:
        print("error: destination must not be inside the source tree", file=sys.stderr)
        return 2

    report = ConversionReport(
        source=str(source),
        destination=str(destination),
        prefix=args.prefix,
        started_at=time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    )
    try:
        ensure_new_destination(destination)
        mboxes = discover_mboxes(source, args.allow_non_mbox, report)
        if not mboxes:
            raise ValueError("no Thunderbird mbox files found")
        for number, mbox_path in enumerate(mboxes, start=1):
            relative = mbox_path.relative_to(source)
            print(f"[{number}/{len(mboxes)}] {relative}", flush=True)
            folder_result = convert_mbox(source, destination, mbox_path, args.prefix)
            report.folders.append(folder_result)
            print(
                f"  -> {folder_result.mailbox}: {folder_result.messages} messages, "
                f"{folder_result.expunged_skipped} expunged skipped",
                flush=True,
            )
        report_path = write_report(report, destination)
    except Exception as error:
        report.warnings.append(str(error))
        try:
            report_path = write_report(report, destination)
            print(f"partial report: {report_path}", file=sys.stderr)
        except Exception:
            pass
        print(f"error: {error}", file=sys.stderr)
        return 1

    totals = report.totals()
    print(
        f"complete: {totals['folders']} folders, {totals['messages']} messages, "
        f"{totals['expunged_skipped']} expunged skipped, {totals['partial_messages']} partial",
        flush=True,
    )
    print(f"report: {report_path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
