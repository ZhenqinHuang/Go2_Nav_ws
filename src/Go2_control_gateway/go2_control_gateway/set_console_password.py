"""Create the scrypt password file used by the LAN console."""

import argparse
import getpass
import os
from pathlib import Path
import tempfile

from .console_core import hash_password


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description="Set Go2 console password")
    parser.add_argument(
        "--output",
        default="/etc/go2-console/password.hash",
        help="password hash destination",
    )
    arguments = parser.parse_args(argv)

    first = getpass.getpass("New operator password: ")
    second = getpass.getpass("Confirm password: ")
    if first != second:
        raise SystemExit("passwords do not match")
    if len(first) < 12:
        raise SystemExit("password must contain at least 12 characters")

    destination = Path(arguments.output)
    destination.parent.mkdir(parents=True, exist_ok=True)
    encoded = hash_password(first)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".password.",
        dir=str(destination.parent),
        text=True,
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            output.write(encoded + "\n")
        os.chmod(temporary_name, 0o600)
        os.replace(temporary_name, destination)
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)
    print(f"Password hash written to {destination}")
