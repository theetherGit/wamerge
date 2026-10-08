import hashlib
import sqlite3

from conftest import apple, make_ios, run

AND = "android-decrypted/msgstore.db"
IOS = "ios-copy/active/ChatStorage.sqlite"
OUT = "output/ChatStorage.merged.sqlite"


def md5(p):
    return hashlib.md5(open(p, "rb").read()).hexdigest()


def merged(work):
    r = run(work, "merge", AND, IOS, OUT)
    assert r.returncode == 0, r.stdout + r.stderr
    return sqlite3.connect(f"file:{work / OUT}?mode=ro&immutable=1", uri=True), r.stdout


def test_sources_are_never_modified(work):
    before = md5(work / AND), md5(work / IOS)
    merged(work)
    assert (md5(work / AND), md5(work / IOS)) == before


def test_counts_and_report(work):
    db, out = merged(work)
    assert "integrity check: ok" in out
    assert db.execute("SELECT count(*) FROM ZWAMESSAGE").fetchone()[0] == 6 + 11
    assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    # the report must not leak message text
    assert "old in" not in out and "newer than iphone" not in out


def test_only_text_from_ordinary_chats_is_added(work):
    db, _ = merged(work)
    keys = {r[0] for r in db.execute("SELECT ZSTANZAID FROM ZWAMESSAGE")}
    assert "K14" not in keys      # newsletter
    assert "K15" not in keys      # media, no text
    assert "K16" not in keys      # media with caption
    assert "K17" not in keys      # empty text


def test_duplicates_are_skipped(work):
    db, _ = merged(work)
    assert db.execute("SELECT count(*) FROM ZWAMESSAGE WHERE ZSTANZAID='DUP'").fetchone()[0] == 1
    # one person stored under two Android addresses: the shared message lands once
    assert db.execute("SELECT count(*) FROM ZWAMESSAGE WHERE ZSTANZAID='K11'").fetchone()[0] == 1


def test_same_message_sent_on_one_side_received_on_other_is_not_doubled(tmp_path):
    import os
    from conftest import make_android
    for d in ("android-decrypted", "ios-copy/active", "output"):
        os.makedirs(tmp_path / d)
    make_android(tmp_path / AND)
    make_ios(tmp_path / IOS, active=False)
    db, _ = merged(tmp_path)
    assert db.execute("SELECT count(*) FROM ZWAMESSAGE WHERE ZSTANZAID='GDUP'").fetchone()[0] == 1


def test_order_is_renumbered_by_date(work):
    db, _ = merged(work)
    rows = db.execute("SELECT ZSTANZAID FROM ZWAMESSAGE WHERE ZCHATSESSION=10 ORDER BY ZSORT").fetchall()
    assert [r[0] for r in rows] == ["K1", "K2", "DUP", "I2", "I6", "K4"]
    sorts = [r[0] for r in db.execute("SELECT ZSORT FROM ZWAMESSAGE WHERE ZCHATSESSION=10 ORDER BY ZSORT")]
    assert sorts == list(range(1, 7))
    assert db.execute("SELECT ZMESSAGECOUNTER FROM ZWACHATSESSION WHERE Z_PK=10").fetchone()[0] == 7


def test_hidden_id_and_phone_number_are_one_chat(work):
    db, _ = merged(work)
    # Android chat under the phone number joins the iPhone chat under the hidden id
    assert db.execute("SELECT ZCHATSESSION, ZTOJID FROM ZWAMESSAGE WHERE ZSTANZAID='K5'").fetchone() == (11, "55@lid")
    assert db.execute("SELECT count(*) FROM ZWACHATSESSION WHERE ZCONTACTJID LIKE '912@%'").fetchone()[0] == 0
    # two Android chats for one new person become one chat, ordered by time
    pk = db.execute("SELECT Z_PK FROM ZWACHATSESSION WHERE ZCONTACTJID='913@s.whatsapp.net'").fetchone()[0]
    assert db.execute("SELECT count(*) FROM ZWACHATSESSION WHERE ZCONTACTJID='66@lid'").fetchone()[0] == 0
    assert [r[0] for r in db.execute("SELECT ZSTANZAID FROM ZWAMESSAGE WHERE ZCHATSESSION=? ORDER BY ZSORT", (pk,))] == ["K12", "K11"]


def test_group_senders(work):
    db, _ = merged(work)
    # both addresses of a known sender map to the existing member row
    assert {r[0] for r in db.execute("SELECT ZGROUPMEMBER FROM ZWAMESSAGE WHERE ZSTANZAID IN ('K6','K7')")} == {30}
    # every added group message points at a member of its own chat
    assert db.execute(
        """SELECT count(*) FROM ZWAMESSAGE m WHERE m.Z_PK > 40 AND m.ZGROUPMEMBER IS NOT NULL AND NOT EXISTS
           (SELECT 1 FROM ZWAGROUPMEMBER g WHERE g.Z_PK = m.ZGROUPMEMBER AND g.ZCHATSESSION = m.ZCHATSESSION)"""
    ).fetchone()[0] == 0


def test_new_group_and_archived_state(work):
    db, _ = merged(work)
    pk, archived, info, name = db.execute(
        "SELECT Z_PK, ZARCHIVED, ZGROUPINFO, ZPARTNERNAME FROM ZWACHATSESSION WHERE ZCONTACTJID='g2@g.us'").fetchone()
    assert archived == 1 and name == "G two"
    assert db.execute("SELECT ZCHATSESSION FROM ZWAGROUPINFO WHERE Z_PK=?", (info,)).fetchone()[0] == pk


def test_addresses_dates_and_stars(work):
    db, _ = merged(work)
    assert db.execute("SELECT ZFROMJID, ZTOJID, ZMESSAGEDATE FROM ZWAMESSAGE WHERE ZSTANZAID='K1'").fetchone() == (
        "911@s.whatsapp.net", None, apple(10))
    assert db.execute("SELECT ZFROMJID, ZTOJID, ZSTARRED FROM ZWAMESSAGE WHERE ZSTANZAID='K2'").fetchone() == (
        None, "911@s.whatsapp.net", 1)


def test_conventions_are_copied_from_the_iphone(work):
    db, _ = merged(work)
    assert db.execute("SELECT ZFLAGS FROM ZWAMESSAGE WHERE ZSTANZAID='K1'").fetchone()[0] == 16777216
    assert db.execute("SELECT ZFLAGS FROM ZWAMESSAGE WHERE ZSTANZAID='K2'").fetchone()[0] == 16777280


def test_row_counters_advance(work):
    db, _ = merged(work)
    for ent, table in ((4, "ZWACHATSESSION"), (5, "ZWAGROUPINFO"), (6, "ZWAGROUPMEMBER"), (9, "ZWAMESSAGE")):
        zmax = db.execute("SELECT Z_MAX FROM Z_PRIMARYKEY WHERE Z_ENT=?", (ent,)).fetchone()[0]
        assert zmax >= db.execute(f"SELECT max(Z_PK) FROM {table}").fetchone()[0]


def test_preview_moves_to_a_newer_added_message(work):
    db, _ = merged(work)
    last, text = db.execute("SELECT ZLASTMESSAGE, ZLASTMESSAGETEXT FROM ZWACHATSESSION WHERE Z_PK=10").fetchone()
    assert text == "newer than iphone"
    assert db.execute("SELECT ZSTANZAID, ZLASTSESSION FROM ZWAMESSAGE WHERE Z_PK=?", (last,)).fetchone() == ("K4", 10)
    assert db.execute("SELECT ZLASTSESSION FROM ZWAMESSAGE WHERE Z_PK=21").fetchone()[0] is None
    assert db.execute(
        "SELECT count(*) FROM (SELECT ZLASTSESSION FROM ZWAMESSAGE WHERE ZLASTSESSION IS NOT NULL GROUP BY 1 HAVING count(*)>1)"
    ).fetchone()[0] == 0


def test_pinned_chat_stays_pinned(tmp_path):
    import os
    from conftest import make_android
    for d in ("android-decrypted", "ios-copy/active", "output"):
        os.makedirs(tmp_path / d)
    make_android(tmp_path / AND)
    make_ios(tmp_path / IOS, pinned=True)
    db, _ = merged(tmp_path)
    assert db.execute("SELECT ZLASTMESSAGEDATE FROM ZWACHATSESSION WHERE Z_PK=10").fetchone()[0] == 9000 * 31557600.0


def test_output_is_a_single_clean_file(work):
    import os
    merged(work)
    assert not os.path.exists(work / (OUT + "-wal"))


def test_missing_input_gives_a_message_not_a_traceback(tmp_path):
    r = run(tmp_path, "merge")
    assert r.returncode != 0 and "Traceback" not in r.stderr and "not found" in r.stderr


def test_refuses_to_write_over_the_iphone_copy(work):
    r = run(work, "merge", AND, IOS, IOS)
    assert r.returncode != 0 and "same" in r.stderr
