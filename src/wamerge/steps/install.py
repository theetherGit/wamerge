#!/usr/bin/env python3
"""
Puts the merged WhatsApp database into the newest Finder backup.

Default is a DRY RUN: it checks everything and changes nothing.

    wamerge install            # dry run
    wamerge install --apply    # make the change

With --apply it first keeps an untouched copy of the whole backup in
backup-untouched/ in the working folder (an instant APFS clone), then replaces
one file in the backup and updates that file's size in the backup index.
"""
import glob
import os
import plistlib
import shutil
import sqlite3
import subprocess
import sys
import time

args = [a for a in sys.argv[1:] if not a.startswith("--")]
APPLY = "--apply" in sys.argv
ROOT = args[0] if len(args) > 0 else os.path.expanduser("~/Library/Application Support/MobileSync/Backup")
MERGED = args[1] if len(args) > 1 else "output/ChatStorage.merged.sqlite"
ACTIVE = args[2] if len(args) > 2 else "ios-copy/active"
SAFE = args[3] if len(args) > 3 else "backup-untouched"
DOMAIN = "AppDomainGroup-group.net.whatsapp.WhatsApp.shared"


def stop(msg):
    sys.exit("STOPPED, nothing changed: " + msg)


for p in (MERGED, os.path.join(ACTIVE, "SOURCE.txt")):
    if not os.path.exists(p):
        stop(f"not found: {p} (run from your working folder, after 'wamerge extract' and 'wamerge merge')")
for suffix in ("-wal", "-journal"):
    if os.path.exists(MERGED + suffix) and os.path.getsize(MERGED + suffix) > 0:
        stop(f"{MERGED}{suffix} exists; the merged database is not fully written. Run 'wamerge merge' again.")
for suffix in ("-wal", "-shm"):          # empty or index-only leftovers from viewing the file
    if os.path.exists(MERGED + suffix):
        os.remove(MERGED + suffix)

rel = open(os.path.join(ACTIVE, "SOURCE.txt")).read().strip()
backups = sorted((d for d in glob.glob(os.path.join(ROOT, "*")) if os.path.isdir(d)),
                 key=os.path.getmtime, reverse=True)
if not backups:
    stop("no backup found (does Terminal have Full Disk Access?)")
B = backups[0]
name = os.path.basename(B)
print(f"backups on this Mac: {len(backups)}; newest is the target")

with open(os.path.join(B, "Manifest.plist"), "rb") as f:
    mp = plistlib.load(f)
if mp.get("IsEncrypted"):
    stop("the newest backup is encrypted; this method needs an unencrypted one")
with open(os.path.join(B, "Status.plist"), "rb") as f:
    st = plistlib.load(f)
if st.get("SnapshotState") != "finished":
    stop(f"the backup did not finish (state: {st.get('SnapshotState')})")
print(f"backup made: {mp.get('Date')} (UTC)   iOS {mp.get('Lockdown', {}).get('ProductVersion')}")

man_path = os.path.join(B, "Manifest.db")
man = sqlite3.connect(f"file:{man_path}?mode=ro", uri=True)
row = man.execute("SELECT fileID, file FROM Files WHERE domain=? AND relativePath=?", (DOMAIN, rel)).fetchone()
man.close()
if not row:
    stop("the active account's database is not listed in this backup")
file_id, blob = row
target = os.path.join(B, file_id[:2], file_id)
if not os.path.exists(target):
    stop("the active account's database file is missing from this backup")

record = plistlib.loads(blob)
meta = next((o for o in record["$objects"] if isinstance(o, dict) and "Size" in o), None)
if meta is None:
    stop("the backup index record has an unexpected layout")
has_digest = "Digest" in meta
new_size = os.path.getsize(MERGED)
print(f"file in backup now: {os.path.getsize(target)} bytes (index says {meta['Size']})")
print(f"merged file:        {new_size} bytes")
print(f"index record keeps a checksum: {has_digest}")
if has_digest:
    stop("this backup records a checksum for the file; the script does not handle that yet")

# The merged file must be built from exactly the database that is in this backup.
chk = sqlite3.connect(f"file:{os.path.abspath(MERGED)}?mode=ro&immutable=1", uri=True)
if chk.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
    stop("the merged database fails its integrity check")
chk.execute(f"ATTACH DATABASE 'file:{target}?mode=ro&immutable=1' AS b")
b_count, b_fp = chk.execute(
    "SELECT count(*), total(Z_PK) + total(ZMESSAGEDATE) + total(length(ZSTANZAID)) FROM b.ZWAMESSAGE").fetchone()
b_max = chk.execute("SELECT coalesce(max(Z_PK),0) FROM b.ZWAMESSAGE").fetchone()[0]
m_count, m_fp = chk.execute(
    "SELECT count(*), total(Z_PK) + total(ZMESSAGEDATE) + total(length(ZSTANZAID)) FROM main.ZWAMESSAGE "
    "WHERE Z_PK <= ?", (b_max,)).fetchone()
m_total = chk.execute("SELECT count(*) FROM main.ZWAMESSAGE").fetchone()[0]
b_sessions = chk.execute("SELECT count(*) FROM b.ZWACHATSESSION").fetchone()[0]
m_sessions = chk.execute(
    "SELECT count(*) FROM main.ZWACHATSESSION WHERE Z_PK <= (SELECT coalesce(max(Z_PK),0) FROM b.ZWACHATSESSION)"
).fetchone()[0]
newest = chk.execute(
    "SELECT datetime(max(ZMESSAGEDATE)+978307200,'unixepoch','localtime') FROM b.ZWAMESSAGE").fetchone()[0]
chk.close()
print(f"backup database: {b_count} messages, newest {newest}")
print(f"merged database: {m_total} messages, of which {m_count} are the backup's own")
if (b_count, b_fp) != (m_count, m_fp) or b_sessions != m_sessions:
    stop("the merged file was built from a DIFFERENT backup than the newest one. "
         "Run 'wamerge extract' and 'wamerge merge' again, then retry.")
if m_total <= b_count:
    stop("the merged file adds nothing")
print("merged file matches this backup: yes")

if not APPLY:
    print("\nDRY RUN complete. Everything checks out; nothing was changed.")
    print("To make the change: wamerge install --apply")
    sys.exit(0)

# 1. Keep an untouched copy of the whole backup.
safe = os.path.join(SAFE, name)
if os.path.exists(safe):
    print(f"\nuntouched copy already exists: {safe}")
    sm = sqlite3.connect(f"file:{os.path.join(safe, 'Manifest.db')}?mode=ro", uri=True)
    srow = sm.execute("SELECT file FROM Files WHERE fileID=?", (file_id,)).fetchone()
    sm.close()
    with open(os.path.join(safe, "Manifest.plist"), "rb") as f:
        if plistlib.load(f).get("Date") != mp.get("Date") or not srow or srow[0] != blob:
            stop(f"{safe} is from a different backup or already modified. Move it away first.")
else:
    os.makedirs(SAFE, exist_ok=True)
    cmd = ["cp", "-Rc", B, safe] if sys.platform == "darwin" else ["cp", "-R", B, safe]
    print("\nkeeping an untouched copy of the backup ...")
    if subprocess.run(cmd).returncode != 0 or not os.path.exists(os.path.join(safe, "Manifest.db")):
        shutil.rmtree(safe, ignore_errors=True)
        stop("could not copy the backup (check free disk space)")
    if os.path.getsize(os.path.join(safe, file_id[:2], file_id)) != os.path.getsize(target):
        stop("the untouched copy is incomplete")
    print(f"untouched copy saved: {safe}")

# 2. Replace the file and update its size in the index.
meta["Size"] = new_size
meta["LastModified"] = int(time.time())
new_blob = plistlib.dumps(record, fmt=plistlib.FMT_BINARY)
tmp = target + ".tmp"
shutil.copyfile(MERGED, tmp)
os.replace(tmp, target)
man = sqlite3.connect(man_path)
man.execute("UPDATE Files SET file=? WHERE fileID=?", (new_blob, file_id))
man.commit()
ok = man.execute("PRAGMA integrity_check").fetchone()[0]
man.close()

# 3. Read it back.
check = sqlite3.connect(f"file:{target}?mode=ro&immutable=1", uri=True)
n = check.execute("SELECT count(*) FROM ZWAMESSAGE").fetchone()[0]
check.close()
man = sqlite3.connect(f"file:{man_path}?mode=ro", uri=True)
size_now = next(o for o in plistlib.loads(man.execute(
    "SELECT file FROM Files WHERE fileID=?", (file_id,)).fetchone()[0])["$objects"]
    if isinstance(o, dict) and "Size" in o)["Size"]
man.close()
print(f"\nINSTALLED. The backup's WhatsApp database now has {n} messages.")
print(f"index size {size_now} == file size {os.path.getsize(target)}: {size_now == os.path.getsize(target)}; "
      f"index integrity: {ok}")
print(f"To undo: delete the backup folder and copy {safe} back in its place.")
