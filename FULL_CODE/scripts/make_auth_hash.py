#!/usr/bin/env python3
"""Create the password hash for the web demo's optional login.

    python FULL_CODE/scripts/make_auth_hash.py <user name>

Prompts for the password (not echoed) and prints two lines to export. Only the salted scrypt hash is kept, never the password.
"""

from __future__ import annotations

import getpass
import sys

from werkzeug.security import generate_password_hash

MIN_LENGTH = 12


def main() -> None:
    if len(sys.argv) != 2 or not sys.argv[1].strip():
        raise SystemExit("usage: make_auth_hash.py <user name>")
    password = getpass.getpass("password (at least 12 characters): ")
    if len(password) < MIN_LENGTH or password != getpass.getpass("repeat: "):
        raise SystemExit(f"password must be at least {MIN_LENGTH} characters and match")
    print(f"R5_AUTH_USER={sys.argv[1].strip()}")
    print(f"R5_AUTH_HASH={generate_password_hash(password, method='scrypt')}")


if __name__ == "__main__":
    main()
