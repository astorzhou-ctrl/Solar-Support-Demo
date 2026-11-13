#!/usr/bin/env python3
"""Small command-line helper.

  python manage.py run                 start the website on http://localhost:5000
  python manage.py set-password        set or reset the admin password (asks you to type it)
  python manage.py reset-demo          (careful) delete the database and start again with the default content
"""
import getpass
import os
import sys

from werkzeug.security import generate_password_hash

from app import app


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "run"
    if cmd == "run":
        app.run(host=os.environ.get("HOST", "127.0.0.1"), port=int(os.environ.get("PORT", "5000")), debug=False)
    elif cmd == "set-password":
        import sqlite3
        pw = getpass.getpass("New admin password (min 10 characters): ")
        if len(pw) < 10 or pw != getpass.getpass("Type it again: "):
            sys.exit("Passwords did not match or were too short.")
        db = sqlite3.connect(app.config["DB_PATH"])
        db.execute("UPDATE users SET pw_hash=?, must_change=0 WHERE username='admin'", (generate_password_hash(pw),))
        db.commit()
        print("Admin password updated.")
    elif cmd == "reset-demo":
        if input("This DELETES all products, prices, uploads and quotes. Type YES to continue: ") == "YES":
            os.remove(app.config["DB_PATH"])
            app.init_db()
            print("Database recreated.")
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
