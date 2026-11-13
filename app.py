"""Solar Support website: public site + owner admin panel.

Run locally:      python manage.py run
Production (WSGI): passenger_wsgi.py (cPanel) or  gunicorn wsgi:app  (VPS)
"""
import json
import os
import re
import secrets
import smtplib
import sqlite3
import time
from datetime import datetime, timedelta
from email.message import EmailMessage
from functools import wraps
from pathlib import Path

from flask import (Flask, abort, flash, g, jsonify, redirect, render_template, request,
                   send_from_directory, session, url_for)
from markupsafe import Markup, escape
from werkzeug.security import check_password_hash, generate_password_hash

import seed

BASE = Path(__file__).parent.resolve()
IMG_EXT = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
VID_EXT = {".mp4", ".webm"}
CATEGORY_ORDER = ["Complete systems", "Components", "Testing and rental"]
GALLERY_CATS = ["Rooftops", "Homes", "Farms and water", "Energy storage", "Installation"]

SCHEMA = """
CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL, pw_hash TEXT NOT NULL, must_change INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS content(key TEXT PRIMARY KEY, grp TEXT, label TEXT, kind TEXT, value TEXT, sort INTEGER);
CREATE TABLE IF NOT EXISTS products(id INTEGER PRIMARY KEY, name TEXT NOT NULL, category TEXT, badge TEXT, summary TEXT, specs TEXT,
  price REAL, unit TEXT DEFAULT '', show_price INTEGER DEFAULT 1, inverter_kva REAL, battery_kwh REAL, pv_kwp REAL,
  image TEXT, sort INTEGER DEFAULT 100, active INTEGER DEFAULT 1);
CREATE TABLE IF NOT EXISTS projects(id INTEGER PRIMARY KEY, title TEXT NOT NULL, client TEXT, capacity_kw REAL, summary TEXT,
  image TEXT, period TEXT, sort INTEGER DEFAULT 100, active INTEGER DEFAULT 1);
CREATE TABLE IF NOT EXISTS media(id INTEGER PRIMARY KEY, path TEXT NOT NULL, kind TEXT NOT NULL, poster TEXT, title TEXT,
  category TEXT, show_in_gallery INTEGER DEFAULT 1, sort INTEGER DEFAULT 100);
CREATE TABLE IF NOT EXISTS quotes(id INTEGER PRIMARY KEY, created TEXT, name TEXT, phone TEXT, email TEXT, message TEXT,
  product TEXT, extra TEXT, ip TEXT, status TEXT DEFAULT 'new');
CREATE TABLE IF NOT EXISTS attempts(ip TEXT, ts REAL);
"""


def create_app(instance_dir=None):
    app = Flask(__name__, instance_path=str(instance_dir or os.environ.get("SOLAR_INSTANCE") or BASE / "instance"))
    Path(app.instance_path).mkdir(parents=True, exist_ok=True)
    (BASE / "static" / "uploads").mkdir(parents=True, exist_ok=True)

    key_file = Path(app.instance_path) / "secret.key"
    if not key_file.exists():
        key_file.write_text(secrets.token_hex(32))
        try:
            os.chmod(key_file, 0o600)
        except OSError:
            pass
    app.config.update(
        SECRET_KEY=key_file.read_text().strip(),
        DB_PATH=str(Path(app.instance_path) / "solar.db"),
        MAX_CONTENT_LENGTH=90 * 1024 * 1024,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=os.environ.get("SOLAR_HTTPS", "0") == "1",
        PERMANENT_SESSION_LIFETIME=timedelta(hours=8),
        TEMPLATES_AUTO_RELOAD=False,
    )

    # ------------------------------------------------------------------ database
    def get_db():
        if "db" not in g:
            g.db = sqlite3.connect(app.config["DB_PATH"])
            g.db.row_factory = sqlite3.Row
        return g.db

    @app.teardown_appcontext
    def close_db(_):
        db = g.pop("db", None)
        if db:
            db.close()

    def init_db():
        db = sqlite3.connect(app.config["DB_PATH"])
        db.row_factory = sqlite3.Row
        db.executescript(SCHEMA)
        if not db.execute("SELECT 1 FROM content LIMIT 1").fetchone():
            for i, (k, grp, label, kind, val) in enumerate(seed.CONTENT):
                db.execute("INSERT INTO content VALUES (?,?,?,?,?,?)", (k, grp, label, kind, val, i))
            for p in seed.PRODUCTS:
                db.execute("""INSERT INTO products(name,category,badge,summary,specs,price,unit,show_price,inverter_kva,battery_kwh,pv_kwp,image,sort)
                              VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""", p)
            for i, (t, c, kw, s, im, per) in enumerate(seed.PROJECTS):
                db.execute("INSERT INTO projects(title,client,capacity_kw,summary,image,period,sort) VALUES (?,?,?,?,?,?,?)",
                           (t, c, kw, s, im, per, i))
            for i, (f, t, cat) in enumerate(seed.GALLERY):
                db.execute("INSERT INTO media(path,kind,title,category,show_in_gallery,sort) VALUES (?,?,?,?,1,?)",
                           (f"img/{f}.jpg", "image", t, cat, i))
            for i, (v, po, t) in enumerate(seed.VIDEOS):
                db.execute("INSERT INTO media(path,kind,poster,title,category,show_in_gallery,sort) VALUES (?,?,?,?,?,1,?)",
                           (v, "video", po, t, "Video", i))
        # keep newly added default content keys available after upgrades
        have = {r["key"] for r in db.execute("SELECT key FROM content")}
        for i, (k, grp, label, kind, val) in enumerate(seed.CONTENT):
            if k not in have:
                db.execute("INSERT INTO content VALUES (?,?,?,?,?,?)", (k, grp, label, kind, val, i))
        if not db.execute("SELECT 1 FROM users LIMIT 1").fetchone():
            pw = os.environ.get("ADMIN_PASSWORD")
            must = 0
            if not pw:
                pw = secrets.token_urlsafe(9)
                (Path(app.instance_path) / "FIRST_LOGIN.txt").write_text(
                    f"Admin login for /admin\nUsername: admin\nPassword: {pw}\n\nYou will be asked to choose a new password at first login.\nDelete this file afterwards.\n")
                must = 1
                print(f"\n*** First admin login -> username: admin  password: {pw}  (also saved in instance/FIRST_LOGIN.txt)\n")
            db.execute("INSERT INTO users(username,pw_hash,must_change) VALUES (?,?,?)", ("admin", generate_password_hash(pw), must))
        db.commit()
        db.close()

    app.init_db = init_db
    init_db()

    # ------------------------------------------------------------------ helpers
    def content():
        if "content" not in g:
            g.content = {r["key"]: r["value"] for r in get_db().execute("SELECT key,value FROM content")}
        return g.content

    def c(key, default=""):
        return content().get(key, default) or default

    def asset(path):
        return url_for("static", filename=path) if path else ""

    def csrf_token():
        if "csrf" not in session:
            session["csrf"] = secrets.token_urlsafe(24)
        return session["csrf"]

    def money(v):
        if v is None:
            return ""
        return f"{v:,.0f}" if float(v).is_integer() else f"{v:,.2f}"

    def paras(text):
        parts = [p.strip() for p in re.split(r"\n\s*\n", text or "") if p.strip()]
        return Markup("".join(f"<p>{escape(p)}</p>" for p in parts))

    def split_title(text):
        return text

    app.jinja_env.globals.update(c=c, asset=asset, csrf_token=csrf_token, now=datetime.now)
    app.jinja_env.filters.update(money=money, paras=paras)

    @app.after_request
    def headers(resp):
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["X-Frame-Options"] = "SAMEORIGIN"
        resp.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        resp.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        resp.headers["Content-Security-Policy"] = (
            "default-src 'self'; img-src 'self' data: https:; media-src 'self' data:; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src 'self' https://fonts.gstatic.com; "
            "script-src 'self' 'unsafe-inline'; connect-src 'self'; frame-ancestors 'self'; base-uri 'self'; form-action 'self'")
        if request.path.startswith("/admin"):
            resp.headers["Cache-Control"] = "no-store"
        return resp

    def client_ip():
        return (request.headers.get("X-Forwarded-For", request.remote_addr or "") or "").split(",")[0].strip()

    @app.before_request
    def csrf_protect():
        if request.method == "POST" and request.path.startswith("/admin"):
            tok = request.form.get("_csrf", "")
            if not tok or not secrets.compare_digest(tok, session.get("csrf", "")):
                abort(400, "Your session expired. Please go back, refresh the page and try again.")

    def login_required(fn):
        @wraps(fn)
        def wrapper(*a, **kw):
            if not session.get("uid"):
                return redirect(url_for("login", next=request.path))
            if session.get("must_change") and request.endpoint not in ("account", "logout"):
                flash("Please choose a new password before continuing.", "warn")
                return redirect(url_for("account"))
            return fn(*a, **kw)
        return wrapper

    def library():
        out = []
        for folder, prefix in (("img", "img"), ("uploads", "uploads")):
            d = BASE / "static" / folder
            if d.exists():
                for f in sorted(d.iterdir()):
                    if f.suffix.lower() in IMG_EXT and not f.name.startswith(("logo", "favicon")):
                        out.append(f"{prefix}/{f.name}")
        return out

    def save_upload(file, kinds=("image",)):
        """Validate and store an uploaded file under static/uploads. Returns relative path or None."""
        if not file or not file.filename:
            return None
        ext = Path(file.filename).suffix.lower()
        allowed = set()
        if "image" in kinds:
            allowed |= IMG_EXT
        if "video" in kinds:
            allowed |= VID_EXT
        if ext not in allowed:
            flash(f"'{file.filename}' was skipped: only {', '.join(sorted(allowed))} files are allowed.", "warn")
            return None
        name = f"{datetime.now():%Y%m%d}-{secrets.token_hex(5)}{ext}"
        dest = BASE / "static" / "uploads" / name
        if ext in IMG_EXT:
            try:
                from PIL import Image, ImageOps
                im = ImageOps.exif_transpose(Image.open(file.stream))
                if ext in (".jpg", ".jpeg") or im.mode not in ("RGBA", "LA", "P"):
                    im = im.convert("RGB")
                    ext2 = ".jpg" if ext in (".jpg", ".jpeg") else ext
                    name = name.rsplit(".", 1)[0] + ext2
                    dest = BASE / "static" / "uploads" / name
                im.thumbnail((2200, 2200))
                if dest.suffix.lower() in (".jpg", ".jpeg"):
                    im.save(dest, quality=84, optimize=True)
                else:
                    im.save(dest)
            except Exception:
                flash(f"'{file.filename}' is not a valid image.", "warn")
                return None
        else:
            file.save(dest)
        return f"uploads/{name}"

    def remove_upload(path):
        if path and path.startswith("uploads/"):
            f = BASE / "static" / path
            if f.exists():
                try:
                    f.unlink()
                except OSError:
                    pass

    def notify(subject, body):
        host = os.environ.get("SMTP_HOST")
        if not host:
            return
        try:
            msg = EmailMessage()
            msg["Subject"], msg["From"] = subject, os.environ.get("SMTP_FROM", os.environ.get("SMTP_USER", ""))
            msg["To"] = os.environ.get("NOTIFY_TO", c("email"))
            msg.set_content(body)
            with smtplib.SMTP_SSL(host, int(os.environ.get("SMTP_PORT", "465")), timeout=10) as s:
                s.login(os.environ.get("SMTP_USER", ""), os.environ.get("SMTP_PASSWORD", ""))
                s.send_message(msg)
        except Exception as exc:  # never break the visitor's request over email
            app.logger.warning("Email notification failed: %s", exc)

    # ------------------------------------------------------------------ public site
    def build_public():
        db = get_db()
        products = []
        for r in db.execute("SELECT * FROM products WHERE active=1 ORDER BY sort,id"):
            p = dict(r)
            p["specs_list"] = [s.strip() for s in (p["specs"] or "").splitlines() if s.strip()]
            products.append(p)
        cats = [k for k in CATEGORY_ORDER if any(p["category"] == k for p in products)]
        cats += sorted({p["category"] for p in products if p["category"] not in cats and p["category"]})
        appliances = []
        for line in c("calc_appliances").splitlines():
            parts = [x.strip() for x in line.split("|")]
            if len(parts) in (3, 4):
                try:
                    appliances.append({"name": parts[0], "watts": float(parts[1]), "hours": float(parts[2]),
                                       "qty": int(float(parts[3])) if len(parts) == 4 and parts[3] else 0})
                except ValueError:
                    pass
        packages = [{"id": p["id"], "name": p["name"], "kva": p["inverter_kva"], "battery": p["battery_kwh"],
                     "pv": p["pv_kwp"], "price": p["price"] if p["show_price"] and p["price"] is not None else None,
                     "unit": p["unit"]}
                    for p in products if p["inverter_kva"] and p["battery_kwh"] and p["pv_kwp"]]
        packages.sort(key=lambda x: x["kva"])
        try:
            sun = float(c("calc_sun_hours", "5.5"))
        except ValueError:
            sun = 5.5
        gallery = [dict(r) for r in db.execute("SELECT * FROM media WHERE kind='image' AND show_in_gallery=1 ORDER BY sort,id")]
        videos = [dict(r) for r in db.execute("SELECT * FROM media WHERE kind='video' AND show_in_gallery=1 ORDER BY sort,id")]
        projects = [dict(r) for r in db.execute("SELECT * FROM projects WHERE active=1 ORDER BY sort,id")]
        brands = json.loads((BASE / "static" / "brands" / "brands.json").read_text()) if (BASE / "static" / "brands" / "brands.json").exists() else []
        slides = [(c(f"hero_img_{i}"), c(f"hero_cap_{i}")) for i in range(1, 6) if c(f"hero_img_{i}")]
        counters = [{"value": c(f"counter_{i}_value"), "suffix": c(f"counter_{i}_suffix"), "label": c(f"counter_{i}_label")}
                    for i in range(1, 5) if c(f"counter_{i}_value")]
        why = [(c(f"why_{i}_title"), c(f"why_{i}_text")) for i in range(1, 6) if c(f"why_{i}_title")]
        services = [(c(f"svc_{i}_title"), c(f"svc_{i}_text"), c(f"svc_{i}_img")) for i in range(1, 5)]
        gcats = [x for x in GALLERY_CATS if any(g_["category"] == x for g_ in gallery)]
        gcats += sorted({g_["category"] for g_ in gallery if g_["category"] and g_["category"] not in gcats})
        return dict(products=products, cats=cats, projects=projects, gallery=gallery, gcats=gcats, videos=videos,
                    brands=brands, slides=slides, counters=counters, why=why, services=services,
                    calc={"appliances": appliances, "packages": packages, "sun": sun},
                    phone_digits=re.sub(r"\D", "", c("whatsapp")))

    @app.route("/")
    def index():
        return render_template("index.html", **build_public())

    @app.route("/api/quote", methods=["POST"])
    def api_quote():
        origin = request.headers.get("Origin", "")
        if origin and not origin.endswith(request.host):
            abort(403)
        data = request.get_json(silent=True) or {}
        if data.get("website"):  # honeypot
            return jsonify(ok=True)
        name = str(data.get("name", "")).strip()[:120]
        phone = str(data.get("phone", "")).strip()[:40]
        email = str(data.get("email", "")).strip()[:160]
        message = str(data.get("message", "")).strip()[:3000]
        product = str(data.get("product", "")).strip()[:200]
        extra = str(data.get("extra", "")).strip()[:3000]
        if not name or not (phone or email) or len(message) < 3:
            return jsonify(ok=False, error="Please add your name, a phone number or email, and a short message."), 400
        if email and not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
            return jsonify(ok=False, error="That email address does not look right."), 400
        db = get_db()
        ip = client_ip()
        since = (datetime.now() - timedelta(hours=1)).isoformat(timespec="seconds")
        if db.execute("SELECT COUNT(*) FROM quotes WHERE ip=? AND created>?", (ip, since)).fetchone()[0] >= 8:
            return jsonify(ok=False, error="Too many requests. Please try again later or call us."), 429
        db.execute("INSERT INTO quotes(created,name,phone,email,message,product,extra,ip) VALUES (?,?,?,?,?,?,?,?)",
                   (datetime.now().isoformat(timespec="seconds"), name, phone, email, message, product, extra, ip))
        db.commit()
        notify(f"New website enquiry from {name}",
               f"Name: {name}\nPhone: {phone}\nEmail: {email}\nProduct: {product}\n\n{message}\n\n{extra}")
        return jsonify(ok=True)

    @app.route("/robots.txt")
    def robots():
        return "User-agent: *\nDisallow: /admin\nAllow: /\n", 200, {"Content-Type": "text/plain"}

    @app.errorhandler(404)
    def not_found(_):
        return render_template("error.html", code=404, msg="That page could not be found."), 404

    @app.errorhandler(400)
    def bad(e):
        return render_template("error.html", code=400, msg=getattr(e, "description", "Bad request.")), 400

    @app.errorhandler(413)
    def too_big(_):
        return render_template("error.html", code=413, msg="That upload is too large (limit 90 MB)."), 413

    # ------------------------------------------------------------------ admin auth
    @app.route("/admin/login", methods=["GET", "POST"])
    def login():
        if session.get("uid"):
            return redirect(url_for("dashboard"))
        error = None
        if request.method == "POST":
            db = get_db()
            ip = client_ip()
            db.execute("DELETE FROM attempts WHERE ts<?", (time.time() - 900,))
            if db.execute("SELECT COUNT(*) FROM attempts WHERE ip=?", (ip,)).fetchone()[0] >= 8:
                error = "Too many failed attempts. Please wait 15 minutes and try again."
            else:
                u = db.execute("SELECT * FROM users WHERE username=?", (request.form.get("username", "").strip(),)).fetchone()
                if u and check_password_hash(u["pw_hash"], request.form.get("password", "")):
                    session.clear()
                    session.permanent = True
                    session["uid"], session["user"], session["must_change"] = u["id"], u["username"], bool(u["must_change"])
                    csrf_token()
                    nxt = request.args.get("next", "")
                    return redirect(nxt if nxt.startswith("/admin") else url_for("dashboard"))
                db.execute("INSERT INTO attempts VALUES (?,?)", (ip, time.time()))
                db.commit()
                error = "Wrong username or password."
        return render_template("admin/login.html", error=error)

    @app.route("/admin/logout", methods=["POST"])
    def logout():
        session.clear()
        return redirect(url_for("login"))

    @app.route("/admin/account", methods=["GET", "POST"])
    @login_required
    def account():
        if request.method == "POST":
            db = get_db()
            u = db.execute("SELECT * FROM users WHERE id=?", (session["uid"],)).fetchone()
            new, again = request.form.get("new", ""), request.form.get("again", "")
            if not check_password_hash(u["pw_hash"], request.form.get("current", "")):
                flash("Your current password is not correct.", "err")
            elif len(new) < 10:
                flash("Choose a new password of at least 10 characters.", "err")
            elif new != again:
                flash("The two new passwords do not match.", "err")
            else:
                db.execute("UPDATE users SET pw_hash=?, must_change=0 WHERE id=?", (generate_password_hash(new), u["id"]))
                db.commit()
                session["must_change"] = False
                f = Path(app.instance_path) / "FIRST_LOGIN.txt"
                if f.exists():
                    f.unlink()
                flash("Password changed.", "ok")
                return redirect(url_for("dashboard"))
        return render_template("admin/account.html")

    # ------------------------------------------------------------------ admin pages
    @app.route("/admin")
    @login_required
    def dashboard():
        db = get_db()
        stats = {
            "products": db.execute("SELECT COUNT(*) FROM products WHERE active=1").fetchone()[0],
            "projects": db.execute("SELECT COUNT(*) FROM projects WHERE active=1").fetchone()[0],
            "photos": db.execute("SELECT COUNT(*) FROM media WHERE kind='image'").fetchone()[0],
            "videos": db.execute("SELECT COUNT(*) FROM media WHERE kind='video'").fetchone()[0],
            "new": db.execute("SELECT COUNT(*) FROM quotes WHERE status='new'").fetchone()[0],
        }
        recent = db.execute("SELECT * FROM quotes ORDER BY id DESC LIMIT 5").fetchall()
        return render_template("admin/dashboard.html", stats=stats, recent=recent)

    @app.route("/admin/prices", methods=["GET", "POST"])
    @login_required
    def prices():
        db = get_db()
        if request.method == "POST":
            n = 0
            for r in db.execute("SELECT id FROM products").fetchall():
                pid = r["id"]
                if f"name_{pid}" not in request.form:
                    continue
                raw = request.form.get(f"price_{pid}", "").replace(",", "").replace("$", "").strip()
                try:
                    price = float(raw) if raw else None
                except ValueError:
                    flash(f"'{raw}' is not a valid price and was skipped.", "warn")
                    continue
                db.execute("UPDATE products SET price=?, unit=?, show_price=?, active=? WHERE id=?",
                           (price, request.form.get(f"unit_{pid}", "").strip()[:30],
                            1 if request.form.get(f"show_{pid}") else 0, 1 if request.form.get(f"active_{pid}") else 0, pid))
                n += 1
            db.commit()
            flash(f"Saved. {n} products updated and live on the website.", "ok")
            return redirect(url_for("prices"))
        rows = db.execute("SELECT * FROM products ORDER BY sort,id").fetchall()
        return render_template("admin/prices.html", rows=rows)

    def product_from_form(db, pid=None):
        f = request.form
        def num(k):
            v = f.get(k, "").replace(",", "").strip()
            try:
                return float(v) if v else None
            except ValueError:
                return None
        cat = f.get("category_new", "").strip() or f.get("category", "")
        old = db.execute("SELECT image FROM products WHERE id=?", (pid,)).fetchone() if pid else None
        image = old["image"] if old else ""
        up = save_upload(request.files.get("image_file"))
        if up:
            image = up
        elif f.get("image_choice"):
            image = f.get("image_choice")
        vals = (f.get("name", "").strip()[:160], cat[:60], f.get("badge", "").strip()[:30], f.get("summary", "").strip()[:300],
                f.get("specs", "").strip()[:3000], num("price"), f.get("unit", "").strip()[:30],
                1 if f.get("show_price") else 0, num("inverter_kva"), num("battery_kwh"), num("pv_kwp"), image,
                int(num("sort") or 100), 1 if f.get("active") else 0)
        if not vals[0]:
            flash("A product name is required.", "err")
            return None
        if pid:
            db.execute("""UPDATE products SET name=?,category=?,badge=?,summary=?,specs=?,price=?,unit=?,show_price=?,
                          inverter_kva=?,battery_kwh=?,pv_kwp=?,image=?,sort=?,active=? WHERE id=?""", vals + (pid,))
        else:
            db.execute("""INSERT INTO products(name,category,badge,summary,specs,price,unit,show_price,inverter_kva,
                          battery_kwh,pv_kwp,image,sort,active) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", vals)
        db.commit()
        return True

    @app.route("/admin/products")
    @login_required
    def products_list():
        return render_template("admin/products.html", rows=get_db().execute("SELECT * FROM products ORDER BY sort,id").fetchall())

    @app.route("/admin/products/new", methods=["GET", "POST"])
    @app.route("/admin/products/<int:pid>", methods=["GET", "POST"])
    @login_required
    def product_edit(pid=None):
        db = get_db()
        row = db.execute("SELECT * FROM products WHERE id=?", (pid,)).fetchone() if pid else None
        if pid and not row:
            abort(404)
        if request.method == "POST":
            if product_from_form(db, pid):
                flash("Product saved.", "ok")
                return redirect(url_for("products_list"))
        cats = sorted({r[0] for r in db.execute("SELECT DISTINCT category FROM products") if r[0]} | set(CATEGORY_ORDER))
        return render_template("admin/product_form.html", p=row, cats=cats, lib=library())

    @app.route("/admin/products/<int:pid>/delete", methods=["POST"])
    @login_required
    def product_delete(pid):
        db = get_db()
        r = db.execute("SELECT image FROM products WHERE id=?", (pid,)).fetchone()
        if r:
            remove_upload(r["image"])
            db.execute("DELETE FROM products WHERE id=?", (pid,))
            db.commit()
            flash("Product deleted.", "ok")
        return redirect(url_for("products_list"))

    @app.route("/admin/projects")
    @login_required
    def projects_list():
        return render_template("admin/projects.html", rows=get_db().execute("SELECT * FROM projects ORDER BY sort,id").fetchall())

    @app.route("/admin/projects/new", methods=["GET", "POST"])
    @app.route("/admin/projects/<int:pid>", methods=["GET", "POST"])
    @login_required
    def project_edit(pid=None):
        db = get_db()
        row = db.execute("SELECT * FROM projects WHERE id=?", (pid,)).fetchone() if pid else None
        if pid and not row:
            abort(404)
        if request.method == "POST":
            f = request.form
            try:
                kw = float(f.get("capacity_kw", "").replace(",", "")) if f.get("capacity_kw", "").strip() else None
            except ValueError:
                kw = None
            image = row["image"] if row else ""
            up = save_upload(request.files.get("image_file"))
            if up:
                image = up
            elif f.get("image_choice"):
                image = f.get("image_choice")
            vals = (f.get("title", "").strip()[:160], f.get("client", "").strip()[:160], kw, f.get("summary", "").strip()[:1000],
                    image, f.get("period", "").strip()[:40], int(f.get("sort") or 100) if str(f.get("sort", "")).isdigit() else 100,
                    1 if f.get("active") else 0)
            if not vals[0]:
                flash("A project title is required.", "err")
            else:
                if pid:
                    db.execute("UPDATE projects SET title=?,client=?,capacity_kw=?,summary=?,image=?,period=?,sort=?,active=? WHERE id=?", vals + (pid,))
                else:
                    db.execute("INSERT INTO projects(title,client,capacity_kw,summary,image,period,sort,active) VALUES (?,?,?,?,?,?,?,?)", vals)
                db.commit()
                flash("Project saved.", "ok")
                return redirect(url_for("projects_list"))
        return render_template("admin/project_form.html", p=row, lib=library())

    @app.route("/admin/projects/<int:pid>/delete", methods=["POST"])
    @login_required
    def project_delete(pid):
        db = get_db()
        r = db.execute("SELECT image FROM projects WHERE id=?", (pid,)).fetchone()
        if r:
            remove_upload(r["image"])
            db.execute("DELETE FROM projects WHERE id=?", (pid,))
            db.commit()
            flash("Project deleted.", "ok")
        return redirect(url_for("projects_list"))

    @app.route("/admin/media", methods=["GET", "POST"])
    @login_required
    def media():
        db = get_db()
        if request.method == "POST":
            cat = request.form.get("category", "Installation")
            added = 0
            for f in request.files.getlist("files"):
                kind = "video" if Path(f.filename or "").suffix.lower() in VID_EXT else "image"
                p = save_upload(f, kinds=("image", "video"))
                if p:
                    title = request.form.get("title", "").strip() or Path(f.filename).stem.replace("_", " ").replace("-", " ").title()[:80]
                    db.execute("INSERT INTO media(path,kind,title,category,show_in_gallery,sort) VALUES (?,?,?,?,1,?)",
                               (p, kind, title, cat if kind == "image" else "Video", 0))
                    added += 1
            db.commit()
            if added:
                flash(f"{added} file(s) uploaded and added to the website gallery.", "ok")
            return redirect(url_for("media"))
        rows = db.execute("SELECT * FROM media ORDER BY kind, sort, id").fetchall()
        return render_template("admin/media.html", rows=rows, cats=GALLERY_CATS)

    @app.route("/admin/media/<int:mid>", methods=["POST"])
    @login_required
    def media_update(mid):
        db = get_db()
        action = request.form.get("action")
        r = db.execute("SELECT * FROM media WHERE id=?", (mid,)).fetchone()
        if not r:
            abort(404)
        if action == "delete":
            remove_upload(r["path"])
            remove_upload(r["poster"])
            db.execute("DELETE FROM media WHERE id=?", (mid,))
            flash("Removed.", "ok")
        else:
            db.execute("UPDATE media SET title=?, category=?, show_in_gallery=? WHERE id=?",
                       (request.form.get("title", "").strip()[:100], request.form.get("category", r["category"]),
                        1 if request.form.get("show") else 0, mid))
            flash("Saved.", "ok")
        db.commit()
        return redirect(url_for("media"))

    @app.route("/admin/content", methods=["GET", "POST"])
    @login_required
    def content_edit():
        db = get_db()
        rows = db.execute("SELECT * FROM content ORDER BY sort").fetchall()
        if request.method == "POST":
            for r in rows:
                k = r["key"]
                if r["kind"] == "image":
                    up = save_upload(request.files.get(f"file__{k}"))
                    if up:
                        db.execute("UPDATE content SET value=? WHERE key=?", (up, k))
                    elif request.form.get(f"choice__{k}"):
                        db.execute("UPDATE content SET value=? WHERE key=?", (request.form[f"choice__{k}"], k))
                elif k in request.form:
                    v = request.form[k].strip()
                    if r["kind"] == "url" and v and not v.startswith(("http://", "https://")):
                        flash(f"'{r['label']}' must start with https:// and was not changed.", "warn")
                        continue
                    db.execute("UPDATE content SET value=? WHERE key=?", (v[:6000], k))
            db.commit()
            flash("Website content saved. Changes are live now.", "ok")
            return redirect(url_for("content_edit", _anchor=request.form.get("group", "")))
        groups = {}
        for r in rows:
            groups.setdefault(r["grp"], []).append(r)
        return render_template("admin/content.html", groups=groups, lib=library())

    @app.route("/admin/quotes", methods=["GET", "POST"])
    @login_required
    def quotes():
        db = get_db()
        if request.method == "POST":
            qid = int(request.form.get("id", 0))
            if request.form.get("action") == "delete":
                db.execute("DELETE FROM quotes WHERE id=?", (qid,))
            else:
                db.execute("UPDATE quotes SET status=? WHERE id=?", ("done" if request.form.get("action") == "done" else "new", qid))
            db.commit()
            return redirect(url_for("quotes"))
        return render_template("admin/quotes.html", rows=db.execute("SELECT * FROM quotes ORDER BY id DESC").fetchall())

    return app


app = create_app()
