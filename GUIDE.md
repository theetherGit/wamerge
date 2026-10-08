# Recovering an Android WhatsApp history onto an iPhone

This guide merges the text history from a dead Android phone's WhatsApp backup
into the WhatsApp you already use on an iPhone, keeping the iPhone's own chats.
The recovery and merge are proven on real data. The final restore to the phone
had not been run on iOS 27 when this was written.

## What you get

Text messages, chats, groups and starred flags come across. Media and a few
message features do not.

| Item | Status |
| --- | --- |
| Text messages, one-to-one chats, groups, group senders | Merged |
| Starred and archived state | Kept |
| The iPhone's existing chats and media | Untouched |
| Sticker collection | Rebuilt separately as sticker packs |
| Photos, videos, voice notes, documents and their captions | Not merged |
| Reply quotes | Reply text is kept, the quoted bubble is not |
| Reactions, polls, calls, system notices | Not merged |

What is still unproven: whether WhatsApp on iOS 27 accepts the modified
database after a restore, whether search finds the added messages, and whether
new chats pick up contact names. The method follows older tools that did this
on earlier iOS versions.

This works only on your own data. It needs your own number to unlock the
backup, and it relies on WhatsApp's undocumented file formats, which WhatsApp's
terms do not permit you to reverse-engineer and which can change without notice.

## How it works

WhatsApp itself unlocks the old backup. The tool only converts and merges, and
nothing touches the phone until the last step.

1. **Recover.** An Android emulator restores the Google Drive backup under
   your number. A Drive backup cannot be downloaded or opened directly.
2. **Export.** You switch on an encrypted backup with a 64-digit key on the
   emulator, copy the backup file to the Mac and decrypt it with that key.
3. **Extract.** A Finder backup of the iPhone gives a copy of WhatsApp's own
   database, `ChatStorage.sqlite`.
4. **Merge.** The tool adds the Android messages to a copy of the iPhone
   database, on the Mac, and verifies the result.
5. **Restore.** The merged database replaces the original inside a fresh
   Finder backup, and the iPhone is restored from it.

Steps 1 to 4 are read-only for the phone and can be repeated freely. Step 5
restores the whole iPhone and is the only step that carries risk.

## Before you start

You need a Mac, the SIM for the old number, and an hour or two in which the
iPhone can be out of use.

**What you need**

- The old phone's WhatsApp backup on Google Drive, visible under Backups in
  that Google account. Google may delete WhatsApp backups that go unused for
  about five months.
- The same phone number, active, so WhatsApp can verify it. If the old phone
  had end-to-end encrypted backup on, you also need that password or key.
- A Mac with Android Studio, Python 3.9 or later, and free disk space for a
  full iPhone backup.
- Full Disk Access for Terminal (System Settings > Privacy & Security), so the
  tool can read the Finder backup.

**What the restore costs you**

- It replaces everything on the iPhone with the backup taken minutes earlier.
  Apps re-download.
- The backup must be unencrypted, so saved passwords, Wi-Fi passwords, Health
  data, call history and Safari history return only if they sync through
  iCloud. Turn on iCloud Keychain and Health first.
- Apple Pay cards and Face ID need setting up again. Banking, payment and
  authenticator apps may ask you to register again, and payment apps can apply
  a lower limit for a day or more afterwards. Confirm your authenticator codes
  are backed up before you start.
- Find My must be off. With Stolen Device Protection on, turning it off away
  from a familiar location starts a one-hour delay.

**Working folder**

```
mkdir -p ~/wa-work/{android-raw,android-decrypted,ios-copy,output}
cd ~/wa-work
python3 -m venv .venv
source .venv/bin/activate
pip install "/path/to/this/repo[decrypt]"
```

This folder will hold your full chat history in readable form. Keep it out of
iCloud Drive and any synced or shared folder, and never commit it to a
repository.

## Recover the Android history (steps 1 and 2)

An emulator stands in for the dead phone: WhatsApp restores the Drive backup
onto it, and you export a copy you can decrypt.

If the number is active on your iPhone, WhatsApp there logs out while the
emulator holds it. Its chats stay on the device, but back up first: WhatsApp >
Settings > Chats > Chat Backup, and a full Finder backup.

**Set up the emulator**

1. In Android Studio's Device Manager, create a device with a **Google Play**
   system image. A Google APIs image cannot reach the Drive backup. If the
   newest API level lists no image, pick the one below it.
2. Under Additional settings, raise internal storage above the size of the
   WhatsApp backup.
3. Boot it, sign in to the Google account that holds the backup, and install
   WhatsApp from the Play Store.

**Restore**

1. Enter your number. The code arrives in WhatsApp on your other phone, or by
   SMS.
2. Allow contacts and media access, then tap Restore. If WhatsApp says no
   backup was found, do not skip: check the Google account and permissions.
3. Leave the emulator open until media has finished downloading. A new backup
   replaces the old one on Drive, so the emulator must hold everything first.

**Export a copy you can decrypt**

1. In WhatsApp, open Settings > Chats > Chat Backup > End-to-end Encrypted
   Backup, turn it on, and choose the 64-digit key. Save the key.
2. Tap Back Up and wait for it to finish.
3. Copy the data to the Mac and decrypt it:

```
cd ~/wa-work
ADB=~/Library/Android/sdk/platform-tools/adb
$ADB pull /sdcard/Android/media/com.whatsapp/WhatsApp android-raw/
wadecrypt YOUR64DIGITKEY android-raw/WhatsApp/Databases/msgstore.db.crypt15 android-decrypted/msgstore.db
```

Check it before moving on. The count and newest time should match what the
emulator shows:

```
sqlite3 -readonly android-decrypted/msgstore.db "SELECT count(*), datetime(max(timestamp)/1000,'unixepoch','localtime') FROM message;"
```

Then open WhatsApp on the iPhone and verify the number again. Keep the emulator
device; it is your second copy.

An old `msgstore.db.crypt14` file found on a computer is no shortcut. Its key
lived on the dead phone, so it can only be opened by letting WhatsApp restore
it the same way.

## Extract the iPhone database (step 3)

A Finder backup holds WhatsApp's database as an ordinary SQLite file, and
`wamerge extract` copies it out without changing the backup.

1. Connect the iPhone. In Finder choose "Back up all of the data on your
   iPhone to this Mac", leave **Encrypt local backup** unticked, and click
   Back Up Now.
2. Run the extract:

```
cd ~/wa-work
wamerge extract
```

It copies `ChatStorage.sqlite`, `LID.sqlite` and `ContactsV2.sqlite` into
`ios-copy/active/` and records which file in the backup they came from.

**If the iPhone has two WhatsApp accounts**

Each account has its own database. The first sits in the main folder of
WhatsApp's shared container; a second sits under `data/<account id>/`. Merging
into the wrong one puts your old chats in the wrong account.

The tool picks the account by two tests that do not depend on timing: none of
its messages appear "sent on one side, received on the other" in the Android
history, and it is the one you send from. If the tests disagree it stops and
copies nothing. It prints both accounts with their date range and message
counts, so check that it chose the one whose history starts where the Android
history ends.

## Merge (step 4)

`wamerge merge` adds the Android text messages to a copy of the iPhone database
and rejects its own output if any check fails.

```
wamerge merge android-decrypted/msgstore.db ios-copy/active/ChatStorage.sqlite
```

It writes `output/ChatStorage.merged.sqlite` and `output/merge-report.txt`.
Both source files are opened read-only. The report holds counts only, no names
or message text.

**Read the report**

- "integrity check: ok" and no leftover side files.
- Messages after = messages before + messages added.
- "skipped: already on the iPhone" should be small if the two histories do not
  overlap in time.
- The ID links lines should show the iPhone's own tables agreeing with
  Android's.

**Read a few chats before going further**

```
sqlite3 -box 'file:output/ChatStorage.merged.sqlite?immutable=1' "
SELECT ZPARTNERNAME AS chat, ZMESSAGECOUNTER-1 AS messages
FROM ZWACHATSESSION WHERE ZSESSIONTYPE IN (0,1) ORDER BY 2 DESC LIMIT 15;"
```

```
sqlite3 -box 'file:output/ChatStorage.merged.sqlite?immutable=1' "
SELECT ZSORT AS n, datetime(ZMESSAGEDATE+978307200,'unixepoch','localtime') AS time,
       CASE ZISFROMME WHEN 1 THEN 'me' ELSE 'them' END AS who, substr(ZTEXT,1,60) AS text
FROM ZWAMESSAGE
WHERE ZCHATSESSION=(SELECT Z_PK FROM ZWACHATSESSION WHERE ZPARTNERNAME='NAME' LIMIT 1)
ORDER BY ZSORT DESC LIMIT 40;"
```

Times should run in order, "me" and "them" should be the right way round, and
the newest messages should be the ones you see on the phone. If a chat ends
earlier than it should, you have probably merged into the wrong account.

Chats created from Android show a phone number as their name here, because
Android keeps contact names in a file that cannot be pulled without root.

## Install and restore (step 5)

This step is untested on iOS 27: the tool passes its own checks, but no restore
had been run when this was written. Treat your first run as a trial and keep
the untouched backup copy until you are satisfied.

Run the steps back to back. A backup taken hours earlier would wipe everything
the phone received since.

1. **Prepare the iPhone.** Turn off Find My, back up WhatsApp to iCloud in
   each account, and check iCloud Keychain and Health are on.
2. **Airplane mode on.** Messages sent to you wait on WhatsApp's servers and
   arrive after the restore.
3. **Fresh backup.** In Finder, with encryption unticked, click Back Up Now.
4. **Rebuild and install:**

```
cd ~/wa-work
wamerge extract
wamerge merge android-decrypted/msgstore.db ios-copy/active/ChatStorage.sqlite
wamerge install            # dry run: checks only
wamerge install --apply
```

5. **Check the output.** Continue only if it ends with `INSTALLED` and the
   line after shows `True` and `ok`. On `STOPPED` or `REJECTED`, nothing was
   changed; read the reason. On `FAILED`, the tool has already put the
   original file back; if it says that also failed, roll back by hand as
   described below before restoring.
6. **Restore.** In Finder click **Restore Backup…**, not "Restore iPhone…",
   which wipes the phone to factory state. Do not click Back Up Now again,
   because that overwrites the merged file.
7. **Finish.** When the phone restarts, turn Airplane mode off so apps
   re-download. Open WhatsApp, verify the number if asked, and choose Skip if
   it offers an iCloud chat restore.

**What the install does**

- Refuses unless the merged file was built from the database in that exact
  backup.
- Saves an untouched copy of the whole backup in `backup-untouched/` first, as
  an instant APFS clone.
- Replaces one file in the backup and updates its size in the backup's index.
  The index keeps no checksum for the file.

**What to check on the phone**

- An old chat scrolls back through the years, and a chat that existed on both
  phones runs in order.
- Sending and receiving works in every account.
- Search finds a word from an old message. This may fail and is not a reason
  to roll back on its own.

**Rolling back**

If WhatsApp crashes, shows empty chats or rejects the database, delete the
modified backup folder under `~/Library/Application Support/MobileSync/Backup/`,
copy the folder from `backup-untouched/` back in its place, and click Restore
Backup… again. Then turn Find My and Stolen Device Protection back on.

## Stickers

Stickers do not need the restore: `wamerge stickers` turns the old phone's
sticker files into packs that Sticker Maker Studio adds to WhatsApp. This part
worked on a real iPhone, for static and animated packs.

```
wamerge stickers          # stickers you sent, most used first
wamerge stickers --all    # every sticker sent or received
```

It reads the `WhatsApp Stickers` folder under `android-raw/`, removes
duplicates, ranks stickers by how often you sent them, and writes
`output/stickers/wastickers/static-01.wastickers`, `animated-01.wastickers`
and so on, 30 stickers per pack.

1. Install Sticker Maker Studio (by Viko & Co) on the iPhone.
2. AirDrop a `.wastickers` file to the phone and open it with Sticker Maker.
3. Tap Add to WhatsApp. Repeat per pack.

A `.wastickers` file is a zip holding 512 × 512 `.webp` stickers, a 96 × 96
`tray.png`, `title.txt` and `author.txt`. A pack is either all static or all
animated.

**Animated stickers that fail validation**

WhatsApp rejects a pack with an "invalid frame" notice if any sticker breaks
its rules, and Android-era files sometimes do. The tool rebuilds an animated
sticker when it finds:

- a frame shown for less than 8 ms,
- a frame that is one flat colour while its neighbours are not (a black flash),
- frames stored as patches over the previous frame.

Rebuilt stickers are flattened to full frames and re-compressed to stay under
500 KB, so they can look slightly softer. Untouched stickers are copied byte
for byte.

Add packs either before the fresh backup in step 5 or after the restore, not
in between.

## Commands

Four commands do the work and three are diagnostics. Only `wamerge install
--apply` changes anything outside the working folder.

| Command | Reads | Writes | Use |
| --- | --- | --- | --- |
| `wamerge extract` | Newest Finder backup, Android database | `ios-copy/active/` | Copy the right account's databases out of the backup |
| `wamerge merge` | Android database, iPhone database copy | `output/ChatStorage.merged.sqlite`, report | Merge text history and verify it |
| `wamerge install` | Merged database, newest Finder backup | With `--apply`: one file in the backup, its index entry, `backup-untouched/` | Put the merged database into the backup |
| `wamerge stickers` | Android sticker folder, Android database | `output/stickers/` | Build sticker packs |
| `wamerge profile` | Both databases | `output/profile.txt` | Counts and codes on each side, and how shared messages compare |
| `wamerge backup-check` | Newest Finder backup | Nothing | How the backup records WhatsApp's database |
| `wamerge find-stores` | Newest Finder backup, merged database | Nothing | Find every WhatsApp account in a backup; spot split chats |

Every report prints counts, codes and file sizes only. Names, phone numbers
and message text never appear in them.

## Problems you may hit

| Symptom | Cause | Fix |
| --- | --- | --- |
| `pip install` fails with "externally-managed-environment" | Homebrew's Python blocks system-wide installs | Use the `.venv` from the setup step |
| Device Manager lists no system image | The newest API level has no Google Play image yet | Choose the API level below it |
| WhatsApp finds no backup on the emulator | Wrong Google account, or contacts and media access denied | Fix the account or permissions; do not skip the screen |
| Restore asks for a password or 64-digit key | The old phone had encrypted backup on | You need that password or key; there is no way around it |
| A merged chat ends weeks too early | Merged into the wrong account's database | Re-run `wamerge extract` and check which account it chose |
| The tool cannot read the backup folder | Terminal lacks Full Disk Access | Grant it and reopen Terminal |
| Find My will not turn off | Stolen Device Protection delay, no internet, or Screen Time restrictions | Wait out the hour, or do it at a familiar location |
| `wamerge install` says the merged file is from a different backup | A newer backup was taken after the merge | Re-run extract and merge, then install |
| "Invalid frame" when adding a sticker pack | A sticker breaks WhatsApp's animation rules | Re-run `wamerge stickers`; it rebuilds those stickers |

## What the merge had to get right

These are the details that differ between the two formats and would corrupt
the result if ignored.

- **Order is a counter, not a date.** The iPhone sorts each chat by `ZSORT`.
  Old messages go before existing ones, so every merged chat is renumbered and
  its `ZMESSAGECOUNTER` updated.
- **One person, two addresses.** A contact can be stored under a phone number
  or a hidden ID (`@lid`). Android's `jid_map` table and the iPhone's
  `LID.sqlite` and `ContactsV2.sqlite` link them. The iPhone's links are used
  only if they agree with Android's.
- **Row counters.** Core Data hands out row IDs from `Z_PRIMARYKEY`. The merge
  advances those counters, or WhatsApp would reuse IDs.
- **Codes are copied, not guessed.** Flag and status values for new rows are
  taken from the most common values the iPhone already uses for the same kind
  of message.
- **Duplicates.** A message is skipped if its ID already exists in the same
  chat, whichever side sent it.
- **Previews and pins.** A chat's last-message link is two-way and must be
  updated on both rows. A last-message date far in the future marks a pinned
  chat and is left alone.
- **Dates.** Android stores milliseconds since 1970; the iPhone stores seconds
  since 2001.

Added messages lack the per-message metadata record that the iPhone writes for
its own messages. Whether the app needs it is what the first restore tests.

## Sources

- [How to back up your iPhone, iPad, and iPod touch with your Mac](https://support.apple.com/en-us/HT211229) (Apple)
- [About encrypted backups on your iPhone, iPad or iPod touch](https://support.apple.com/en-gb/108353) (Apple)
- [.WASTICKERS file extension](https://fileinfo.com/extension/wastickers) (FileInfo)
- [sticker-convert](https://github.com/laggykiller/sticker-convert), which also writes `.wastickers` files
- `wa-crypt-tools`, the Python package used to decrypt the `.crypt15` backup

The database layouts and account folders described here come from one real run
on iOS 27.0.1 and may differ on other versions.
