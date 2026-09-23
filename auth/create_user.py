"""Create a login for a staff member -- run once per person when setting
up a new pilot deploy. CLAUDE.md's go-to-market context is one contact on
medical/performance staff per pilot with white-glove setup, not self-serve
signup, so there's no in-app "create account" flow (yet) -- this is it.

Usage:
    python auth/create_user.py --email jane@theclub.com --name "Jane Doe"

Prompts for the password interactively (getpass -- not echoed, never left
in shell history) unless --password is given. --password exists only for
non-interactive/scripted use (see deploy/huggingface/build_seed.sh's
baked-in demo account), not for creating a real person's account -- typing
a real password as a CLI argument leaves it sitting in that shell's
history file.
"""

from __future__ import annotations

import argparse
import getpass
import sys
from pathlib import Path

AUTH_DIR = Path(__file__).resolve().parent
REPO_ROOT = AUTH_DIR.parent
sys.path.insert(0, str(AUTH_DIR))
sys.path.insert(0, str(REPO_ROOT))

from common import db  # noqa: E402
from users import create_user  # noqa: E402

MIN_PASSWORD_LENGTH = 8


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--email", required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--password", help="Non-interactive use only (e.g. seeding a demo account) -- omit to be prompted securely")
    return parser.parse_args()


def main():
    args = parse_args()

    if args.password:
        password = args.password
    else:
        password = getpass.getpass("Password: ")
        confirm = getpass.getpass("Confirm password: ")
        if confirm != password:
            print("Passwords didn't match.", file=sys.stderr)
            sys.exit(1)

    if len(password) < MIN_PASSWORD_LENGTH:
        print(f"Password must be at least {MIN_PASSWORD_LENGTH} characters.", file=sys.stderr)
        sys.exit(1)

    driver = db.connect()
    try:
        with driver.session() as session:
            db.run_constraints(session)
            user_id = create_user(session, args.email, args.name, password)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        driver.close()

    print(f"Created user {args.email} ({user_id})")


if __name__ == "__main__":
    main()
