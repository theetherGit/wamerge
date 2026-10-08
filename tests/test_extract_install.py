import os
import plistlib
import sqlite3

from conftest import make_android, make_backup, make_ios, run

AND = "android-decrypted/msgstore.db"


def setup(tmp_path, accounts=None, **backup_kw):
    os.makedirs(tmp_path / "android-decrypted")
    os.makedirs(tmp_path / "output")
    make_android(tmp_path / AND)
    make_ios(tmp_path / "main.sqlite", active=False)       # dormant account in the main folder
    make_ios(tmp_path / "second.sqlite", active=True)      # the account that matches Android
    root = tmp_path / "Backup"
    os.makedirs(root)
    accounts = accounts or {"ChatStorage.sqlite": tmp_path / "main.sqlite",
                            "data/ACCOUNT-2/ChatStorage.sqlite": tmp_path / "second.sqlite"}
    backup = make_backup(str(root), accounts, **backup_kw)
    return root, backup


def pipeline(tmp_path, root):
    r = run(tmp_path, "extract", root, "ios-copy/active", AND)
    assert r.returncode == 0, r.stdout + r.stderr
    r = run(tmp_path, "merge", AND, "ios-copy/active/ChatStorage.sqlite", "output/merged.sqlite")
    assert r.returncode == 0, r.stdout + r.stderr


def install(tmp_path, root, *flags):
    return run(tmp_path, "install", root, "output/merged.sqlite", "ios-copy/active", "backup-untouched", *flags)


def stored(backup, rel):
    man = sqlite3.connect(os.path.join(backup, "Manifest.db"))
    fid, blob = man.execute("SELECT fileID, file FROM Files WHERE relativePath=?", (rel,)).fetchone()
    man.close()
    size = next(o for o in plistlib.loads(blob)["$objects"] if isinstance(o, dict) and "Size" in o)["Size"]
    return os.path.join(backup, fid[:2], fid), size


def count(path):
    db = sqlite3.connect(f"file:{path}?mode=ro&immutable=1", uri=True)
    return db.execute("SELECT count(*) FROM ZWAMESSAGE").fetchone()[0]


def test_extract_picks_the_account_that_matches_android(tmp_path):
    root, _ = setup(tmp_path)
    r = run(tmp_path, "extract", root, "ios-copy/active", AND)
    assert r.returncode == 0, r.stdout + r.stderr
    assert open(tmp_path / "ios-copy/active/SOURCE.txt").read().strip() == "data/ACCOUNT-2/ChatStorage.sqlite"
    assert count(tmp_path / "ios-copy/active/ChatStorage.sqlite") == 6


def test_extract_stops_when_it_cannot_tell_the_accounts_apart(tmp_path):
    os.makedirs(tmp_path / "android-decrypted")
    make_android(tmp_path / AND)
    make_ios(tmp_path / "a.sqlite", active=True)
    make_ios(tmp_path / "b.sqlite", active=True)
    root = tmp_path / "Backup"
    os.makedirs(root)
    make_backup(str(root), {"ChatStorage.sqlite": tmp_path / "a.sqlite",
                            "data/ACCOUNT-2/ChatStorage.sqlite": tmp_path / "b.sqlite"})
    r = run(tmp_path, "extract", root, "ios-copy/active", AND)
    assert r.returncode != 0 and "STOPPED" in r.stderr
    assert not os.path.exists(tmp_path / "ios-copy/active/ChatStorage.sqlite")


def test_extract_does_not_change_the_backup(tmp_path):
    root, backup = setup(tmp_path)
    before = {p: os.path.getmtime(os.path.join(d, p)) for d, _, fs in os.walk(backup) for p in fs}
    listing = sorted(os.listdir(backup))
    run(tmp_path, "extract", root, "ios-copy/active", AND)
    assert sorted(os.listdir(backup)) == listing
    assert before == {p: os.path.getmtime(os.path.join(d, p)) for d, _, fs in os.walk(backup) for p in fs}


def test_dry_run_changes_nothing(tmp_path):
    root, backup = setup(tmp_path)
    pipeline(tmp_path, root)
    path, size = stored(backup, "data/ACCOUNT-2/ChatStorage.sqlite")
    r = install(tmp_path, root)
    assert r.returncode == 0 and "DRY RUN" in r.stdout
    assert count(path) == 6 and stored(backup, "data/ACCOUNT-2/ChatStorage.sqlite")[1] == size
    assert not os.path.exists(tmp_path / "backup-untouched")


def test_apply_replaces_only_the_right_file_and_keeps_an_untouched_copy(tmp_path):
    root, backup = setup(tmp_path)
    pipeline(tmp_path, root)
    other_path, other_size = stored(backup, "ChatStorage.sqlite")
    other_bytes = open(other_path, "rb").read()
    r = install(tmp_path, root, "--apply")
    assert r.returncode == 0 and "INSTALLED" in r.stdout, r.stdout + r.stderr
    path, size = stored(backup, "data/ACCOUNT-2/ChatStorage.sqlite")
    assert count(path) == 17 and size == os.path.getsize(path)
    assert not os.path.exists(path + "-wal")
    # the other account is untouched
    assert open(other_path, "rb").read() == other_bytes and stored(backup, "ChatStorage.sqlite")[1] == other_size
    # the untouched copy still holds the original
    safe = tmp_path / "backup-untouched" / os.path.basename(backup)
    safe_path, _ = stored(str(safe), "data/ACCOUNT-2/ChatStorage.sqlite")
    assert count(safe_path) == 6


def test_install_refuses_a_merge_built_from_another_backup(tmp_path):
    root, backup = setup(tmp_path)
    pipeline(tmp_path, root)
    # the phone was backed up again and now holds one more message
    path, _ = stored(backup, "data/ACCOUNT-2/ChatStorage.sqlite")
    db = sqlite3.connect(path)
    db.execute("INSERT INTO ZWAMESSAGE(Z_PK,Z_ENT,ZISFROMME,ZMESSAGETYPE,ZSORT,ZCHATSESSION,ZMESSAGEDATE,ZSTANZAID) "
               "VALUES(26,9,0,0,9,10,1.0,'LATER')")
    db.commit()
    db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    db.close()
    r = install(tmp_path, root, "--apply")
    assert r.returncode != 0 and "DIFFERENT backup" in r.stderr
    assert count(path) == 7


def test_install_refuses_an_encrypted_backup(tmp_path):
    root, _ = setup(tmp_path)
    pipeline(tmp_path, root)
    b = [d for d in os.listdir(root)][0]
    with open(root / b / "Manifest.plist", "wb") as f:
        plistlib.dump({"IsEncrypted": True, "Version": "10.0"}, f)
    r = install(tmp_path, root, "--apply")
    assert r.returncode != 0 and "encrypted" in r.stderr


def test_install_refuses_a_backup_that_records_a_checksum(tmp_path):
    root, backup = setup(tmp_path, digest=True)
    pipeline(tmp_path, root)
    r = install(tmp_path, root, "--apply")
    assert r.returncode != 0 and "checksum" in r.stderr
    assert count(stored(backup, "data/ACCOUNT-2/ChatStorage.sqlite")[0]) == 6


def test_apply_twice_is_refused(tmp_path):
    root, _ = setup(tmp_path)
    pipeline(tmp_path, root)
    assert install(tmp_path, root, "--apply").returncode == 0
    r = install(tmp_path, root, "--apply")
    assert r.returncode != 0 and "adds nothing" in r.stderr
