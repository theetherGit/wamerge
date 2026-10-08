#!/usr/bin/env python3
"""
Read-only profile of the Android (msgstore.db) and iPhone (ChatStorage.sqlite)
WhatsApp databases.

It prints aggregates only: counts, type codes, status codes and JID *servers*
(the part after @). No message text, names or phone numbers are printed.
Nothing is written to either database.

Run from your working folder:

    wamerge profile

Optional: wamerge profile <msgstore.db> <ChatStorage.sqlite> <output.txt>
"""
import os
import re
import sqlite3
import sys
from collections import Counter

AND = sys.argv[1] if len(sys.argv) > 1 else "android-decrypted/msgstore.db"
IOS = sys.argv[2] if len(sys.argv) > 2 else "ios-copy/ChatStorage.sqlite"
OUT = sys.argv[3] if len(sys.argv) > 3 else "output/profile.txt"

APPLE_EPOCH = 978307200
lines = []


def out(s=""):
    print(s)
    lines.append(s)


def section(title):
    out()
    out("=" * 72)
    out(title)
    out("=" * 72)


def fmt(v):
    if v is None:
        return "NULL"
    if isinstance(v, float):
        return f"{v:.3f}"
    return str(v)


def table(db, title, sql, headers, params=()):
    out()
    out(f"-- {title}")
    try:
        rows = db.execute(sql, params).fetchall()
    except sqlite3.Error as e:
        out(f"   (query failed: {e})")
        return []
    data = [[fmt(c) for c in r] for r in rows]
    widths = [len(h) for h in headers]
    for r in data:
        for i, c in enumerate(r):
            widths[i] = max(widths[i], len(c))
    out("   " + "  ".join(h.ljust(widths[i]) for i, h in enumerate(headers)))
    for r in data:
        out("   " + "  ".join(c.ljust(widths[i]) for i, c in enumerate(r)))
    if not data:
        out("   (no rows)")
    return rows


def server(col):
    """SQL expression reducing a JID to its server part, hiding the number."""
    return (
        f"CASE WHEN {col} IS NULL THEN 'NULL' "
        f"WHEN instr({col},'@')=0 THEN 'no-@' "
        f"ELSE substr({col}, instr({col},'@')) END"
    )


def mask(s):
    if s is None:
        return "NULL"
    s = re.sub(r"[0-9]", "9", str(s))
    s = re.sub(r"[A-Za-z]", "a", s)
    s = re.sub(r"9{3,}", "9..", s)
    s = re.sub(r"a{3,}", "a..", s)
    return s[:70]


for p in (AND, IOS):
    if not os.path.exists(p):
        sys.exit(f"Not found: {p}  (run this from your working folder)")

# Open with URI support so both databases are attached strictly read-only.
db = sqlite3.connect("file::memory:", uri=True)
db.execute(f"ATTACH DATABASE 'file:{os.path.abspath(AND)}?mode=ro' AS a")
db.execute(f"ATTACH DATABASE 'file:{os.path.abspath(IOS)}?mode=ro' AS i")

# ---------------------------------------------------------------------------
section("A. IPHONE: how ChatStorage.sqlite stores things")

table(db, "A1 messages by ZMESSAGETYPE",
      "SELECT ZMESSAGETYPE, count(*) FROM i.ZWAMESSAGE GROUP BY 1 ORDER BY 2 DESC",
      ["type", "count"])

table(db, "A2 messages by from_me and ZMESSAGESTATUS",
      "SELECT ZISFROMME, ZMESSAGESTATUS, count(*) FROM i.ZWAMESSAGE GROUP BY 1,2 ORDER BY 1,3 DESC",
      ["from_me", "status", "count"])

for col in ("ZFLAGS", "ZDATAITEMVERSION", "ZSPOTLIGHTSTATUS", "Z_ENT", "Z_OPT",
            "ZGROUPEVENTTYPE", "ZMESSAGEERRORSTATUS", "ZSTARRED", "ZENCRETRYCOUNT",
            "ZFILTEREDRECIPIENTCOUNT", "ZCHILDMESSAGESDELIVEREDCOUNT"):
    table(db, f"A3 top values of {col}",
          f"SELECT {col}, count(*) FROM i.ZWAMESSAGE GROUP BY 1 ORDER BY 2 DESC LIMIT 12",
          [col, "count"])

nullable = ["ZFROMJID", "ZTOJID", "ZGROUPMEMBER", "ZPUSHNAME", "ZMEDIAITEM", "ZMESSAGEINFO",
            "ZPHASH", "ZSENTDATE", "ZDOCID", "ZMEDIASECTIONID", "ZLASTSESSION",
            "ZPARENTMESSAGE", "ZTEXT", "ZSORT"]
sel = ", ".join(f"sum({c} IS NOT NULL)" for c in nullable)
table(db, "A4 how many rows have each column filled, by chat type / from_me",
      f"""SELECT s.ZSESSIONTYPE, m.ZISFROMME, count(*), {sel}
          FROM i.ZWAMESSAGE m LEFT JOIN i.ZWACHATSESSION s ON s.Z_PK = m.ZCHATSESSION
          GROUP BY 1,2 ORDER BY 1,2""",
      ["sesstype", "from_me", "rows"] + [c[1:].lower() for c in nullable])

# A5 ZSORT conventions
out()
out("-- A5 ZSORT conventions")
try:
    rows = db.execute(
        """SELECT m.ZCHATSESSION, count(*), min(m.ZSORT), max(m.ZSORT),
                  count(DISTINCT m.ZSORT), s.ZMESSAGECOUNTER
           FROM i.ZWAMESSAGE m LEFT JOIN i.ZWACHATSESSION s ON s.Z_PK = m.ZCHATSESSION
           GROUP BY 1""").fetchall()
    n = len(rows)
    out(f"   chats with messages: {n}")
    out(f"   chats where max(ZSORT) == ZMESSAGECOUNTER: {sum(1 for r in rows if r[3] == r[5])}")
    out(f"   chats where max(ZSORT) <= ZMESSAGECOUNTER: {sum(1 for r in rows if r[5] is not None and r[3] is not None and r[3] <= r[5])}")
    out(f"   chats where min(ZSORT) == 1: {sum(1 for r in rows if r[2] == 1)}")
    out(f"   chats where min(ZSORT) == 0: {sum(1 for r in rows if r[2] == 0)}")
    out(f"   chats where ZSORT unique within chat: {sum(1 for r in rows if r[1] == r[4])}")
    out(f"   chats where count == max(ZSORT) - min(ZSORT) + 1: {sum(1 for r in rows if r[2] is not None and r[1] == r[3] - r[2] + 1)}")
    g = db.execute("SELECT count(*), count(DISTINCT ZSORT), min(ZSORT), max(ZSORT), typeof(max(ZSORT)) FROM i.ZWAMESSAGE").fetchone()
    out(f"   global: rows={g[0]} distinct ZSORT={g[1]} min={fmt(g[2])} max={fmt(g[3])} type={g[4]}")
    good = bad = 0
    prev_chat, prev_date = None, None
    for chat, sort, date in db.execute(
            "SELECT ZCHATSESSION, ZSORT, ZMESSAGEDATE FROM i.ZWAMESSAGE ORDER BY ZCHATSESSION, ZSORT, Z_PK"):
        if chat == prev_chat and date is not None and prev_date is not None:
            if date >= prev_date:
                good += 1
            else:
                bad += 1
        prev_chat, prev_date = chat, date
    out(f"   neighbours (by ZSORT within a chat) in date order: {good}, out of date order: {bad}")
    for r in sorted(rows, key=lambda r: -r[1])[:5]:
        out(f"   sample big chat: rows={r[1]} minsort={fmt(r[2])} maxsort={fmt(r[3])} distinct={r[4]} counter={fmt(r[5])}")
except sqlite3.Error as e:
    out(f"   (failed: {e})")

table(db, "A6 ZDOCID vs Z_PK",
      """SELECT count(*), min(Z_PK), max(Z_PK), min(ZDOCID), max(ZDOCID),
                count(DISTINCT ZDOCID), sum(ZDOCID = Z_PK), sum(ZDOCID IS NULL), sum(ZDOCID = 0)
         FROM i.ZWAMESSAGE""",
      ["rows", "min_pk", "max_pk", "min_docid", "max_docid", "distinct_docid", "docid=pk", "docid_null", "docid_0"])

table(db, "A7 chat sessions by type and JID server",
      f"""SELECT ZSESSIONTYPE, {server('ZCONTACTJID')}, count(*), sum(ZREMOVED=1), sum(ZHIDDEN=1),
                 sum(ZARCHIVED=1), sum(ZGROUPINFO IS NOT NULL), sum(ZLASTMESSAGE IS NOT NULL),
                 sum(ZCONTACTIDENTIFIER IS NOT NULL), sum(ZPROPERTIES IS NOT NULL)
          FROM i.ZWACHATSESSION GROUP BY 1,2 ORDER BY 3 DESC""",
      ["sesstype", "server", "chats", "removed", "hidden", "archived", "groupinfo", "lastmsg", "contactid", "props"])

for col in ("ZFLAGS", "Z_ENT", "Z_OPT", "ZSPOTLIGHTSTATUS", "ZIDENTITYVERIFICATIONSTATE", "ZCONTACTABID"):
    table(db, f"A7b chat session top values of {col}",
          f"SELECT {col}, count(*) FROM i.ZWACHATSESSION GROUP BY 1 ORDER BY 2 DESC LIMIT 8",
          [col, "count"])

table(db, "A8 ZFROMJID / ZTOJID servers by from_me",
      f"""SELECT ZISFROMME, {server('ZFROMJID')}, {server('ZTOJID')}, count(*)
          FROM i.ZWAMESSAGE GROUP BY 1,2,3 ORDER BY 4 DESC LIMIT 20""",
      ["from_me", "fromjid", "tojid", "count"])

out()
out("-- A9 shape of ZMEDIASECTIONID, ZPHASH, ZSTANZAID (digits->9, letters->a)")
for col in ("ZMEDIASECTIONID", "ZPHASH", "ZSTANZAID"):
    try:
        c = Counter(mask(r[0]) for r in db.execute(
            f"SELECT {col} FROM i.ZWAMESSAGE WHERE {col} IS NOT NULL LIMIT 20000"))
        for pat, n in c.most_common(5):
            out(f"   {col}: {pat}  x{n}")
    except sqlite3.Error as e:
        out(f"   {col}: (failed: {e})")

out()
out("-- A10 Z_PRIMARYKEY counters vs real max Z_PK")
try:
    for ent, name, zmax in db.execute("SELECT Z_ENT, Z_NAME, Z_MAX FROM i.Z_PRIMARYKEY ORDER BY Z_ENT"):
        t = "Z" + name.upper()
        try:
            cnt, mx = db.execute(f"SELECT count(*), max(Z_PK) FROM i.{t}").fetchone()
            ents = [r[0] for r in db.execute(f"SELECT DISTINCT Z_ENT FROM i.{t} LIMIT 5")]
            out(f"   ent={ent} {name}: Z_MAX={zmax} rows={cnt} max_pk={fmt(mx)} row Z_ENT values={ents}")
        except sqlite3.Error as e:
            out(f"   ent={ent} {name}: (table {t} not readable: {e})")
except sqlite3.Error as e:
    out(f"   (failed: {e})")

table(db, "A11 group members per group (summary)",
      """SELECT count(*), min(n), max(n), sum(n) FROM
         (SELECT ZCHATSESSION, count(*) n FROM i.ZWAGROUPMEMBER GROUP BY 1)""",
      ["groups", "min_members", "max_members", "total_member_rows"])
table(db, "A11b group member flags",
      f"""SELECT {server('ZMEMBERJID')}, ZISACTIVE, ZISADMIN, sum(ZCONTACTNAME IS NOT NULL), count(*)
          FROM i.ZWAGROUPMEMBER GROUP BY 1,2,3 ORDER BY 5 DESC LIMIT 12""",
      ["server", "active", "admin", "has_name", "count"])

table(db, "A12 media items",
      """SELECT count(*), sum(ZMEDIALOCALPATH IS NOT NULL), sum(ZMEDIAURL IS NOT NULL),
                sum(ZXMPPTHUMBPATH IS NOT NULL), sum(ZMETADATA IS NOT NULL), sum(ZMEDIAKEY IS NOT NULL)
         FROM i.ZWAMEDIAITEM""",
      ["rows", "localpath", "url", "thumbpath", "metadata", "mediakey"])
out()
out("-- A12b shape of ZMEDIALOCALPATH / ZXMPPTHUMBPATH")
for col in ("ZMEDIALOCALPATH", "ZXMPPTHUMBPATH"):
    try:
        c = Counter(mask(r[0]) for r in db.execute(
            f"SELECT {col} FROM i.ZWAMEDIAITEM WHERE {col} IS NOT NULL LIMIT 20000"))
        for pat, n in c.most_common(6):
            out(f"   {col}: {pat}  x{n}")
    except sqlite3.Error as e:
        out(f"   {col}: (failed: {e})")

out()
out("-- A13 database health")
for label, sql in (("journal_mode", "PRAGMA i.journal_mode"), ("user_version", "PRAGMA i.user_version"),
                   ("page_size", "PRAGMA i.page_size"), ("quick_check", "PRAGMA i.quick_check")):
    try:
        out(f"   {label}: {db.execute(sql).fetchone()[0]}")
    except sqlite3.Error as e:
        out(f"   {label}: (failed: {e})")
try:
    v = db.execute("SELECT Z_VERSION, Z_UUID, length(Z_PLIST) FROM i.Z_METADATA").fetchone()
    out("   Z_METADATA: (empty)" if v is None else f"   Z_METADATA: version={v[0]} uuid_len={len(v[1] or '')} plist_bytes={v[2]}")
except sqlite3.Error as e:
    out(f"   Z_METADATA: (failed: {e})")
try:
    trg = db.execute("SELECT count(*) FROM i.sqlite_master WHERE type='trigger'").fetchone()[0]
    out(f"   triggers: {trg}")
except sqlite3.Error as e:
    out(f"   triggers: (failed: {e})")

# ---------------------------------------------------------------------------
section("B. ANDROID: what msgstore.db contains")

table(db, "B1 messages by message_type",
      """SELECT message_type, count(*), sum(text_data IS NOT NULL AND text_data <> '')
         FROM a.message GROUP BY 1 ORDER BY 2 DESC""",
      ["type", "count", "with_text"])

table(db, "B2 messages by from_me and status",
      "SELECT from_me, status, count(*) FROM a.message GROUP BY 1,2 ORDER BY 1,3 DESC",
      ["from_me", "status", "count"])

table(db, "B3 chats and their messages by JID server",
      f"""SELECT {server('j.raw_string')}, count(DISTINCT c._id), count(m._id)
          FROM a.chat c LEFT JOIN a.jid j ON j._id = c.jid_row_id
          LEFT JOIN a.message m ON m.chat_row_id = c._id
          GROUP BY 1 ORDER BY 3 DESC""",
      ["server", "chats", "messages"])

table(db, "B4 lid mapping available",
      "SELECT (SELECT count(*) FROM a.jid_map), (SELECT count(*) FROM a.jid WHERE server='lid')",
      ["jid_map_rows", "lid_jids"])

table(db, "B5 system message action types",
      "SELECT action_type, count(*) FROM a.message_system GROUP BY 1 ORDER BY 2 DESC LIMIT 25",
      ["action_type", "count"])

out()
out("-- B6 side tables")
for t, extra in (("message_quoted", ""), ("message_media", ""),
                 ("message_media", "WHERE file_path IS NOT NULL"),
                 ("message_media", "WHERE transferred = 1"),
                 ("message_add_on", ""), ("message_add_on_reaction", ""),
                 ("message_edit_info", ""), ("message_revoked", ""), ("message_forwarded", ""),
                 ("message_mentions", ""), ("message_location", ""), ("message_vcard", ""),
                 ("message_poll", ""), ("message_link", ""), ("message_text", ""),
                 ("message_thumbnail", ""), ("receipt_user", ""), ("group_participant_user", ""),
                 ("call_log", ""), ("message", "WHERE starred = 1")):
    try:
        n = db.execute(f"SELECT count(*) FROM a.{t} {extra}").fetchone()[0]
        out(f"   {t} {extra}: {n}")
    except sqlite3.Error as e:
        out(f"   {t} {extra}: (failed: {e})")

table(db, "B7 message_add_on by type",
      "SELECT message_add_on_type, count(*) FROM a.message_add_on GROUP BY 1 ORDER BY 2 DESC",
      ["add_on_type", "count"])

table(db, "B8 duplicate key_ids in Android",
      """SELECT count(*), sum(n) FROM (SELECT key_id, count(*) n FROM a.message GROUP BY 1 HAVING n > 1)""",
      ["dup_key_ids", "rows_involved"])

table(db, "B9 sender filled, by chat server / from_me",
      f"""SELECT {server('j.raw_string')}, m.from_me, count(*),
                 sum(m.sender_jid_row_id IS NOT NULL AND m.sender_jid_row_id > 0)
          FROM a.message m JOIN a.chat c ON c._id = m.chat_row_id
          LEFT JOIN a.jid j ON j._id = c.jid_row_id
          GROUP BY 1,2 ORDER BY 3 DESC LIMIT 14""",
      ["server", "from_me", "rows", "with_sender"])

table(db, "B10 sender JID servers in groups",
      f"""SELECT {server('sj.raw_string')}, count(*)
          FROM a.message m JOIN a.jid sj ON sj._id = m.sender_jid_row_id
          GROUP BY 1 ORDER BY 2 DESC""",
      ["sender_server", "count"])

table(db, "B11 media files referenced, by top folder",
      """SELECT CASE WHEN instr(file_path,'/')=0 THEN '(flat)' ELSE substr(file_path,1,instr(file_path,'/')-1) END,
                count(*), sum(file_size)
         FROM a.message_media WHERE file_path IS NOT NULL GROUP BY 1 ORDER BY 2 DESC LIMIT 8""",
      ["prefix", "files", "bytes"])
out()
out("-- B11b shape of message_media.file_path")
try:
    c = Counter(mask(r[0]) for r in db.execute(
        "SELECT file_path FROM a.message_media WHERE file_path IS NOT NULL LIMIT 20000"))
    for pat, n in c.most_common(8):
        out(f"   {pat}  x{n}")
except sqlite3.Error as e:
    out(f"   (failed: {e})")

# ---------------------------------------------------------------------------
section("C. OVERLAP: the same message as stored on each side")

try:
    db.execute("""CREATE TEMP TABLE ov AS
                  SELECT m._id AS aid, z.Z_PK AS ipk
                  FROM a.message m JOIN i.ZWAMESSAGE z
                    ON z.ZSTANZAID = m.key_id AND z.ZISFROMME = m.from_me""")
    db.execute("CREATE INDEX temp.ov_a ON ov(aid)")
    db.execute("CREATE INDEX temp.ov_i ON ov(ipk)")
    ok = True
except sqlite3.Error as e:
    out(f"(could not build overlap: {e})")
    ok = False

if ok:
    J = """FROM ov JOIN a.message m ON m._id = ov.aid
           JOIN i.ZWAMESSAGE z ON z.Z_PK = ov.ipk
           JOIN a.chat c ON c._id = m.chat_row_id
           LEFT JOIN a.jid cj ON cj._id = c.jid_row_id
           LEFT JOIN i.ZWACHATSESSION s ON s.Z_PK = z.ZCHATSESSION"""

    table(db, "C0 pairs matched on message id + from_me",
          "SELECT count(*), count(DISTINCT aid), count(DISTINCT ipk) FROM ov",
          ["pairs", "distinct_android", "distinct_iphone"])

    table(db, "C1 Android message_type -> iPhone ZMESSAGETYPE",
          f"SELECT m.message_type, z.ZMESSAGETYPE, count(*) {J} GROUP BY 1,2 ORDER BY 1,3 DESC",
          ["android_type", "iphone_type", "count"])

    table(db, "C2 Android status -> iPhone ZMESSAGESTATUS, by from_me",
          f"SELECT m.from_me, m.status, z.ZMESSAGESTATUS, count(*) {J} GROUP BY 1,2,3 ORDER BY 1,2,4 DESC",
          ["from_me", "android_status", "iphone_status", "count"])

    table(db, "C3 timestamp agreement (iPhone date + 978307200 vs Android ms/1000)",
          f"""SELECT CASE WHEN d < 1 THEN 'within 1s' WHEN d < 2 THEN 'within 2s'
                          WHEN d < 60 THEN 'within 60s' ELSE 'more' END, count(*),
                     sum(isint)
              FROM (SELECT abs(z.ZMESSAGEDATE + {APPLE_EPOCH} - m.timestamp/1000.0) d,
                           (z.ZMESSAGEDATE = CAST(z.ZMESSAGEDATE AS INTEGER)) isint {J})
              GROUP BY 1 ORDER BY 2 DESC""",
          ["difference", "count", "iphone_date_is_whole_seconds"])

    table(db, "C3b iPhone ZSENTDATE vs ZMESSAGEDATE in the overlap",
          f"""SELECT m.from_me, sum(z.ZSENTDATE IS NULL), sum(z.ZSENTDATE = z.ZMESSAGEDATE),
                     sum(z.ZSENTDATE IS NOT NULL AND z.ZSENTDATE <> z.ZMESSAGEDATE), count(*)
              {J} GROUP BY 1""",
          ["from_me", "sent_null", "sent=date", "sent<>date", "rows"])

    table(db, "C4 chat JID: Android vs iPhone",
          f"""SELECT {server('cj.raw_string')}, {server('s.ZCONTACTJID')},
                     sum(cj.raw_string = s.ZCONTACTJID),
                     sum(EXISTS (SELECT 1 FROM a.jid_map jm JOIN a.jid pj ON pj._id = jm.jid_row_id
                                 WHERE jm.lid_row_id = c.jid_row_id AND pj.raw_string = s.ZCONTACTJID)),
                     count(*)
              {J} GROUP BY 1,2 ORDER BY 5 DESC""",
          ["android_server", "iphone_server", "identical", "same_via_jid_map", "count"])

    table(db, "C5 incoming: what iPhone ZFROMJID / ZTOJID hold",
          f"""SELECT s.ZSESSIONTYPE,
                     sum(z.ZFROMJID = s.ZCONTACTJID), sum(z.ZFROMJID IS NULL),
                     sum(z.ZTOJID IS NULL), sum(z.ZGROUPMEMBER IS NOT NULL),
                     sum(z.ZPUSHNAME IS NOT NULL), count(*)
              {J} WHERE m.from_me = 0 GROUP BY 1""",
          ["sesstype", "from=chatjid", "from_null", "to_null", "has_groupmember", "has_pushname", "rows"])

    table(db, "C6 outgoing: what iPhone ZFROMJID / ZTOJID hold",
          f"""SELECT s.ZSESSIONTYPE,
                     sum(z.ZTOJID = s.ZCONTACTJID), sum(z.ZTOJID IS NULL),
                     sum(z.ZFROMJID IS NULL), sum(z.ZMESSAGEINFO IS NOT NULL), count(*)
              {J} WHERE m.from_me = 1 GROUP BY 1""",
          ["sesstype", "to=chatjid", "to_null", "from_null", "has_msginfo", "rows"])

    table(db, "C7 group sender: Android sender JID vs iPhone group member JID",
          f"""SELECT {server('sj.raw_string')}, {server('gm.ZMEMBERJID')},
                     sum(sj.raw_string = gm.ZMEMBERJID),
                     sum(EXISTS (SELECT 1 FROM a.jid_map jm JOIN a.jid pj ON pj._id = jm.jid_row_id
                                 WHERE jm.lid_row_id = m.sender_jid_row_id AND pj.raw_string = gm.ZMEMBERJID)),
                     sum(gm.ZCHATSESSION = z.ZCHATSESSION), count(*)
              {J} LEFT JOIN a.jid sj ON sj._id = m.sender_jid_row_id
                  LEFT JOIN i.ZWAGROUPMEMBER gm ON gm.Z_PK = z.ZGROUPMEMBER
              WHERE m.from_me = 0 AND s.ZSESSIONTYPE = 1
              GROUP BY 1,2 ORDER BY 6 DESC""",
          ["android_sender", "iphone_member", "identical", "same_via_jid_map", "member_in_same_chat", "count"])

    table(db, "C8 text agreement",
          f"""SELECT m.message_type, sum(m.text_data = z.ZTEXT),
                     sum(m.text_data IS NULL AND z.ZTEXT IS NULL),
                     sum(m.text_data IS NOT NULL AND z.ZTEXT IS NULL),
                     sum(m.text_data IS NULL AND z.ZTEXT IS NOT NULL),
                     sum(m.text_data IS NOT NULL AND z.ZTEXT IS NOT NULL AND m.text_data <> z.ZTEXT),
                     count(*)
              {J} GROUP BY 1 ORDER BY 7 DESC""",
          ["android_type", "equal", "both_null", "only_android", "only_iphone", "differ", "rows"])

    table(db, "C9 iPhone ZFLAGS / ZDATAITEMVERSION / ZSPOTLIGHTSTATUS by Android type and from_me",
          f"""SELECT m.message_type, m.from_me, z.ZFLAGS, z.ZDATAITEMVERSION, z.ZSPOTLIGHTSTATUS, count(*)
              {J} GROUP BY 1,2,3,4,5 ORDER BY 6 DESC LIMIT 40""",
          ["android_type", "from_me", "zflags", "dataitemver", "spotlight", "count"])

    table(db, "C10 starred agreement",
          f"SELECT m.starred, z.ZSTARRED, count(*) {J} GROUP BY 1,2 ORDER BY 3 DESC",
          ["android_starred", "iphone_starred", "count"])

    table(db, "C11 media in the overlap: does the iPhone row have a media item / local file",
          f"""SELECT m.message_type, count(*), sum(z.ZMEDIAITEM IS NOT NULL),
                     sum(mi.ZMEDIALOCALPATH IS NOT NULL), sum(mm.file_path IS NOT NULL),
                     sum(mi.ZFILESIZE = mm.file_size), sum(mi.ZTITLE IS NOT NULL),
                     sum(mi.ZMETADATA IS NOT NULL)
              {J} LEFT JOIN i.ZWAMEDIAITEM mi ON mi.Z_PK = z.ZMEDIAITEM
                  LEFT JOIN a.message_media mm ON mm.message_row_id = m._id
              GROUP BY 1 ORDER BY 2 DESC""",
          ["android_type", "rows", "iphone_mediaitem", "iphone_localpath", "android_filepath",
           "size_equal", "iphone_title", "iphone_metadata"])

    table(db, "C12 quoted replies in the overlap",
          f"""SELECT sum(q.message_row_id IS NOT NULL), sum(z.ZPARENTMESSAGE IS NOT NULL),
                     sum(q.message_row_id IS NOT NULL AND z.ZPARENTMESSAGE IS NOT NULL),
                     sum(q.message_row_id IS NOT NULL AND z.ZMEDIAITEM IS NOT NULL), count(*)
              {J} LEFT JOIN a.message_quoted q ON q.message_row_id = m._id""",
          ["android_quoted", "iphone_parent", "both", "quoted_with_mediaitem", "rows"])

    # ordering agreement
    out()
    out("-- C13 does Android order agree with iPhone ZSORT inside a chat")
    try:
        good = bad = 0
        prev_chat, prev_sort = None, None
        for chat, asort, isort in db.execute(
                f"SELECT z.ZCHATSESSION, m.sort_id, z.ZSORT {J} ORDER BY z.ZCHATSESSION, m.sort_id"):
            if chat == prev_chat and isort is not None and prev_sort is not None:
                if isort >= prev_sort:
                    good += 1
                else:
                    bad += 1
            prev_chat, prev_sort = chat, isort
        out(f"   neighbours in the same order: {good}, in a different order: {bad}")
    except sqlite3.Error as e:
        out(f"   (failed: {e})")

# ---------------------------------------------------------------------------
section("D. WHAT THE MERGE WOULD ADD")

try:
    ios_jids = {r[0] for r in db.execute("SELECT ZCONTACTJID FROM i.ZWACHATSESSION WHERE ZCONTACTJID IS NOT NULL")}
    lidmap = dict(db.execute(
        """SELECT lj.raw_string, pj.raw_string FROM a.jid_map jm
           JOIN a.jid lj ON lj._id = jm.lid_row_id JOIN a.jid pj ON pj._id = jm.jid_row_id"""))
    have = Counter()
    new = Counter()
    have_msgs = Counter()
    new_msgs = Counter()
    for raw, n in db.execute(
            """SELECT j.raw_string, count(m._id) FROM a.chat c
               LEFT JOIN a.jid j ON j._id = c.jid_row_id
               LEFT JOIN a.message m ON m.chat_row_id = c._id
               GROUP BY c._id"""):
        srv = "NULL" if raw is None else (raw[raw.find("@"):] if "@" in raw else "no-@")
        if raw in ios_jids or lidmap.get(raw) in ios_jids:
            have[srv] += 1
            have_msgs[srv] += n
        else:
            new[srv] += 1
            new_msgs[srv] += n
    out()
    out("-- D1 Android chats by whether the iPhone already has that chat")
    out("   server                 on_iphone  msgs      not_on_iphone  msgs")
    for srv in sorted(set(have) | set(new), key=lambda s: -(have_msgs[s] + new_msgs[s])):
        out(f"   {srv:<22} {have[srv]:<10} {have_msgs[srv]:<9} {new[srv]:<14} {new_msgs[srv]}")
except sqlite3.Error as e:
    out(f"   (failed: {e})")

table(db, "D2 Android messages not on the iPhone, by type",
      """SELECT m.message_type, count(*) FROM a.message m
         WHERE NOT EXISTS (SELECT 1 FROM i.ZWAMESSAGE z WHERE z.ZSTANZAID = m.key_id AND z.ZISFROMME = m.from_me)
         GROUP BY 1 ORDER BY 2 DESC""",
      ["android_type", "to_add"])

os.makedirs(os.path.dirname(OUT) or ".", exist_ok=True)
with open(OUT, "w") as f:
    f.write("\n".join(lines) + "\n")
print(f"\nSaved to {OUT}")
