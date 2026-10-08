#!/usr/bin/env python3
"""
Read-only look at how the newest Finder backup records WhatsApp's database.
Changes nothing. Prints structure and sizes only, no message content.

    wamerge backup-check
"""
import glob
import hashlib
import os
import plistlib
import sqlite3
import sys

ROOT = os.path.expanduser("~/Library/Application Support/MobileSync/Backup")
if len(sys.argv) > 1:
    ROOT = sys.argv[1]
DOMAIN = "AppDomainGroup-group.net.whatsapp.WhatsApp.shared"
APPLE_EPOCH = 978307200

backups = sorted((d for d in glob.glob(os.path.join(ROOT, "*")) if os.path.isdir(d)),
                 key=os.path.getmtime, reverse=True)
if not backups:
    sys.exit("No backup found (does Terminal have Full Disk Access?)")
B = backups[0]
print(f"backups on this Mac: {len(backups)}; using the newest")

for name in ("Manifest.plist", "Status.plist", "Info.plist"):
    path = os.path.join(B, name)
    if not os.path.exists(path):
        print(f"{name}: missing")
        continue
    with open(path, "rb") as f:
        p = plistlib.load(f)
    if name == "Manifest.plist":
        print(f"Manifest.plist: IsEncrypted={p.get('IsEncrypted')} Version={p.get('Version')} "
              f"Date={p.get('Date')} keys={sorted(p.keys())}")
        print(f"   Lockdown.ProductVersion={p.get('Lockdown', {}).get('ProductVersion')}")
    elif name == "Status.plist":
        print(f"Status.plist: {{'BackupState': {p.get('BackupState')!r}, 'IsFullBackup': {p.get('IsFullBackup')!r}, "
              f"'SnapshotState': {p.get('SnapshotState')!r}, 'Version': {p.get('Version')!r}, 'Date': {p.get('Date')!r}}}")
    else:
        print(f"Info.plist: Product Version={p.get('Product Version')} Last Backup Date={p.get('Last Backup Date')}")

man = sqlite3.connect(f"file:{os.path.join(B, 'Manifest.db')}?mode=ro", uri=True)
print("Manifest.db tables:", [r[0] for r in man.execute("SELECT name FROM sqlite_master WHERE type='table'")])
print("Files columns:", [r[1] for r in man.execute("PRAGMA table_info(Files)")])


def describe(file_id, rel, flags, blob):
    path = os.path.join(B, file_id[:2], file_id)
    on_disk = os.path.getsize(path) if os.path.exists(path) else None
    print(f"\n{rel}")
    print(f"   flags={flags} stored_as={file_id[:2]}/{file_id[:8]}... on_disk_bytes={on_disk}")
    if blob is None:
        print("   (no metadata record)")
        return
    p = plistlib.loads(blob)
    print(f"   record: archiver={p.get('$archiver')} top_keys={sorted(p.keys())}")
    for obj in p.get("$objects", []):
        if isinstance(obj, dict) and "Size" in obj:
            shown = {}
            for k, v in obj.items():
                if isinstance(v, plistlib.UID):
                    target = p["$objects"][v.data]
                    if isinstance(target, bytes):
                        shown[k] = f"<{len(target)} bytes: {target.hex()}>" if len(target) <= 32 else f"<{len(target)} bytes>"
                    elif isinstance(target, dict):
                        shown[k] = "<object: " + ",".join(sorted(str(x) for x in target.keys())) + ">"
                    elif k == "RelativePath":
                        shown[k] = "<path>"
                    else:
                        shown[k] = repr(target)
                else:
                    shown[k] = v
            for k in sorted(shown):
                print(f"      {k} = {shown[k]}")
            print(f"   Size matches file on disk: {obj.get('Size') == on_disk}")
    if on_disk is not None and on_disk < 2_000_000_000:
        h1, h256 = hashlib.sha1(), hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h1.update(chunk)
                h256.update(chunk)
        print(f"   sha1 of file   = {h1.hexdigest()}")
        print(f"   sha256 of file = {h256.hexdigest()}")


rows = man.execute(
    "SELECT fileID, relativePath, flags, file FROM Files WHERE domain=? AND "
    "(relativePath LIKE 'ChatStorage%' OR relativePath LIKE '%.sqlite' OR relativePath LIKE '%.sqlite-%' "
    " OR relativePath LIKE '%.db')", (DOMAIN,)).fetchall()
main = None
for file_id, rel, flags, blob in rows:
    if rel == "ChatStorage.sqlite":
        main = file_id
        describe(file_id, rel, flags, blob)

print("\nOther databases WhatsApp keeps in the same place (name, bytes):")
for file_id, rel, flags, blob in sorted(rows, key=lambda r: r[1]):
    if rel == "ChatStorage.sqlite" or "/" in rel.strip("/") and rel.count("/") > 1:
        continue
    path = os.path.join(B, file_id[:2], file_id)
    print(f"   {rel}  {os.path.getsize(path) if os.path.exists(path) else 'missing'}")

n_files, n_media = man.execute(
    "SELECT count(*), sum(relativePath LIKE 'Message/Media/%') FROM Files WHERE domain=?", (DOMAIN,)).fetchone()
print(f"\nWhatsApp shared-container entries in the backup: {n_files} (media files: {n_media})")

if main:
    db = sqlite3.connect(f"file:{os.path.join(B, main[:2], main)}?mode=ro", uri=True)
    n, newest = db.execute(
        "SELECT count(*), datetime(max(ZMESSAGEDATE)+?, 'unixepoch', 'localtime') FROM ZWAMESSAGE",
        (APPLE_EPOCH,)).fetchone()
    print(f"\nChatStorage in this backup: {n} messages, newest {newest}")
    print("   newest five message times:",
          [r[0] for r in db.execute(
              "SELECT datetime(ZMESSAGEDATE+?, 'unixepoch', 'localtime') FROM ZWAMESSAGE "
              "ORDER BY ZMESSAGEDATE DESC LIMIT 5", (APPLE_EPOCH,))])
else:
    print("\nChatStorage.sqlite not found in this backup")
