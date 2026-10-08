#!/usr/bin/env python3
"""
Stage 1 merge: add the old Android text history to a COPY of the iPhone
WhatsApp database. Runs entirely on the Mac; the phone is not involved.

Reads   android-decrypted/msgstore.db      (opened read-only)
        ios-copy/active/ChatStorage.sqlite  (opened read-only, copied)
Writes  output/ChatStorage.merged.sqlite    (the merged copy)
        output/merge-report.txt             (counts only, no message content)

What it brings across: 1:1 chats, groups, group senders, text messages,
starred / archived state. What it leaves for later stages: photos, videos,
voice notes, documents, stickers, reply-quotes, reactions, polls, calls and
system notices.

Run from your working folder:

    wamerge merge
"""
import os
import shutil
import sqlite3
import sys
from collections import defaultdict

AND = sys.argv[1] if len(sys.argv) > 1 else "android-decrypted/msgstore.db"
IOS = sys.argv[2] if len(sys.argv) > 2 else "ios-copy/active/ChatStorage.sqlite"
OUT = sys.argv[3] if len(sys.argv) > 3 else "output/ChatStorage.merged.sqlite"
REPORT = os.path.join(os.path.dirname(OUT) or ".", "merge-report.txt")
WORK = OUT + ".partial"          # renamed to OUT only after every check passes

APPLE_EPOCH = 978307200
FAR_FUTURE = 4102444800 - APPLE_EPOCH      # year 2100
ENT_SESSION, ENT_GROUPINFO, ENT_MEMBER, ENT_MESSAGE = 4, 5, 6, 9
SERVERS = ("s.whatsapp.net", "lid", "g.us")

lines = []


def out(s=""):
    print(s)
    lines.append(s)


def die(msg):
    remove(WORK)
    sys.exit("STOPPED: " + msg)


def remove(base):
    for suffix in ("", "-wal", "-shm", "-journal"):
        if os.path.exists(base + suffix):
            os.remove(base + suffix)


for p in (AND, IOS):
    if not os.path.exists(p):
        die(f"not found: {p} (run this from your working folder)")
if os.path.abspath(OUT) == os.path.abspath(IOS):
    die("output path is the same as the iPhone copy")

# --------------------------------------------------------------------------
# 0. Work on a copy. The source files are never opened for writing.
# --------------------------------------------------------------------------
os.makedirs(os.path.dirname(OUT) or ".", exist_ok=True)
# A failed or interrupted run must not leave an old output or report behind.
remove(OUT)
remove(WORK)
if os.path.exists(REPORT):
    os.remove(REPORT)
src = sqlite3.connect(f"file:{os.path.abspath(IOS)}?mode=ro", uri=True)
if src.execute("PRAGMA quick_check").fetchone()[0] != "ok":
    die("the iPhone database copy fails its integrity check")
ORIG_JOURNAL = src.execute("PRAGMA journal_mode").fetchone()[0]
src.close()
shutil.copyfile(IOS, WORK)

adb = sqlite3.connect(f"file:{os.path.abspath(AND)}?mode=ro", uri=True)
db = sqlite3.connect(WORK)
db.execute("PRAGMA foreign_keys=OFF")

# Confirm the iPhone database is laid out the way this script expects.
ents = dict(db.execute("SELECT Z_NAME, Z_ENT FROM Z_PRIMARYKEY"))
expected = {"WAChatSession": ENT_SESSION, "WAGroupInfo": ENT_GROUPINFO,
            "WAGroupMember": ENT_MEMBER, "WAMessage": ENT_MESSAGE}
for name, ent in expected.items():
    if ents.get(name) != ent:
        die(f"unexpected entity number for {name}: {ents.get(name)} (expected {ent})")
if db.execute("SELECT count(*) FROM sqlite_master WHERE type='trigger'").fetchone()[0]:
    die("the iPhone database has triggers; this script was not written for that")

before = {t: db.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
          for t in ("ZWAMESSAGE", "ZWACHATSESSION", "ZWAGROUPMEMBER", "ZWAGROUPINFO", "ZWAMEDIAITEM")}
before_fingerprint = db.execute(
    "SELECT count(*), total(Z_PK), total(length(ZTEXT)), total(ZMESSAGEDATE) FROM ZWAMESSAGE").fetchone()

# --------------------------------------------------------------------------
# 1. Learn the iPhone's own conventions from the rows it already has.
# --------------------------------------------------------------------------
def modal(sql, params=(), default=None):
    row = db.execute(sql, params).fetchone()
    return row[0] if row else default


def msg_template(sesstype, from_me):
    """Most common values the iPhone uses for a plain text message of this kind."""
    tpl = {}
    for col, fallback in (("ZFLAGS", 0), ("ZMESSAGESTATUS", 8), ("ZGROUPEVENTTYPE", 0),
                          ("ZSPOTLIGHTSTATUS", 0), ("ZDATAITEMVERSION", 3)):
        v = None
        for where, params in (
            ("s.ZSESSIONTYPE=? AND m.ZISFROMME=?", (sesstype, from_me)),
            ("m.ZISFROMME=?", (from_me,)),
            ("1=1", ()),
        ):
            row = db.execute(
                f"""SELECT m.{col} FROM ZWAMESSAGE m
                    LEFT JOIN ZWACHATSESSION s ON s.Z_PK = m.ZCHATSESSION
                    WHERE m.ZMESSAGETYPE = 0 AND m.{col} IS NOT NULL AND {where}
                    GROUP BY 1 ORDER BY count(*) DESC LIMIT 1""", params).fetchone()
            if row:
                v = row[0]
                break
        tpl[col] = fallback if v is None else v
    return tpl


MSG_TPL = {(st, fm): msg_template(st, fm) for st in (0, 1) for fm in (0, 1)}


def session_flags(sesstype, server):
    for where, params in (
        ("ZSESSIONTYPE=? AND ZCONTACTJID LIKE ?", (sesstype, "%@" + server)),
        ("ZSESSIONTYPE=?", (sesstype,)),
    ):
        row = db.execute(
            f"""SELECT ZFLAGS FROM ZWACHATSESSION WHERE ZFLAGS IS NOT NULL AND {where}
                GROUP BY 1 ORDER BY count(*) DESC LIMIT 1""", params).fetchone()
        if row:
            return row[0]
    return 0


SESSION_SPOTLIGHT = modal(
    "SELECT ZSPOTLIGHTSTATUS FROM ZWACHATSESSION GROUP BY 1 ORDER BY count(*) DESC LIMIT 1", default=0)
GROUP_STATE = modal(
    "SELECT ZSTATE FROM ZWAGROUPINFO GROUP BY 1 ORDER BY count(*) DESC LIMIT 1", default=0)

# --------------------------------------------------------------------------
# 2. Load identities: Android JIDs, the lid <-> phone-number map, iPhone chats.
# --------------------------------------------------------------------------
jid = {}          # android jid row id -> (raw, user, server)
for rid, user, server, raw in adb.execute("SELECT _id, user, server, raw_string FROM jid"):
    jid[rid] = (raw, user, server)

lid2pn, pn2lid = {}, {}
for lid_row, pn_row in adb.execute("SELECT lid_row_id, jid_row_id FROM jid_map"):
    if lid_row in jid and pn_row in jid:
        l, p = jid[lid_row][0], jid[pn_row][0]
        if l and p:
            lid2pn.setdefault(l, p)
            pn2lid.setdefault(p, l)


# The iPhone keeps its own table of hidden-id <-> phone-number links. Use it too,
# but only if it agrees with the links Android already knows.
import re as _re
MAP_NOTES = []


def _digits(v):
    return _re.sub(r"\D", "", str(v).split("@")[0].split(":")[0]) if v is not None else ""


def load_iphone_links(filename, table, lid_col, pn_col):
    path = os.path.join(os.path.dirname(os.path.abspath(IOS)), filename)
    if not os.path.exists(path):
        MAP_NOTES.append(f"{filename}: not found next to the iPhone database, skipped")
        return
    try:
        c = sqlite3.connect(f"file:{path}?mode=ro&immutable=1", uri=True)
        rows = c.execute(f"SELECT {lid_col}, {pn_col} FROM {table} "
                         f"WHERE {lid_col} IS NOT NULL AND {pn_col} IS NOT NULL").fetchall()
        c.close()
    except sqlite3.Error as e:
        MAP_NOTES.append(f"{filename}: unreadable ({e}), skipped")
        return
    pairs = {}
    for l, p in rows:
        l, p = _digits(l), _digits(p)
        if len(l) >= 8 and len(p) >= 10:
            pairs[l + "@lid"] = p + "@s.whatsapp.net"
    checked = [(l, p) for l, p in pairs.items() if l in lid2pn]
    agree = sum(1 for l, p in checked if lid2pn[l] == p)
    if len(checked) < 20 or agree < 0.98 * len(checked):
        MAP_NOTES.append(f"{filename}: {len(pairs)} links, {agree} of {len(checked)} agree with Android "
                         f"-> NOT used (cannot be trusted)")
        return
    added = 0
    for l, p in pairs.items():
        if l not in lid2pn and p not in pn2lid:
            lid2pn[l] = p
            pn2lid[p] = l
            added += 1
    MAP_NOTES.append(f"{filename}: {len(pairs)} links, {agree} of {len(checked)} agree with Android "
                     f"-> used, {added} new")


ANDROID_LINKS = len(lid2pn)
load_iphone_links("ContactsV2.sqlite", "ZWAADDRESSBOOKCONTACT", "ZLID", "ZWHATSAPPID")
load_iphone_links("LID.sqlite", "ZWAZACCOUNT", "ZIDENTIFIER", "ZPHONENUMBER")


def forms(raw):
    """Every address the same person may be stored under."""
    res = [raw]
    if raw in lid2pn:
        res.append(lid2pn[raw])
    if raw in pn2lid:
        res.append(pn2lid[raw])
    return res


def display(raw):
    """A fallback label for someone we have no saved name for."""
    for f in forms(raw):
        if f and f.endswith("@s.whatsapp.net"):
            return "+" + f.split("@")[0].split(":")[0]
    return None


ios_session = {}  # contact jid -> session pk (only ordinary chats and groups)
session_type = {}
for pk, cj, st in db.execute(
        "SELECT Z_PK, ZCONTACTJID, ZSESSIONTYPE FROM ZWACHATSESSION WHERE ZCONTACTJID IS NOT NULL"):
    session_type[pk] = st
    if cj.split("@")[-1] in SERVERS:
        ios_session.setdefault(cj, pk)
session_jid = {pk: cj for cj, pk in ios_session.items()}

members = {}      # (session pk, member jid) -> member pk
for pk, sess, mj in db.execute("SELECT Z_PK, ZCHATSESSION, ZMEMBERJID FROM ZWAGROUPMEMBER"):
    if mj is not None:
        members.setdefault((sess, mj), pk)

existing_ids = defaultdict(set)   # session pk -> message ids already there
for sess, sid in db.execute("SELECT ZCHATSESSION, ZSTANZAID FROM ZWAMESSAGE WHERE ZSTANZAID IS NOT NULL"):
    existing_ids[sess].add(sid)

# --------------------------------------------------------------------------
# 3. Read the Android text messages and decide where each one goes.
# --------------------------------------------------------------------------
stats = defaultdict(int)
chat_info = {}
for cid, jrow, subject, created, archived, hidden in adb.execute(
        "SELECT _id, jid_row_id, subject, created_timestamp, archived, hidden FROM chat"):
    if jrow in jid and jid[jrow][0]:
        chat_info[cid] = (jid[jrow][0], jid[jrow][2], subject, created, archived or 0, hidden or 0)

skipped_types = defaultdict(int)
for mtype, n in adb.execute(
        """SELECT message_type, count(*) FROM message
           WHERE NOT (message_type = 0 AND text_data IS NOT NULL AND text_data <> '')
           GROUP BY 1"""):
    skipped_types[mtype] += n

# target key -> plan. A target is an existing session pk, or ("new", jid).
plans = {}


def plan_for(cid):
    raw, server, subject, created, archived, hidden = chat_info[cid]
    for f in forms(raw):
        if f in ios_session:
            key = ios_session[f]
            if key not in plans:
                plans[key] = {"pk": key, "jid": session_jid[key], "new": False,
                              "group": server == "g.us", "rows": [], "seen": set(),
                              "sources": set()}
            return plans[key]
    target = raw
    if server == "lid" and raw in lid2pn:
        target = lid2pn[raw]          # keep one chat per person, under the phone number
    key = ("new", target)
    if key not in plans:
        plans[key] = {"pk": None, "jid": target, "new": True, "group": server == "g.us",
                      "subject": subject, "created": created, "archived": archived,
                      "hidden": hidden, "rows": [], "seen": set(), "sources": set()}
    else:
        p = plans[key]
        p["archived"] = min(p["archived"], archived)
        p["hidden"] = min(p["hidden"], hidden)
    return plans[key]


cur = adb.execute(
    """SELECT _id, chat_row_id, from_me, key_id, sender_jid_row_id, timestamp,
              received_timestamp, text_data, starred, sort_id
       FROM message
       WHERE message_type = 0 AND text_data IS NOT NULL AND text_data <> ''
       ORDER BY sort_id, _id""")
for mid, cid, from_me, key_id, sender_row, ts, rts, text, starred, sort_id in cur:
    stats["android text messages read"] += 1
    info = chat_info.get(cid)
    if info is None or info[1] not in SERVERS:
        stats["skipped: not an ordinary chat or group (channels, status, broadcast)"] += 1
        continue
    if not key_id or not ts or ts <= 0:
        stats["skipped: no message id or timestamp"] += 1
        continue
    p = plan_for(cid)
    if not p["new"] and key_id in existing_ids[p["pk"]]:
        stats["skipped: already on the iPhone"] += 1
        continue
    if key_id in p["seen"]:
        stats["skipped: duplicate inside the Android history"] += 1
        continue
    p["seen"].add(key_id)
    p["sources"].add(cid)
    sender = jid[sender_row][0] if (sender_row and sender_row in jid) else None
    p["rows"].append((ts, 1 if from_me else 0, key_id, sender, rts, text, 1 if starred else 0))

plans = {k: p for k, p in plans.items() if p["rows"]}
for p in plans.values():
    if len(p["sources"]) > 1:      # one person stored as two Android chats: order by time
        p["rows"].sort(key=lambda r: r[0])

# --------------------------------------------------------------------------
# 4. Write. Everything happens in one transaction on the copy.
# --------------------------------------------------------------------------
zmax = dict(db.execute("SELECT Z_ENT, Z_MAX FROM Z_PRIMARYKEY"))
next_pk = {}
for ent, table in ((ENT_SESSION, "ZWACHATSESSION"), (ENT_GROUPINFO, "ZWAGROUPINFO"),
                   (ENT_MEMBER, "ZWAGROUPMEMBER"), (ENT_MESSAGE, "ZWAMESSAGE")):
    real = db.execute(f"SELECT coalesce(max(Z_PK), 0) FROM {table}").fetchone()[0]
    next_pk[ent] = max(real, zmax.get(ent) or 0)


def alloc(ent):
    next_pk[ent] += 1
    return next_pk[ent]


def apple(ms):
    return float(int(ms // 1000) - APPLE_EPOCH)


db.execute("BEGIN")
touched_sessions = []

for key, p in plans.items():
    is_group = p["group"]
    sesstype = 1 if is_group else 0

    if p["new"]:
        spk = alloc(ENT_SESSION)
        server = p["jid"].split("@")[-1]
        name = (p.get("subject") if is_group else None) or display(p["jid"]) or p["jid"].split("@")[0]
        db.execute(
            """INSERT INTO ZWACHATSESSION
               (Z_PK, Z_ENT, Z_OPT, ZARCHIVED, ZCONTACTABID, ZFLAGS, ZHIDDEN,
                ZIDENTITYVERIFICATIONEPOCH, ZIDENTITYVERIFICATIONSTATE, ZMESSAGECOUNTER,
                ZREMOVED, ZSESSIONTYPE, ZSPOTLIGHTSTATUS, ZUNREADCOUNT, ZCONTACTJID, ZPARTNERNAME)
               VALUES (?,?,1,?,0,?,?,0,0,0,0,?,?,0,?,?)""",
            (spk, ENT_SESSION, 1 if p["archived"] else 0, session_flags(sesstype, server),
             1 if p["hidden"] else 0, sesstype, SESSION_SPOTLIGHT, p["jid"], name))
        if is_group:
            gpk = alloc(ENT_GROUPINFO)
            created = apple(p["created"]) if p.get("created") and p["created"] > 0 else None
            db.execute(
                """INSERT INTO ZWAGROUPINFO (Z_PK, Z_ENT, Z_OPT, ZSTATE, ZCHATSESSION, ZCREATIONDATE)
                   VALUES (?,?,1,?,?,?)""", (gpk, ENT_GROUPINFO, GROUP_STATE, spk, created))
            db.execute("UPDATE ZWACHATSESSION SET ZGROUPINFO=? WHERE Z_PK=?", (gpk, spk))
            stats["groups created"] += 1
        else:
            stats["1:1 chats created"] += 1
        if p["hidden"]:
            stats["  of which hidden on Android (kept hidden)"] += 1
        if p["archived"]:
            stats["  of which archived on Android (kept archived)"] += 1
        p["pk"] = spk
        existing = []
    else:
        spk = p["pk"]
        if session_type.get(spk) in (0, 1):
            sesstype = session_type[spk]
        existing = db.execute(
            "SELECT Z_PK, ZMESSAGEDATE FROM ZWAMESSAGE WHERE ZCHATSESSION=? ORDER BY ZSORT, Z_PK",
            (spk,)).fetchall()
        stats["existing iPhone chats extended"] += 1

    def member_for(sender):
        if sender is None:
            return None
        for f in forms(sender):
            if (spk, f) in members:
                return members[(spk, f)]
        mpk = alloc(ENT_MEMBER)
        db.execute(
            """INSERT INTO ZWAGROUPMEMBER
               (Z_PK, Z_ENT, Z_OPT, ZCONTACTABID, ZISACTIVE, ZISADMIN, ZSENDERKEYSENT,
                ZCHATSESSION, ZCONTACTNAME, ZMEMBERJID)
               VALUES (?,?,1,0,0,0,0,?,?,?)""", (mpk, ENT_MEMBER, spk, display(sender), sender))
        members[(spk, sender)] = mpk
        stats["group senders added"] += 1
        return mpk

    # Insert the new rows (order fixed afterwards).
    new_rows = []
    for ts, from_me, key_id, sender, rts, text, starred in p["rows"]:
        tpl = MSG_TPL[(1 if is_group else 0, from_me)]
        mpk = alloc(ENT_MESSAGE)
        date = apple(ts)
        sent = apple(rts) if (rts and rts > 0 and not from_me) else date
        member = member_for(sender) if (is_group and not from_me) else None
        db.execute(
            """INSERT INTO ZWAMESSAGE
               (Z_PK, Z_ENT, Z_OPT, ZCHILDMESSAGESDELIVEREDCOUNT, ZCHILDMESSAGESPLAYEDCOUNT,
                ZCHILDMESSAGESREADCOUNT, ZDATAITEMVERSION, ZDOCID, ZENCRETRYCOUNT,
                ZFILTEREDRECIPIENTCOUNT, ZFLAGS, ZGROUPEVENTTYPE, ZISFROMME, ZMESSAGEERRORSTATUS,
                ZMESSAGESTATUS, ZMESSAGETYPE, ZSORT, ZSPOTLIGHTSTATUS, ZSTARRED, ZCHATSESSION,
                ZGROUPMEMBER, ZMESSAGEDATE, ZSENTDATE, ZFROMJID, ZSTANZAID, ZTEXT, ZTOJID)
               VALUES (?,?,1,0,0,0,?,0,0,0,?,?,?,0,?,0,0,?,?,?,?,?,?,?,?,?,?)""",
            (mpk, ENT_MESSAGE, tpl["ZDATAITEMVERSION"], tpl["ZFLAGS"], tpl["ZGROUPEVENTTYPE"],
             from_me, tpl["ZMESSAGESTATUS"], tpl["ZSPOTLIGHTSTATUS"], 1 if starred else None,
             spk, member, date, sent, None if from_me else p["jid"], key_id, text,
             p["jid"] if from_me else None))
        new_rows.append((mpk, date))
        stats["messages added"] += 1
        if starred:
            stats["  of which starred"] += 1

    # Interleave by date, keeping each side's own internal order, then renumber.
    order, i, j = [], 0, 0
    while i < len(existing) or j < len(new_rows):
        take_new = j < len(new_rows) and (
            i >= len(existing) or existing[i][1] is None or new_rows[j][1] < existing[i][1])
        if take_new:
            order.append(new_rows[j][0])
            j += 1
        else:
            order.append(existing[i][0])
            i += 1
    db.executemany("UPDATE ZWAMESSAGE SET ZSORT=? WHERE Z_PK=?",
                   [(n, pk) for n, pk in enumerate(order, start=1)])
    db.execute("UPDATE ZWACHATSESSION SET ZMESSAGECOUNTER=? WHERE Z_PK=?", (len(order) + 1, spk))

    # If one of the added messages is now the newest, make it the chat's preview.
    last_pk = order[-1]
    old_last = db.execute("SELECT ZLASTMESSAGE FROM ZWACHATSESSION WHERE Z_PK=?", (spk,)).fetchone()[0]
    if p["new"] or (last_pk != old_last and last_pk in {r[0] for r in new_rows}):
        d, t = db.execute("SELECT ZMESSAGEDATE, ZTEXT FROM ZWAMESSAGE WHERE Z_PK=?", (last_pk,)).fetchone()
        if old_last:
            db.execute("UPDATE ZWAMESSAGE SET ZLASTSESSION=NULL WHERE Z_PK=?", (old_last,))
        db.execute("UPDATE ZWAMESSAGE SET ZLASTSESSION=? WHERE Z_PK=?", (spk, last_pk))
        # A date far in the future is how WhatsApp marks a pinned chat: keep it.
        db.execute(
            """UPDATE ZWACHATSESSION SET ZLASTMESSAGE=?, ZLASTMESSAGETEXT=?,
                      ZLASTMESSAGEDATE = CASE WHEN ZLASTMESSAGEDATE > ? THEN ZLASTMESSAGEDATE ELSE ? END
               WHERE Z_PK=?""",
            (last_pk, t, FAR_FUTURE, d, spk))
    if not p["new"]:
        db.execute("UPDATE ZWACHATSESSION SET Z_OPT = coalesce(Z_OPT,1) + 1 WHERE Z_PK=?", (spk,))
    touched_sessions.append(spk)

for ent in (ENT_SESSION, ENT_GROUPINFO, ENT_MEMBER, ENT_MESSAGE):
    db.execute("UPDATE Z_PRIMARYKEY SET Z_MAX=? WHERE Z_ENT=?", (next_pk[ent], ent))

# --------------------------------------------------------------------------
# 5. Verify before committing. Any failure discards the output.
# --------------------------------------------------------------------------
problems = []


def check(label, sql, want=0):
    got = db.execute(sql).fetchone()[0]
    if got != want:
        problems.append(f"{label}: expected {want}, found {got}")


check("messages pointing at a missing chat",
      "SELECT count(*) FROM ZWAMESSAGE m WHERE ZCHATSESSION IS NOT NULL AND NOT EXISTS (SELECT 1 FROM ZWACHATSESSION s WHERE s.Z_PK = m.ZCHATSESSION)",
      db.execute("SELECT count(*) FROM ZWAMESSAGE m WHERE Z_PK <= ? AND ZCHATSESSION IS NOT NULL AND NOT EXISTS (SELECT 1 FROM ZWACHATSESSION s WHERE s.Z_PK = m.ZCHATSESSION)", (zmax.get(ENT_MESSAGE) or 0,)).fetchone()[0])
check("added messages pointing at a missing or foreign group sender",
      f"""SELECT count(*) FROM ZWAMESSAGE m WHERE m.Z_PK > {zmax.get(ENT_MESSAGE) or 0} AND m.ZGROUPMEMBER IS NOT NULL
          AND NOT EXISTS (SELECT 1 FROM ZWAGROUPMEMBER g WHERE g.Z_PK = m.ZGROUPMEMBER AND g.ZCHATSESSION = m.ZCHATSESSION)""")
if touched_sessions:
    marks = ",".join(str(s) for s in touched_sessions)
    check("duplicate sort positions inside a merged chat",
          f"""SELECT count(*) FROM (SELECT ZCHATSESSION, ZSORT FROM ZWAMESSAGE
              WHERE ZCHATSESSION IN ({marks}) GROUP BY 1,2 HAVING count(*) > 1)""")
    check("merged chats whose counter is not past the last message",
          f"""SELECT count(*) FROM ZWACHATSESSION s WHERE s.Z_PK IN ({marks})
              AND s.ZMESSAGECOUNTER <= (SELECT max(ZSORT) FROM ZWAMESSAGE m WHERE m.ZCHATSESSION = s.Z_PK)""")
    check("duplicate message ids inside a merged chat (new duplicates only)",
          f"""SELECT count(*) FROM (SELECT ZCHATSESSION, ZSTANZAID FROM ZWAMESSAGE
              WHERE ZCHATSESSION IN ({marks}) AND ZSTANZAID IS NOT NULL
              GROUP BY 1,2 HAVING count(*) > 1 AND max(Z_PK) > {zmax.get(ENT_MESSAGE) or 0})""")
check("chat previews pointing at a missing message",
      "SELECT count(*) FROM ZWACHATSESSION s WHERE ZLASTMESSAGE IS NOT NULL AND NOT EXISTS (SELECT 1 FROM ZWAMESSAGE m WHERE m.Z_PK = s.ZLASTMESSAGE)",
      0)
check("chats with more than one preview message",
      "SELECT count(*) FROM (SELECT ZLASTSESSION FROM ZWAMESSAGE WHERE ZLASTSESSION IS NOT NULL GROUP BY 1 HAVING count(*) > 1)")
check("duplicate chats for one address",
      "SELECT count(*) FROM (SELECT ZCONTACTJID FROM ZWACHATSESSION WHERE ZCONTACTJID IS NOT NULL GROUP BY 1 HAVING count(*) > 1)",
      db.execute("SELECT count(*) FROM (SELECT ZCONTACTJID FROM ZWACHATSESSION WHERE ZCONTACTJID IS NOT NULL AND Z_PK <= ? GROUP BY 1 HAVING count(*) > 1)", (zmax.get(ENT_SESSION) or 0,)).fetchone()[0])
for ent, table in ((ENT_SESSION, "ZWACHATSESSION"), (ENT_GROUPINFO, "ZWAGROUPINFO"),
                   (ENT_MEMBER, "ZWAGROUPMEMBER"), (ENT_MESSAGE, "ZWAMESSAGE")):
    check(f"row counter behind the real rows in {table}",
          f"SELECT (SELECT coalesce(max(Z_PK),0) FROM {table}) > (SELECT Z_MAX FROM Z_PRIMARYKEY WHERE Z_ENT={ent})")

after = {t: db.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in before}
if after["ZWAMESSAGE"] != before["ZWAMESSAGE"] + stats["messages added"]:
    problems.append("message total does not equal original + added")
if after["ZWAMEDIAITEM"] != before["ZWAMEDIAITEM"]:
    problems.append("media rows changed (they must not in this stage)")
orig_now = db.execute(
    "SELECT count(*), total(Z_PK), total(length(ZTEXT)), total(ZMESSAGEDATE) FROM ZWAMESSAGE WHERE Z_PK <= ?",
    (zmax.get(ENT_MESSAGE) or 0,)).fetchone()
if tuple(orig_now) != tuple(before_fingerprint):
    problems.append("the iPhone's original messages were altered")

if problems:
    db.execute("ROLLBACK")
    db.close()
    remove(WORK)
    out("MERGE REJECTED. Nothing was kept. Problems found:")
    for pr in problems:
        out("  - " + pr)
    sys.exit(1)

db.execute("COMMIT")
integrity = db.execute("PRAGMA integrity_check").fetchone()[0]
if ORIG_JOURNAL == "wal":
    db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
db.close()
adb.close()
unwritten = os.path.exists(WORK + "-wal") and os.path.getsize(WORK + "-wal") > 0
if integrity != "ok" or unwritten:
    remove(WORK)
    out("MERGE REJECTED. Nothing was kept. Problems found:")
    out(f"  - integrity check: {integrity}" if integrity != "ok" else
        "  - changes were left in a -wal file instead of the database itself")
    sys.exit(1)
for suffix in ("-wal", "-shm"):
    if os.path.exists(WORK + suffix):
        os.remove(WORK + suffix)
os.replace(WORK, OUT)

# --------------------------------------------------------------------------
# 6. Report (counts only).
# --------------------------------------------------------------------------
out("Stage 1 merge finished")
out("=" * 60)
out(f"integrity check: {integrity}")
out(f"leftover -wal / -shm files next to the output: "
    f"{[s for s in ('-wal', '-shm') if os.path.exists(OUT + s)] or 'none'}")
out()
out(f"{'':34}{'before':>10}{'after':>10}")
for t, label in (("ZWAMESSAGE", "messages"), ("ZWACHATSESSION", "chats"),
                 ("ZWAGROUPINFO", "groups"), ("ZWAGROUPMEMBER", "group senders"),
                 ("ZWAMEDIAITEM", "media records (untouched)")):
    out(f"{label:34}{before[t]:>10}{after[t]:>10}")
out()
for k in ("android text messages read", "messages added", "  of which starred",
          "skipped: already on the iPhone", "skipped: duplicate inside the Android history",
          "skipped: not an ordinary chat or group (channels, status, broadcast)",
          "skipped: no message id or timestamp", "existing iPhone chats extended",
          "1:1 chats created", "groups created", "  of which hidden on Android (kept hidden)",
          "  of which archived on Android (kept archived)", "group senders added"):
    out(f"{k:68}{stats[k]:>8}")
out()
out("Android messages left for later stages, by type code:")
for mtype, n in sorted(skipped_types.items(), key=lambda kv: -kv[1]):
    out(f"   type {str(mtype):<6}{n:>8}")
out()
out("Hidden-id <-> phone-number links used to keep one chat per person:")
out(f"   Android's own table: {ANDROID_LINKS}")
for note in MAP_NOTES:
    out("   " + note)
out()
out("iPhone database merged into: " + os.path.abspath(IOS).replace(os.path.expanduser("~"), "~"))
_c = sqlite3.connect(f"file:{os.path.abspath(OUT)}?mode=ro&immutable=1", uri=True)
r = _c.execute(
    "SELECT datetime(min(ZMESSAGEDATE)+978307200,'unixepoch','localtime'), "
    "datetime(max(ZMESSAGEDATE)+978307200,'unixepoch','localtime') FROM ZWAMESSAGE WHERE Z_PK <= ?",
    (zmax.get(ENT_MESSAGE) or 0,)).fetchone()
_c.close()
out(f"   its own messages run from {r[0]} to {r[1]}")
out()
out("Conventions copied from the iPhone's own text messages:")
for (st, fm), tpl in sorted(MSG_TPL.items()):
    out(f"   {'group' if st else '1:1  '} {'sent    ' if fm else 'received'}  " +
        "  ".join(f"{k[1:].lower()}={v}" for k, v in tpl.items()))
out()
out(f"Merged database: {OUT}")
with open(REPORT, "w") as f:
    f.write("\n".join(lines) + "\n")
print(f"Report saved to {REPORT}")
