# wamerge

Merge the text history from an Android WhatsApp backup into the WhatsApp you
already use on an iPhone, keeping the iPhone's own chats.

**Experimental. Read this before using it.**

- For your own data only. You need your own phone number to unlock the backup.
- It relies on WhatsApp's undocumented file formats, which WhatsApp's terms do
  not permit you to reverse-engineer and which can change without notice.
- The last step restores your whole iPhone from a modified backup. That step
  had not been proven on iOS 27 when this was published. Keep the untouched
  backup copy the tool makes until you are satisfied.
- Text only. Photos, videos, voice notes, reply quotes and reactions are not
  merged. Stickers are rebuilt separately as sticker packs.

The full walkthrough, including the Android emulator steps and what the
restore costs you, is in [GUIDE.md](GUIDE.md).

## Install

Requires macOS, Python 3.9+, and Full Disk Access for your terminal (to read
Finder backups).

```
python3 -m venv .venv && source .venv/bin/activate
pip install ".[decrypt]"
```

## Use

Work in a private folder that is not synced or shared. It will hold your chat
history in readable form.

```
mkdir -p ~/wa-work/{android-raw,android-decrypted,ios-copy,output} && cd ~/wa-work

# 1. after restoring the Drive backup on an Android emulator and making an
#    encrypted backup with a 64-digit key (see GUIDE.md):
adb pull /sdcard/Android/media/com.whatsapp/WhatsApp android-raw/
wadecrypt YOUR64DIGITKEY android-raw/WhatsApp/Databases/msgstore.db.crypt15 android-decrypted/msgstore.db

# 2. after an unencrypted Finder backup of the iPhone:
wamerge extract
wamerge merge android-decrypted/msgstore.db ios-copy/active/ChatStorage.sqlite
wamerge install            # dry run: checks only
wamerge install --apply    # changes the backup, after saving an untouched copy

# stickers, independent of the restore:
wamerge stickers
```

| Step | Reads | Writes |
| --- | --- | --- |
| `extract` | newest Finder backup, Android database | `ios-copy/active/` |
| `merge` | Android database, iPhone database copy | `output/ChatStorage.merged.sqlite`, `output/merge-report.txt` |
| `install` | merged database, newest Finder backup | with `--apply`: one file in the backup, its index entry, `backup-untouched/` |
| `stickers` | Android sticker folder, Android database | `output/stickers/` |
| `profile`, `backup-check`, `find-stores` | databases or backup | reports of counts only |

Reports contain counts, codes and sizes. They never contain names, phone
numbers or message text.

## Tests

```
pip install ".[test]"
pytest
```

The tests build made-up databases and a made-up backup folder. No real
WhatsApp data is needed or included.

## Status

Proven on one real run (iOS 27.0.1): recovery, extract, merge, the install
dry run, and sticker packs. Not yet proven: `install --apply` followed by a
restore. If you run it, please report what WhatsApp did.
