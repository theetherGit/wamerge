"""Command line entry point. Each step is a self-contained script in steps/,
run with its own arguments so the tested behaviour of each step is unchanged."""
import os
import runpy
import sys

from . import __version__

STEPS = {
    "extract": ("extract.py", "Copy the right WhatsApp account's databases out of the newest Finder backup"),
    "merge": ("merge.py", "Merge the Android text history into a copy of the iPhone database"),
    "install": ("install.py", "Put the merged database into the backup (dry run unless --apply)"),
    "stickers": ("stickers.py", "Build .wastickers packs from the Android sticker folder"),
    "profile": ("profile.py", "Diagnostic: counts and codes on each side (no message content)"),
    "backup-check": ("backup_check.py", "Diagnostic: how the backup records WhatsApp's database"),
    "find-stores": ("find_stores.py", "Diagnostic: every WhatsApp account in a backup; split chats"),
}

USAGE = """wamerge {version}

Merge an Android WhatsApp text history into an iPhone's WhatsApp database.
For your own data only. Read the guide before running 'install --apply':
restoring the modified backup replaces everything on the iPhone.

usage: wamerge <step> [arguments]

steps, in the order you run them:
{steps}

Run from your working folder (the one holding android-decrypted/, ios-copy/
and output/). Every step reads its inputs read-only; only 'install --apply'
changes a Finder backup, after saving an untouched copy of it.
"""


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("-h", "--help", "help"):
        lines = "\n".join(f"  {name:<13} {desc}" for name, (_, desc) in STEPS.items())
        print(USAGE.format(version=__version__, steps=lines))
        return 0
    if argv[0] in ("-V", "--version"):
        print(__version__)
        return 0
    step = argv[0]
    if step not in STEPS:
        print(f"wamerge: unknown step '{step}'. Run 'wamerge --help'.", file=sys.stderr)
        return 2
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "steps", STEPS[step][0])
    if any(a in ("-h", "--help") for a in argv[1:]):
        import ast
        with open(path) as f:
            print((ast.get_docstring(ast.parse(f.read())) or STEPS[step][1]).strip())
        return 0
    old = sys.argv
    sys.argv = [f"wamerge {step}"] + argv[1:]
    try:
        runpy.run_path(path, run_name="__main__")
    except SystemExit as e:
        if e.code is None or e.code == 0:
            return 0
        if isinstance(e.code, int):
            return e.code
        print(e.code, file=sys.stderr)
        return 1
    finally:
        sys.argv = old
    return 0
