#!/usr/bin/env python3
"""
Copies the ACTIVE WhatsApp account's databases out of the newest Finder backup
into ios-copy/active/. Read-only on the backup.

    wamerge extract
"""
import glob
import os
import shutil
import sqlite3
import sys

ROOT = sys.argv[1] if len(sys.argv) > 1 else os.path.expanduser(
    "~/Library/Application Support/MobileSync/Backup")
DEST = sys.argv[2] if len(sys.argv) > 2 else "ios-copy/active"
AND = sys.argv[3] if len(sys.argv) > 3 else "android-decrypted/msgstore.db"
DOMAIN = "AppDomainGroup-group.net.whatsapp.WhatsApp.shared"
EPOCH = 978307200

backups = sorted((d for d in glob.glob(os.path.join(ROOT, "*")) if os.path.isdir(d)),
                 key=os.path.getmtime, reverse=True)
if not backups:
    sys.exit("No backup found (does Terminal have Full Disk Access?)")
B = backups[0]
if not os.path.exists(os.path.join(B, "Manifest.db")):
    sys.exit(f"STOPPED: the newest folder in {ROOT} is not a finished Finder backup (no Manifest.db)")
man = sqlite3.connect(f"file:{os.path.join(B, 'Manifest.db')}?mode=ro&immutable=1", uri=True)


def disk(fid):
    return os.path.join(B, fid[:2], fid)


android_ids = None
if os.path.exists(AND):
    a = sqlite3.connect(f"file:{os.path.abspath(AND)}?mode=ro", uri=True)
    android_ids = {(k, fm) for k, fm in a.execute("SELECT key_id, from_me FROM message WHERE key_id IS NOT NULL")}

stores = []
for fid, rel in man.execute(
        "SELECT fileID, relativePath FROM Files WHERE domain=? AND flags=1 AND "
        "(relativePath='ChatStorage.sqlite' OR relativePath LIKE '%/ChatStorage.sqlite')", (DOMAIN,)):
    if not os.path.exists(disk(fid)):
        continue
    db = sqlite3.connect(f"file:{disk(fid)}?mode=ro&immutable=1", uri=True)
    n, oldest, newest, newest_raw, sent30 = db.execute(
        """SELECT count(*), datetime(min(ZMESSAGEDATE)+?, 'unixepoch', 'localtime'),
                  datetime(max(ZMESSAGEDATE)+?, 'unixepoch', 'localtime'), max(ZMESSAGEDATE),
                  sum(ZISFROMME=1 AND ZMESSAGEDATE > (SELECT max(ZMESSAGEDATE) FROM ZWAMESSAGE) - 30*86400)
           FROM ZWAMESSAGE""", (EPOCH, EPOCH)).fetchone()
    same = opposite = 0
    if android_ids is not None:
        for k, fm in db.execute("SELECT ZSTANZAID, ZISFROMME FROM ZWAMESSAGE WHERE ZSTANZAID IS NOT NULL"):
            if (k, fm) in android_ids:
                same += 1
            elif (k, 1 - (fm or 0)) in android_ids:
                opposite += 1
    months = db.execute(
        """SELECT strftime('%Y-%m', ZMESSAGEDATE+?, 'unixepoch', 'localtime') m, count(*)
           FROM ZWAMESSAGE GROUP BY 1 ORDER BY 1 DESC LIMIT 6""", (EPOCH,)).fetchall()
    folder = os.path.dirname(rel)
    stores.append({"rel": rel, "folder": folder, "n": n, "oldest": oldest, "newest": newest,
                   "newest_raw": newest_raw or 0, "sent30": sent30 or 0, "same": same,
                   "opposite": opposite, "months": months})
    db.close()

if not stores:
    sys.exit("No ChatStorage.sqlite found in the backup")

# The account to merge into is the one that is the same number as the Android
# phone: its messages never appear "the other way round" in the Android history,
# and it is the one you actively send from.
stores.sort(key=lambda s: (s["opposite"] == 0, s["sent30"]), reverse=True)
if len(stores) > 1 and android_ids is None:
    sys.exit(f"STOPPED: the backup holds {len(stores)} WhatsApp accounts and {AND} was not found, "
             "so there is no way to tell which one matches the Android history. Nothing copied.")
if len(stores) > 1:
    a, b = stores[0], stores[1]
    if a["opposite"] > 0 or a["sent30"] <= b["sent30"]:
        sys.exit("STOPPED: cannot tell which account matches the Android history. Nothing copied.")
print(f"WhatsApp accounts in the backup: {len(stores)}")
for i, s in enumerate(stores):
    where = "main folder" if not s["folder"] else "data/" + s["folder"].split("/")[-1][:8] + "..."
    print(f"\n  account stored in {where}")
    print(f"     messages: {s['n']}   from {s['oldest']} to {s['newest']}")
    print(f"     sent by you in its last 30 days: {s['sent30']}")
    print(f"     messages per month (newest first): {s['months']}")
    print(f"     messages also in the Android history: {s['same']} the same way round, "
          f"{s['opposite']} sent on one side and received on the other")

active = stores[0]
print(f"\nUsing the account that matches the Android history and that you send from "
      f"({'main folder' if not active['folder'] else 'data/' + active['folder'].split('/')[-1][:8] + '...'}).")

os.makedirs(DEST, exist_ok=True)
prefix = (active["folder"] + "/") if active["folder"] else ""
for name in ("ChatStorage.sqlite", "LID.sqlite", "ContactsV2.sqlite"):
    row = man.execute("SELECT fileID FROM Files WHERE domain=? AND relativePath=?",
                      (DOMAIN, prefix + name)).fetchone()
    target = os.path.join(DEST, name)
    for suffix in ("", "-wal", "-shm"):
        if os.path.exists(target + suffix):
            os.remove(target + suffix)
    if row and os.path.exists(disk(row[0])):
        shutil.copyfile(disk(row[0]), target)
        print(f"   copied {name} ({os.path.getsize(target)} bytes)")
    else:
        print(f"   {name}: not in the backup for this account")
wal = man.execute("SELECT fileID FROM Files WHERE domain=? AND relativePath=?",
                  (DOMAIN, prefix + "ChatStorage.sqlite-wal")).fetchone()
if wal and os.path.exists(disk(wal[0])) and os.path.getsize(disk(wal[0])) > 0:
    print("\n   WARNING: the backup also holds a non-empty ChatStorage.sqlite-wal. Its newest messages are not\n"
          "   in the copy, and 'wamerge install' will refuse this backup. Make a fresh backup and try again.")
with open(os.path.join(DEST, "SOURCE.txt"), "w") as f:
    f.write(prefix + "ChatStorage.sqlite\n")
print(f"\nSaved to {DEST}/")
