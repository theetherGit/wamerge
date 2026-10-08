# wamerge

Merge the text history from an Android WhatsApp backup into the WhatsApp you
already use on an iPhone, keeping the iPhone's own chats.

> **Educational project. Not affiliated with, endorsed by or supported by Meta
> or WhatsApp. No warranty.** Read the [disclaimer](#disclaimer) before use.

**Experimental. Read this before using it.**

- For your own data only. You need your own phone number to unlock the backup.
- It relies on WhatsApp's undocumented file formats, which WhatsApp's terms do
  not permit you to reverse-engineer and which can change without notice.
- The last step restores your whole iPhone from a modified backup. It has
  worked in one real run on iOS 27.0.1, but a WhatsApp or iOS update can
  change that. Keep the untouched backup copy the tool makes until you are
  satisfied.
- Messages that arrived after the old phone stopped working and before
  WhatsApp was set up on the iPhone are not recovered if only a linked device
  (WhatsApp Web or Desktop) received them. They are in neither backup.
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

Proven end to end in one real run on iOS 27.0.1: recovery, extract, merge,
`install --apply`, the restore, and sticker packs. WhatsApp opened the restored
database with the old history in place. The only messages missing were the
ones from the gap described above. Not yet checked: whether search finds the
added messages, and whether new chats pick up contact names. If you run it on
another iOS version, please report what happened.

## Disclaimer

wamerge is an independent project, published for educational purposes and
for personal interoperability: moving your own chat history between your own
devices.

- **Not affiliated with Meta or WhatsApp.** wamerge is not made, endorsed or
  supported by Meta Platforms, Inc. or WhatsApp LLC. "WhatsApp" is a
  trademark of its owner and is used here only to say what the tool works
  with.
- **No Meta code.** This repository contains no code, keys or other material
  from Meta or WhatsApp. wamerge was written from scratch and uses only the
  Python standard library and Pillow. Decryption is done by
  [wa-crypt-tools](https://pypi.org/project/wa-crypt-tools/), a separate,
  publicly available open-source package that you install yourself.
- **Your own backups only.** wamerge reads backups you make of your own
  devices: a Finder backup of your iPhone, and the copy that WhatsApp itself
  restores onto an Android emulator under your own number. It makes no
  network connections, does not contact WhatsApp's servers and does not
  modify the WhatsApp app itself. The only thing it changes is the WhatsApp
  database inside your own iPhone backup, and only with `install --apply`.
- **Your responsibility.** WhatsApp's terms of service may not permit working
  with its file formats this way. You alone decide whether to use wamerge,
  and you are responsible for following those terms and the laws that apply
  to you. Use it only on your own account and your own data.
- **No warranty.** wamerge is provided "as is" under the MIT licence (see
  [LICENSE](LICENSE)). The authors are not liable for lost data, a damaged
  backup, a restricted or banned account, or any other harm from using it.
