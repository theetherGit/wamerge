"""Builders for made-up WhatsApp databases and a made-up Finder backup.
Nothing here comes from a real phone: the tables hold only the columns the
tool reads, and every number, name and message is invented."""
import os
import plistlib
import sqlite3
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOMAIN = "AppDomainGroup-group.net.whatsapp.WhatsApp.shared"
APPLE_EPOCH = 978307200
BASE = 1700000000


def ms(s):
    return (BASE + s) * 1000


def apple(s):
    return float(BASE + s - APPLE_EPOCH)


ANDROID_DDL = """
CREATE TABLE jid (_id INTEGER PRIMARY KEY, user TEXT, server TEXT, agent INTEGER, device INTEGER, type INTEGER, raw_string TEXT);
CREATE TABLE jid_map (lid_row_id INTEGER PRIMARY KEY, jid_row_id INTEGER, sort_id INTEGER);
CREATE TABLE chat (_id INTEGER PRIMARY KEY, jid_row_id INTEGER, hidden INTEGER, subject TEXT, created_timestamp INTEGER, archived INTEGER);
CREATE TABLE message (_id INTEGER PRIMARY KEY, chat_row_id INTEGER, from_me INTEGER, key_id TEXT, sender_jid_row_id INTEGER,
    status INTEGER, timestamp INTEGER, received_timestamp INTEGER, message_type INTEGER, text_data TEXT, starred INTEGER, sort_id INTEGER);
CREATE TABLE message_media (message_row_id INTEGER PRIMARY KEY, chat_row_id INTEGER, file_path TEXT, file_size INTEGER);
"""

IOS_DDL = """
CREATE TABLE ZWACHATSESSION ( Z_PK INTEGER PRIMARY KEY, Z_ENT INTEGER, Z_OPT INTEGER, ZARCHIVED INTEGER, ZCONTACTABID INTEGER, ZFLAGS INTEGER, ZHIDDEN INTEGER, ZIDENTITYVERIFICATIONEPOCH INTEGER, ZIDENTITYVERIFICATIONSTATE INTEGER, ZMESSAGECOUNTER INTEGER, ZREMOVED INTEGER, ZSESSIONTYPE INTEGER, ZSPOTLIGHTSTATUS INTEGER, ZUNREADCOUNT INTEGER, ZGROUPINFO INTEGER, ZLASTMESSAGE INTEGER, ZPROPERTIES INTEGER, ZLASTMESSAGEDATE TIMESTAMP, ZLOCATIONSHARINGENDDATE TIMESTAMP, ZCONTACTIDENTIFIER VARCHAR, ZCONTACTJID VARCHAR, ZETAG VARCHAR, ZLASTMESSAGETEXT VARCHAR, ZPARTNERNAME VARCHAR, ZSAVEDINPUT VARCHAR );
CREATE TABLE ZWAGROUPINFO ( Z_PK INTEGER PRIMARY KEY, Z_ENT INTEGER, Z_OPT INTEGER, ZSTATE INTEGER, ZCHATSESSION INTEGER, ZLASTMESSAGEOWNER INTEGER, ZCREATIONDATE TIMESTAMP, ZSUBJECTTIMESTAMP TIMESTAMP, ZCREATORJID VARCHAR, ZOWNERJID VARCHAR, ZPICTUREID VARCHAR, ZPICTUREPATH VARCHAR, ZSOURCEJID VARCHAR, ZSUBJECTOWNERJID VARCHAR );
CREATE TABLE ZWAGROUPMEMBER ( Z_PK INTEGER PRIMARY KEY, Z_ENT INTEGER, Z_OPT INTEGER, ZCONTACTABID INTEGER, ZISACTIVE INTEGER, ZISADMIN INTEGER, ZSENDERKEYSENT INTEGER, ZCHATSESSION INTEGER, ZRECENTGROUPCHAT INTEGER, ZCONTACTIDENTIFIER VARCHAR, ZCONTACTNAME VARCHAR, ZFIRSTNAME VARCHAR, ZMEMBERJID VARCHAR );
CREATE TABLE ZWAMEDIAITEM ( Z_PK INTEGER PRIMARY KEY, Z_ENT INTEGER, Z_OPT INTEGER, ZMESSAGE INTEGER, ZFILESIZE INTEGER, ZMEDIALOCALPATH VARCHAR );
CREATE TABLE ZWAMESSAGE ( Z_PK INTEGER PRIMARY KEY, Z_ENT INTEGER, Z_OPT INTEGER, ZCHILDMESSAGESDELIVEREDCOUNT INTEGER, ZCHILDMESSAGESPLAYEDCOUNT INTEGER, ZCHILDMESSAGESREADCOUNT INTEGER, ZDATAITEMVERSION INTEGER, ZDOCID INTEGER, ZENCRETRYCOUNT INTEGER, ZFILTEREDRECIPIENTCOUNT INTEGER, ZFLAGS INTEGER, ZGROUPEVENTTYPE INTEGER, ZISFROMME INTEGER, ZMESSAGEERRORSTATUS INTEGER, ZMESSAGESTATUS INTEGER, ZMESSAGETYPE INTEGER, ZSORT INTEGER, ZSPOTLIGHTSTATUS INTEGER, ZSTARRED INTEGER, ZCHATSESSION INTEGER, ZGROUPMEMBER INTEGER, ZLASTSESSION INTEGER, ZMEDIAITEM INTEGER, ZMESSAGEINFO INTEGER, ZPARENTMESSAGE INTEGER, ZMESSAGEDATE TIMESTAMP, ZSENTDATE TIMESTAMP, ZFROMJID VARCHAR, ZMEDIASECTIONID VARCHAR, ZPHASH VARCHAR, ZPUSHNAME VARCHAR, ZSTANZAID VARCHAR, ZTEXT VARCHAR, ZTOJID VARCHAR );
CREATE TABLE Z_PRIMARYKEY (Z_ENT INTEGER PRIMARY KEY, Z_NAME VARCHAR, Z_SUPER INTEGER, Z_MAX INTEGER);
CREATE TABLE Z_METADATA (Z_VERSION INTEGER PRIMARY KEY, Z_UUID VARCHAR(255), Z_PLIST BLOB);
"""


def make_android(path, extra_messages=()):
    """An Android history covering every case the merge must handle."""
    a = sqlite3.connect(path)
    a.executescript(ANDROID_DDL)
    a.executescript("""
    INSERT INTO jid(_id,user,server,raw_string) VALUES
     (1,'911','s.whatsapp.net','911@s.whatsapp.net'),   -- chat already on the iPhone
     (2,'912','s.whatsapp.net','912@s.whatsapp.net'),   -- on the iPhone under hidden id 55
     (3,'55','lid','55@lid'),
     (4,'g1','g.us','g1@g.us'),                          -- group already on the iPhone
     (5,'g2','g.us','g2@g.us'),                          -- group only on Android
     (6,'913','s.whatsapp.net','913@s.whatsapp.net'),   -- person only on Android, two addresses
     (7,'66','lid','66@lid'),
     (8,'77','lid','77@lid'),                            -- group sender known to the iPhone
     (9,'914','s.whatsapp.net','914@s.whatsapp.net'),   -- same sender by phone number
     (10,'nl','newsletter','nl@newsletter'),
     (11,'915','s.whatsapp.net','915@s.whatsapp.net');
    INSERT INTO jid_map(lid_row_id,jid_row_id) VALUES (3,2),(7,6),(8,9);
    INSERT INTO chat(_id,jid_row_id,subject,created_timestamp,archived,hidden) VALUES
     (1,1,NULL,0,0,0),(2,2,NULL,0,0,0),(3,4,'G one',0,0,0),(4,5,'G two',1600000000000,1,0),
     (5,6,NULL,0,0,0),(6,7,NULL,0,0,0),(7,10,'News',0,0,0),(8,11,NULL,0,0,0);
    """)
    rows = [  # id, chat, from_me, key, sender, seconds, type, text, starred
        (1, 1, 0, "K1", 0, 10, 0, "old in", 0), (2, 1, 1, "K2", 0, 20, 0, "old out", 1),
        (3, 1, 0, "DUP", 0, 100, 0, "already", 0), (4, 1, 0, "K4", 0, 300, 0, "newer than iphone", 0),
        (5, 2, 1, "K5", 0, 15, 0, "to hidden-id person", 0),
        (6, 3, 0, "K6", 8, 5, 0, "group old from 77", 0), (7, 3, 0, "K7", 9, 6, 0, "group old from 914", 0),
        (8, 3, 1, "GDUP", 0, 50, 0, "sent here, received there", 0),
        (9, 4, 0, "K9", 1, 7, 0, "new group", 0), (10, 4, 1, "K10", 0, 8, 0, "new group out", 0),
        (11, 5, 0, "K11", 0, 30, 0, "new chat by number", 0), (12, 6, 0, "K12", 0, 29, 0, "new chat by hidden id", 0),
        (13, 6, 0, "K11", 0, 30, 0, "same message, other address", 0),
        (14, 7, 0, "K14", 0, 1, 0, "newsletter", 0), (15, 8, 0, "K15", 0, 1, 1, None, 0),
        (16, 1, 0, "K16", 0, 11, 1, "caption", 0), (17, 1, 0, "K17", 0, 12, 0, "", 0),
    ] + list(extra_messages)
    for (i, c, fm, k, s, sec, ty, tx, st) in rows:
        a.execute(
            "INSERT INTO message(_id,chat_row_id,from_me,key_id,sender_jid_row_id,status,timestamp,"
            "received_timestamp,message_type,text_data,starred,sort_id) VALUES(?,?,?,?,?,0,?,?,?,?,?,?)",
            (i, c, fm, k, s, ms(sec), ms(sec) + 2000, ty, tx, st, i))
    a.commit()
    a.close()


def make_ios(path, active=True, pinned=False):
    """An iPhone database. active=True is the account that matches the Android
    history; active=False is a second account that received the same messages."""
    i = sqlite3.connect(path)
    i.executescript(IOS_DDL)
    for ent, name in ((4, "WAChatSession"), (5, "WAGroupInfo"), (6, "WAGroupMember"),
                      (8, "WAMediaItem"), (9, "WAMessage")):
        i.execute("INSERT INTO Z_PRIMARYKEY VALUES(?,?,0,0)", (ent, name))
    i.execute("INSERT INTO Z_METADATA VALUES(1,'u',x'00')")
    i.executescript("""
    INSERT INTO ZWACHATSESSION(Z_PK,Z_ENT,Z_OPT,ZSESSIONTYPE,ZCONTACTJID,ZMESSAGECOUNTER,ZREMOVED,ZHIDDEN,ZARCHIVED,ZGROUPINFO,ZFLAGS,ZSPOTLIGHTSTATUS,ZLASTMESSAGE) VALUES
     (10,4,3,0,'911@s.whatsapp.net',3,0,0,0,NULL,272,-5,21),
     (11,4,3,0,'55@lid',2,0,0,0,NULL,67109120,-5,22),
     (12,4,3,1,'g1@g.us',3,0,0,0,5,999,-5,24),
     (13,4,3,3,'911@status',0,0,0,0,NULL,0,-5,NULL);
    INSERT INTO ZWAGROUPINFO(Z_PK,Z_ENT,Z_OPT,ZSTATE,ZCHATSESSION) VALUES(5,5,1,2,12);
    INSERT INTO ZWAGROUPMEMBER(Z_PK,Z_ENT,Z_OPT,ZCHATSESSION,ZMEMBERJID,ZISACTIVE) VALUES(30,6,1,12,'77@lid',1);
    """)
    gdup = "GDUP" if not active else "IGRP"          # the other account received what Android sent
    rows = [  # pk, from_me, status, sort, chat, member, date, key, text, from, to, flags, groupevent, lastsession
        (20, 0, 8, 1, 10, None, apple(100), "DUP", "already", "911@s.whatsapp.net", None, 16777216, 0, None),
        (21, 1, 8, 2, 10, None, apple(200), "I2", "iphone out", None, "911@s.whatsapp.net", 16777280, 0, 10),
        (22, 0, 8, 1, 11, None, apple(400), "I3", "hidden id in", "55@lid", None, 16777216, 0, 11),
        (23, 0, 6, 1, 12, 30, apple(50), gdup, "group", "g1@g.us", None, 16777216, 2, None),
        (24, 0, 6, 2, 12, 30, apple(60), "I5", "group", "g1@g.us", None, 16777216, 2, 12),
        (25, 1, 8, 3, 10, None, apple(210), "I6", "iphone out 2", None, "911@s.whatsapp.net", 16777280, 0, None),
    ]
    if not active:
        rows = [r for r in rows if r[1] == 0]        # a dormant account: nothing sent
    for r in rows:
        i.execute(
            "INSERT INTO ZWAMESSAGE(Z_PK,Z_ENT,Z_OPT,ZISFROMME,ZMESSAGESTATUS,ZMESSAGETYPE,ZSORT,ZCHATSESSION,"
            "ZGROUPMEMBER,ZMESSAGEDATE,ZSTANZAID,ZTEXT,ZFROMJID,ZTOJID,ZFLAGS,ZGROUPEVENTTYPE,ZLASTSESSION,"
            "ZDATAITEMVERSION,ZSPOTLIGHTSTATUS) VALUES(?,9,2,?,?,0,?,?,?,?,?,?,?,?,?,?,?,3,-32768)", r)
    if pinned:
        i.execute("UPDATE ZWACHATSESSION SET ZLASTMESSAGEDATE=? WHERE Z_PK=10", (9000 * 31557600.0,))
    for ent, zmax in ((4, 13), (5, 5), (6, 30), (9, 40)):
        i.execute("UPDATE Z_PRIMARYKEY SET Z_MAX=? WHERE Z_ENT=?", (zmax, ent))
    i.commit()
    i.execute("PRAGMA journal_mode=wal")
    i.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    i.close()
    for suffix in ("-wal", "-shm"):
        if os.path.exists(str(path) + suffix):
            os.remove(str(path) + suffix)


def _record(rel, size, digest=False):
    uid = plistlib.UID
    obj = {"$class": uid(3), "Size": size, "LastModified": 1, "Mode": 33188, "RelativePath": uid(2),
           "ProtectionClass": 3, "InodeNumber": 5, "UserID": 501, "GroupID": 501, "Birth": 1,
           "LastStatusChange": 1, "Flags": 0}
    objects = ["$null", obj, rel, {"$classname": "MBFile", "$classes": ["MBFile", "NSObject"]}]
    if digest:
        obj["Digest"] = uid(4)
        objects.append(b"\x01" * 20)
    return plistlib.dumps({"$archiver": "NSKeyedArchiver", "$version": 100000, "$top": {"root": uid(1)},
                           "$objects": objects}, fmt=plistlib.FMT_BINARY)


def make_backup(root, accounts, encrypted=False, digest=False):
    """A Finder-style backup folder. accounts maps a path inside WhatsApp's
    shared container to a database file to store there."""
    b = os.path.join(root, "00008000-TESTDEVICE")
    os.makedirs(b)
    man = sqlite3.connect(os.path.join(b, "Manifest.db"))
    man.execute("CREATE TABLE Files (fileID TEXT PRIMARY KEY, domain TEXT, relativePath TEXT, flags INTEGER, file BLOB)")
    man.execute("CREATE TABLE Properties (key TEXT PRIMARY KEY, value BLOB)")
    for n, (rel, src) in enumerate(accounts.items()):
        fid = f"{n + 10:02x}" + "ab" * 19
        os.makedirs(os.path.join(b, fid[:2]), exist_ok=True)
        with open(src, "rb") as f, open(os.path.join(b, fid[:2], fid), "wb") as g:
            g.write(f.read())
        man.execute("INSERT INTO Files VALUES(?,?,?,1,?)", (fid, DOMAIN, rel, _record(rel, os.path.getsize(src), digest)))
    man.commit()
    man.close()
    with open(os.path.join(b, "Manifest.plist"), "wb") as f:
        plistlib.dump({"IsEncrypted": encrypted, "Version": "10.0", "Lockdown": {"ProductVersion": "27.0.1"}}, f)
    with open(os.path.join(b, "Status.plist"), "wb") as f:
        plistlib.dump({"BackupState": "new", "IsFullBackup": True, "SnapshotState": "finished", "Version": "3.3"}, f)
    return b


def run(cwd, *args):
    env = dict(os.environ, PYTHONPATH=os.path.join(ROOT, "src"))
    return subprocess.run([sys.executable, "-m", "wamerge", *map(str, args)], cwd=cwd, env=env,
                          capture_output=True, text=True)


@pytest.fixture
def work(tmp_path):
    """A working folder with an Android history and one iPhone database."""
    for d in ("android-decrypted", "ios-copy/active", "output"):
        os.makedirs(tmp_path / d)
    make_android(tmp_path / "android-decrypted/msgstore.db")
    make_ios(tmp_path / "ios-copy/active/ChatStorage.sqlite")
    return tmp_path
