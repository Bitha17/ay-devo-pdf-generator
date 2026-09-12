"""Import the current PythonAnywhere access log into the persistent analytics DB.

Run this from a PythonAnywhere scheduled task at least daily.  Importing the
same file repeatedly is safe: previously seen lines are ignored.
"""
import os
import sys

import db


DEFAULT_LOG = "/var/log/tabithapermalla.pythonanywhere.com.access.log"
DEFAULT_SALT_FILE = os.path.expanduser("~/.devo-analytics-salt")


def analytics_salt():
    salt = os.environ.get("DEVO_ANALYTICS_SALT") or os.environ.get("SECRET_KEY")
    if salt:
        return salt
    try:
        with open(DEFAULT_SALT_FILE, "r", encoding="utf-8") as salt_file:
            return salt_file.read().strip()
    except OSError:
        raise SystemExit(
            "Set DEVO_ANALYTICS_SALT or create ~/.devo-analytics-salt before importing."
        )


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("DEVO_ACCESS_LOG", DEFAULT_LOG)
    try:
        result = db.import_access_log(path, analytics_salt())
    except OSError as error:
        raise SystemExit(f"Could not import {path}: {error}")
    print(f"Imported {result['imported']} new request(s); skipped {result['skipped']} malformed line(s).")


if __name__ == "__main__":
    main()
