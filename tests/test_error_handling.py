"""Failure paths: every step must stop cleanly and leave the backup, its
inputs and unrelated folders exactly as they were."""
import os
import sqlite3

from conftest import make_android, make_ios, run
from test_extract_install import AND, count, install, pipeline, stored
from test_extract_install import setup as make_work

ACCOUNT = "data/ACCOUNT-2/ChatStorage.sqlite"


def test_apply_puts_the_backup_back_if_the_index_update_fails(tmp_path):
    root, backup = make_work(tmp_path)
    pipeline(tmp_path, root)
    path, size = stored(backup, ACCOUNT)
    original = open(path, "rb").read()
    man = sqlite3.connect(os.path.join(backup, "Manifest.db"))
    man.execute("CREATE TRIGGER fail BEFORE UPDATE ON Files WHEN NEW.file <> OLD.file "
                "BEGIN SELECT RAISE(ABORT, 'disk gone'); END")
    man.commit()
    man.close()
    r = install(tmp_path, root, "--apply")
    assert r.returncode != 0 and "put back" in r.stderr and "INSTALLED" not in r.stdout
    assert open(path, "rb").read() == original and stored(backup, ACCOUNT)[1] == size
    assert not os.path.exists(path + ".tmp")


def test_install_refuses_a_backup_with_a_non_empty_wal(tmp_path):
    (tmp_path / "wal").write_bytes(b"x" * 100)
    os.makedirs(tmp_path / "pre")
    make_ios(tmp_path / "pre/main.sqlite", active=False)
    make_ios(tmp_path / "pre/second.sqlite", active=True)
    root, backup = make_work(tmp_path, accounts={
        "ChatStorage.sqlite": tmp_path / "pre/main.sqlite",
        ACCOUNT: tmp_path / "pre/second.sqlite",
        ACCOUNT + "-wal": tmp_path / "wal"})
    r = run(tmp_path, "extract", root, "ios-copy/active", AND)
    assert r.returncode == 0 and "WARNING" in r.stdout and "-wal" in r.stdout
    pipeline(tmp_path, root)
    r = install(tmp_path, root, "--apply")
    assert r.returncode != 0 and "-wal" in r.stderr
    assert count(stored(backup, ACCOUNT)[0]) == 6


def test_extract_stops_with_two_accounts_and_no_android_history(tmp_path):
    root, _ = make_work(tmp_path)
    r = run(tmp_path, "extract", root, "ios-copy/active", "android-decrypted/typo.db")
    assert r.returncode != 0 and "STOPPED" in r.stderr
    assert not os.path.exists(tmp_path / "ios-copy/active/ChatStorage.sqlite")


def test_a_newer_folder_that_is_not_a_backup_stops_extract_and_install(tmp_path):
    root, _ = make_work(tmp_path)
    pipeline(tmp_path, root)
    os.makedirs(root / "zz-not-a-backup")
    os.utime(root / "zz-not-a-backup", (2_000_000_000, 2_000_000_000))
    for r in (run(tmp_path, "extract", root, "ios-copy/active", AND), install(tmp_path, root)):
        assert r.returncode != 0 and "not a finished Finder backup" in r.stderr, r.stderr


def test_merge_runs_with_default_paths(work):
    r = run(work, "merge")
    assert r.returncode == 0, r.stdout + r.stderr
    assert os.path.exists(work / "output/ChatStorage.merged.sqlite")


def test_a_failed_merge_leaves_no_output_and_no_old_report(work):
    paths = (AND, "ios-copy/active/ChatStorage.sqlite", "output/merged.sqlite")
    assert run(work, "merge", *paths).returncode == 0
    db = sqlite3.connect(work / paths[1])
    db.execute("CREATE TRIGGER t AFTER INSERT ON ZWAMESSAGE BEGIN SELECT 1; END")
    db.commit()
    db.close()
    r = run(work, "merge", *paths)
    assert r.returncode != 0 and "STOPPED" in r.stderr
    assert sorted(os.listdir(work / "output")) == []


def test_stickers_will_not_delete_a_folder_it_did_not_make(tmp_path):
    os.makedirs(tmp_path / "android-raw/WhatsApp Stickers")
    os.makedirs(tmp_path / "android-decrypted")
    make_android(tmp_path / AND)
    from PIL import Image
    Image.new("RGBA", (512, 512), (1, 2, 3, 255)).save(tmp_path / "android-raw/WhatsApp Stickers/a.webp")
    os.makedirs(tmp_path / "Desktop")
    (tmp_path / "Desktop/notes.txt").write_text("keep me")
    r = run(tmp_path, "stickers", "android-raw", AND, "Desktop", "--all")
    assert r.returncode != 0 and "STOPPED" in r.stderr
    assert (tmp_path / "Desktop/notes.txt").read_text() == "keep me"
