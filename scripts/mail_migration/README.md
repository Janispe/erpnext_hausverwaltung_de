# Thunderbird local folders to Vandelay/Stalwart

This is a staging-only migration helper. It never writes to the copied
Thunderbird source and it is not pointed at Stalwart's data directory.

The converter understands Thunderbird's `folder` + `folder.sbd/` layout,
skips `.msf` indexes and messages marked `Expunged`, and creates a Dovecot
Maildir tree using filesystem hierarchy. Common flags and `X-Mozilla-Keys`
are translated to Maildir flags/keywords. The raw Thunderbird metadata
headers remain in each message as an additional audit trail.

Run from this directory's repository root:

```bash
python3 scripts/mail_migration/thunderbird_mbox_to_dovecot.py \
  "/path/to/prepared/private/source" \
  "/path/to/new/empty/work/vmail/migration/Maildir"
```

The destination must be new or empty. Review the adjacent
`Maildir-conversion-report.json` before starting Dovecot. A Dovecot test
container can then mount the `vmail` parent at `/srv/vmail` and the supplied config file at
`/etc/dovecot/conf.d/99-thunderbird-migration.conf`.

Publish any temporary IMAP port on `127.0.0.1` only. The supplied Dovecot
snippet configures mailbox storage; it does not restrict container port
publication. No Stalwart import is performed by the converter.

Run the fixture-based tests without accessing a mail archive:

```bash
python3 -m unittest discover -s scripts/mail_migration -p 'test_*.py'
```
