#!/usr/bin/env python3
"""
Read-only diagnostic. Changes nothing, prints no message text, names or numbers.

Answers three questions:
  1. Does the Finder backup hold more than one WhatsApp message store
     (a second account, WhatsApp Business), and which one is current?
  2. Is the store we merged into missing recent days?
  3. Did the merge leave one person split across two chats?

    wamerge find-stores > output/stores.txt
"""
import glob
import os
import plistlib
import re
import sqlite3
import struct
import sys

ROOT = sys.argv[1] if len(sys.argv) > 1 else os.path.expanduser(
    "~/Library/Application Support/MobileSync/Backup")
IOS = sys.argv[2] if len(sys.argv) > 2 else "ios-copy/ChatStorage.sqlite"
MERGED = sys.argv[3] if len(sys.argv) > 3 else "output/ChatStorage.merged.sqlite"
EPOCH = 978307200


def mask(s):
    return re.sub(r"\d{6,}", "<digits>", s or "")


def ro(path):
    return sqlite3.connect(f"file:{os.path.abspath(path)}?mode=ro&immutable=1", uri=True)


backups = sorted((d for d in glob.glob(os.path.join(ROOT, "*")) if os.path.isdir(d)),
                 key=os.path.getmtime, reverse=True)
if not backups:
    sys.exit("No backup found (does Terminal have Full Disk Access?)")
B = backups[0]
man = ro(os.path.join(B, "Manifest.db"))


def disk(file_id):
    return os.path.join(B, file_id[:2], file_id)


print("=" * 70)
print("1. WHATSAPP DATA IN THE BACKUP")
print("=" * 70)
try:
    with open(os.path.join(B, "Manifest.plist"), "rb") as f:
        apps = plistlib.load(f).get("Applications", {})
    print("installed apps with 'whatsapp' in the id:",
          sorted(a for a in apps if "whatsapp" in a.lower()) or "none")
except Exception as e:
    print("could not read app list:", e)

print("\nbackup sections (domains) mentioning WhatsApp:")
for dom, n in man.execute(
        "SELECT domain, count(*) FROM Files WHERE lower(domain) LIKE '%whatsapp%' GROUP BY 1 ORDER BY 2 DESC"):
    print(f"   {n:>7} entries  {dom}")

print("\nwrite-ahead log files recorded for WhatsApp (-wal / -shm):",
      man.execute("SELECT count(*) FROM Files WHERE lower(domain) LIKE '%whatsapp%' AND "
                  "(relativePath LIKE '%-wal' OR relativePath LIKE '%-shm')").fetchone()[0])

stores = man.execute(
    "SELECT fileID, domain, relativePath FROM Files WHERE flags = 1 AND "
    "(relativePath LIKE '%ChatStorage%' OR relativePath LIKE '%msgstore%')").fetchall()
print(f"\nmessage stores found anywhere in the backup: {len(stores)}")
for file_id, dom, rel in stores:
    path = disk(file_id)
    size = os.path.getsize(path) if os.path.exists(path) else None
    print(f"\n   [{dom}]")
    print(f"   {mask(rel)}   bytes={size}")
    if not size or not rel.endswith(".sqlite"):
        continue
    with open(path, "rb") as f:
        head = f.read(100)
    page_size = struct.unpack(">H", head[16:18])[0] or 65536
    pages = struct.unpack(">I", head[28:32])[0]
    print(f"   header: journal_version={head[18]} (2 means write-ahead log) "
          f"pages*page_size={pages * page_size} matches_file={pages * page_size == size}")
    try:
        db = ro(path)
        n, newest = db.execute(
            "SELECT count(*), datetime(max(ZMESSAGEDATE)+?, 'unixepoch', 'localtime') FROM ZWAMESSAGE",
            (EPOCH,)).fetchone()
        chats = db.execute("SELECT count(*) FROM ZWACHATSESSION").fetchone()[0]
        print(f"   messages={n} chats={chats} newest={newest}")
        print("   messages per day, last 14 days with any (day, received, sent):")
        for day, rcv, snt in db.execute(
                """SELECT date(ZMESSAGEDATE+?, 'unixepoch', 'localtime') d,
                          sum(ZISFROMME=0), sum(ZISFROMME=1)
                   FROM ZWAMESSAGE GROUP BY 1 ORDER BY 1 DESC LIMIT 14""", (EPOCH,)):
            print(f"      {day}  {rcv:>5} {snt:>5}")
        print("   last-message time of the 12 most recent chats (as the chat list would show):")
        print("     ", [r[0] for r in db.execute(
            """SELECT datetime(ZLASTMESSAGEDATE+?, 'unixepoch', 'localtime') FROM ZWACHATSESSION
               WHERE ZLASTMESSAGEDATE IS NOT NULL ORDER BY ZLASTMESSAGEDATE DESC LIMIT 12""", (EPOCH,))])
    except sqlite3.Error as e:
        print(f"   (could not read: {e})")

print("\nall SQLite databases in WhatsApp sections, largest first (top 25):")
rows = []
for file_id, dom, rel in man.execute(
        "SELECT fileID, domain, relativePath FROM Files WHERE flags = 1 AND lower(domain) LIKE '%whatsapp%' "
        "AND (relativePath LIKE '%.sqlite' OR relativePath LIKE '%.db')"):
    p = disk(file_id)
    rows.append((os.path.getsize(p) if os.path.exists(p) else 0, dom.split("-")[-1], mask(rel)))
for size, dom, rel in sorted(rows, reverse=True)[:25]:
    print(f"   {size:>11}  {dom}  {rel}")

print()
print("=" * 70)
print("2. THE CHAT THAT LOOKED WRONG (chats whose newest message is 2 Sep 2026)")
print("=" * 70)
if os.path.exists(MERGED) and os.path.exists(IOS):
    orig = ro(IOS)
    orig_max_session = orig.execute("SELECT coalesce(max(Z_PK),0) FROM ZWACHATSESSION").fetchone()[0]
    orig_max_msg = orig.execute("SELECT coalesce(max(Z_PK),0) FROM ZWAMESSAGE").fetchone()[0]
    m = ro(MERGED)
    print("   origin         address   messages  from_iphone  from_android  newest")
    for pk, jid, n, n_ios, newest in m.execute(
            """SELECT s.Z_PK, s.ZCONTACTJID, count(*), sum(x.Z_PK <= ?),
                      datetime(max(x.ZMESSAGEDATE)+?, 'unixepoch', 'localtime')
               FROM ZWACHATSESSION s JOIN ZWAMESSAGE x ON x.ZCHATSESSION = s.Z_PK
               GROUP BY s.Z_PK
               HAVING date(max(x.ZMESSAGEDATE)+?, 'unixepoch', 'localtime') = '2026-09-02'""",
            (orig_max_msg, EPOCH, EPOCH)):
        origin = "iPhone chat" if pk <= orig_max_session else "new (Android)"
        print(f"   {origin:<14} @{jid.split('@')[-1]:<9}{n:>8}{n_ios:>13}{n - n_ios:>14}  {newest}")

    print()
    print("=" * 70)
    print("3. ONE PERSON SPLIT ACROSS TWO CHATS?")
    print("=" * 70)
    lid_users = {j.split("@")[0]: pk for pk, j in orig.execute(
        "SELECT Z_PK, ZCONTACTJID FROM ZWACHATSESSION WHERE ZCONTACTJID LIKE '%@lid'")}
    pn_old = {j.split("@")[0]: pk for pk, j in orig.execute(
        "SELECT Z_PK, ZCONTACTJID FROM ZWACHATSESSION WHERE ZCONTACTJID LIKE '%@s.whatsapp.net'")}
    new_pn = {j.split("@")[0]: pk for pk, j in m.execute(
        "SELECT Z_PK, ZCONTACTJID FROM ZWACHATSESSION WHERE Z_PK > ? AND ZCONTACTJID LIKE '%@s.whatsapp.net'",
        (orig_max_session,))}
    new_lid = {j.split("@")[0]: pk for pk, j in m.execute(
        "SELECT Z_PK, ZCONTACTJID FROM ZWACHATSESSION WHERE Z_PK > ? AND ZCONTACTJID LIKE '%@lid'",
        (orig_max_session,))}
    print(f"   iPhone chats addressed by hidden id: {len(lid_users)}, by phone number: {len(pn_old)}")
    print(f"   chats the merge created by phone number: {len(new_pn)}, by hidden id: {len(new_lid)}")

    def scan(rel_name):
        row = man.execute(
            "SELECT fileID FROM Files WHERE domain='AppDomainGroup-group.net.whatsapp.WhatsApp.shared' "
            "AND relativePath=?", (rel_name,)).fetchone()
        if not row or not os.path.exists(disk(row[0])):
            print(f"\n   {rel_name}: not in backup")
            return
        try:
            d = ro(disk(row[0]))
            tables = [r[0] for r in d.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        except sqlite3.Error as e:
            print(f"\n   {rel_name}: could not open ({e})")
            return
        print(f"\n   {rel_name}:")
        pairs_a, pairs_b = set(), set()
        for t in tables:
            try:
                cols = [r[1] for r in d.execute(f'PRAGMA table_info("{t}")')]
                count = d.execute(f'SELECT count(*) FROM "{t}"').fetchone()[0]
                print(f"      table {t} ({count} rows): {', '.join(cols)}")
                for r in d.execute(f'SELECT * FROM "{t}"'):
                    vals = set()
                    for v in r:
                        if isinstance(v, int):
                            vals.add(str(v))
                        elif isinstance(v, str):
                            vals.add(v.split("@")[0].split(":")[0].lstrip("+"))
                    l_old = vals & lid_users.keys()
                    p_new = vals & new_pn.keys()
                    for l in l_old:
                        for p in p_new:
                            pairs_a.add((lid_users[l], new_pn[p]))
                    for p in vals & pn_old.keys():
                        for l in vals & new_lid.keys():
                            pairs_b.add((pn_old[p], new_lid[l]))
            except sqlite3.Error as e:
                print(f"      table {t}: unreadable ({e})")
        for label, pairs in (("iPhone hidden-id chat  <->  new phone-number chat", pairs_a),
                             ("iPhone phone-number chat  <->  new hidden-id chat", pairs_b)):
            msgs = 0
            for _, new_pk in {(None, b) for _, b in pairs}:
                msgs += m.execute("SELECT count(*) FROM ZWAMESSAGE WHERE ZCHATSESSION=?", (new_pk,)).fetchone()[0]
            print(f"      same person, {label}: {len(pairs)} pairs, {msgs} messages in the new halves")

    scan("LID.sqlite")
    scan("ContactsV2.sqlite")
else:
    print("   (merged database or iPhone copy not found; run from your working folder)")
