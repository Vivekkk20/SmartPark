from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, session
from functools import wraps
from contextlib import contextmanager
from werkzeug.security import generate_password_hash, check_password_hash
import sqlite3
from datetime import datetime
from pathlib import Path
import math
import uuid
import os

app = Flask(__name__)
app.secret_key = os.environ.get("SMARTPARK_SECRET_KEY", "smartpark-demo-secret-change-before-deployment")
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
DB_PATH = Path(__file__).with_name("smartpark.db")
TOTAL_SLOTS = 12
HOURLY_RATE = 20  # demo rate in INR; editable via settings

# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------

@contextmanager
def db():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    try:
        with con:
            yield con
    finally:
        con.close()


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("user_id"):
            flash("Please log in to continue.", "error")
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped


def admin_required(view):
    @wraps(view)
    @login_required
    def wrapped(*args, **kwargs):
        if session.get("role") != "admin":
            flash("Admin access is required for that page.", "error")
            return redirect(url_for("dashboard"))
        return view(*args, **kwargs)
    return wrapped


def init_db():
    with db() as con:
        con.execute("""CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            full_name TEXT NOT NULL,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'user',
            created_at TEXT NOT NULL
        )""")
        con.execute("""CREATE TABLE IF NOT EXISTS slots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            slot_code TEXT UNIQUE NOT NULL,
            category TEXT NOT NULL DEFAULT 'four_wheeler',
            status TEXT NOT NULL DEFAULT 'available'
        )""")
        con.execute("""CREATE TABLE IF NOT EXISTS sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            customer_name TEXT NOT NULL,
            vehicle_number TEXT NOT NULL,
            vehicle_category TEXT NOT NULL DEFAULT 'four_wheeler',
            slot_code TEXT NOT NULL,
            entry_time TEXT NOT NULL,
            exit_time TEXT,
            duration_minutes INTEGER,
            amount REAL,
            advance_amount REAL DEFAULT 0,
            advance_method TEXT DEFAULT 'none',
            advance_status TEXT DEFAULT 'none',
            payment_method TEXT DEFAULT 'cash',
            refund_amount REAL DEFAULT 0,
            demo_adjusted INTEGER DEFAULT 0,
            payment_status TEXT NOT NULL DEFAULT 'unpaid',
            status TEXT NOT NULL DEFAULT 'active',
            receipt_number TEXT
        )""")
        con.execute("""CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY, value TEXT NOT NULL
        )""")
        con.execute("""CREATE TABLE IF NOT EXISTS activity_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_type TEXT NOT NULL,
            description TEXT NOT NULL,
            vehicle_number TEXT,
            slot_code TEXT,
            user_id INTEGER,
            created_at TEXT NOT NULL
        )""")

        # Safe migrations for databases created by earlier versions
        sess_cols = [row["name"] for row in con.execute("PRAGMA table_info(sessions)").fetchall()]
        if "user_id" not in sess_cols:
            con.execute("ALTER TABLE sessions ADD COLUMN user_id INTEGER")
        if "receipt_number" not in sess_cols:
            con.execute("ALTER TABLE sessions ADD COLUMN receipt_number TEXT")
        if "vehicle_category" not in sess_cols:
            con.execute("ALTER TABLE sessions ADD COLUMN vehicle_category TEXT DEFAULT 'four_wheeler'")
        if "advance_amount" not in sess_cols:
            con.execute("ALTER TABLE sessions ADD COLUMN advance_amount REAL DEFAULT 0")
        if "advance_method" not in sess_cols:
            con.execute("ALTER TABLE sessions ADD COLUMN advance_method TEXT DEFAULT 'none'")
        if "advance_status" not in sess_cols:
            con.execute("ALTER TABLE sessions ADD COLUMN advance_status TEXT DEFAULT 'none'")
        if "payment_method" not in sess_cols:
            con.execute("ALTER TABLE sessions ADD COLUMN payment_method TEXT DEFAULT 'cash'")
        if "refund_amount" not in sess_cols:
            con.execute("ALTER TABLE sessions ADD COLUMN refund_amount REAL DEFAULT 0")
        if "demo_adjusted" not in sess_cols:
            con.execute("ALTER TABLE sessions ADD COLUMN demo_adjusted INTEGER DEFAULT 0")

        slot_cols = [row["name"] for row in con.execute("PRAGMA table_info(slots)").fetchall()]
        if "category" not in slot_cols:
            con.execute("ALTER TABLE slots ADD COLUMN category TEXT DEFAULT 'four_wheeler'")
            # Standard documented mapping: S01-S06 Two-Wheeler, S07-S12 Four-Wheeler
            con.execute("UPDATE slots SET category='two_wheeler' WHERE slot_code IN ('S01','S02','S03','S04','S05','S06')")
            con.execute("UPDATE slots SET category='four_wheeler' WHERE slot_code IN ('S07','S08','S09','S10','S11','S12')")

        # Seed or sync admin credentials securely
        admin_pwd = os.environ.get("SMARTPARK_ADMIN_PASSWORD", "Pass@123")
        admin = con.execute("SELECT id, password_hash FROM users WHERE username='admin'").fetchone()
        if not admin:
            con.execute(
                "INSERT INTO users(username,full_name,password_hash,role,created_at) VALUES(?,?,?,?,?)",
                ("admin", "SmartPark Administrator", generate_password_hash(admin_pwd), "admin",
                 datetime.now().isoformat(timespec="seconds")),
            )
        else:
            if not check_password_hash(admin["password_hash"], admin_pwd):
                con.execute(
                    "UPDATE users SET password_hash=? WHERE id=?",
                    (generate_password_hash(admin_pwd), admin["id"]),
                )

        # Seed slots if not present
        for i in range(1, TOTAL_SLOTS + 1):
            code = f"S{i:02}"
            cat = "two_wheeler" if i <= 6 else "four_wheeler"
            con.execute("INSERT OR IGNORE INTO slots(slot_code,category,status) VALUES(?, ?, 'available')", (code, cat))

        # Seed settings
        con.execute("INSERT OR IGNORE INTO settings(key,value) VALUES('rate_two_wheeler','10')")
        con.execute("INSERT OR IGNORE INTO settings(key,value) VALUES('rate_four_wheeler','20')")
        con.execute("INSERT OR IGNORE INTO settings(key,value) VALUES('hourly_rate',?)", (str(HOURLY_RATE),))
        con.execute("INSERT OR IGNORE INTO settings(key,value) VALUES('demo_extra_minutes','0')")


# ---------------------------------------------------------------------------
# Stats & rate helpers
# ---------------------------------------------------------------------------

def get_rates():
    with db() as con:
        r2 = con.execute("SELECT value FROM settings WHERE key='rate_two_wheeler'").fetchone()
        r4 = con.execute("SELECT value FROM settings WHERE key='rate_four_wheeler'").fetchone()
    try:
        rate_2w = max(0.0, float(r2["value"])) if r2 else 10.0
    except (TypeError, ValueError):
        rate_2w = 10.0
    try:
        rate_4w = max(0.0, float(r4["value"])) if r4 else 20.0
    except (TypeError, ValueError):
        rate_4w = 20.0
    return {"two_wheeler": rate_2w, "four_wheeler": rate_4w}


def get_rate_for_category(category):
    rates = get_rates()
    return rates.get(category, rates["four_wheeler"])


def get_rate():
    return get_rates()["four_wheeler"]


def get_demo_extra_minutes():
    with db() as con:
        row = con.execute("SELECT value FROM settings WHERE key='demo_extra_minutes'").fetchone()
    try:
        return int(row["value"]) if row else 0
    except (TypeError, ValueError):
        return 0


def get_stats():
    with db() as con:
        total = con.execute("SELECT COUNT(*) n FROM slots").fetchone()["n"]
        occupied = con.execute("SELECT COUNT(*) n FROM slots WHERE status='occupied'").fetchone()["n"]
        active = con.execute("SELECT COUNT(*) n FROM sessions WHERE status='active'").fetchone()["n"]

        tw_total = con.execute("SELECT COUNT(*) n FROM slots WHERE category='two_wheeler'").fetchone()["n"]
        tw_occ = con.execute("SELECT COUNT(*) n FROM slots WHERE category='two_wheeler' AND status='occupied'").fetchone()["n"]
        tw_active = con.execute("SELECT COUNT(*) n FROM sessions WHERE status='active' AND vehicle_category='two_wheeler'").fetchone()["n"]

        fw_total = con.execute("SELECT COUNT(*) n FROM slots WHERE category='four_wheeler'").fetchone()["n"]
        fw_occ = con.execute("SELECT COUNT(*) n FROM slots WHERE category='four_wheeler' AND status='occupied'").fetchone()["n"]
        fw_active = con.execute("SELECT COUNT(*) n FROM sessions WHERE status='active' AND vehicle_category='four_wheeler'").fetchone()["n"]

        today = datetime.now().strftime("%Y-%m-%d")
        revenue = con.execute(
            """SELECT COALESCE(SUM(amount),0) n FROM sessions
               WHERE status='completed' AND substr(exit_time,1,10)=? AND payment_status='paid'""",
            (today,),
        ).fetchone()["n"]
        completed_today = con.execute(
            "SELECT COUNT(*) n FROM sessions WHERE status='completed' AND substr(exit_time,1,10)=?",
            (today,),
        ).fetchone()["n"]
    return {
        "total": total,
        "occupied": occupied,
        "available": total - occupied,
        "active": active,
        "revenue": revenue,
        "completed_today": completed_today,
        "two_wheeler": {
            "total": tw_total,
            "occupied": tw_occ,
            "available": tw_total - tw_occ,
            "active": tw_active,
        },
        "four_wheeler": {
            "total": fw_total,
            "occupied": fw_occ,
            "available": fw_total - fw_occ,
            "active": fw_active,
        },
    }


def user_stats(user_id):
    with db() as con:
        total = con.execute("SELECT COUNT(*) n FROM slots").fetchone()["n"]
        occupied = con.execute("SELECT COUNT(*) n FROM slots WHERE status='occupied'").fetchone()["n"]
        active = con.execute(
            "SELECT COUNT(*) n FROM sessions WHERE status='active' AND user_id=?", (user_id,)
        ).fetchone()["n"]

        tw_total = con.execute("SELECT COUNT(*) n FROM slots WHERE category='two_wheeler'").fetchone()["n"]
        tw_occ = con.execute("SELECT COUNT(*) n FROM slots WHERE category='two_wheeler' AND status='occupied'").fetchone()["n"]
        tw_active = con.execute(
            "SELECT COUNT(*) n FROM sessions WHERE status='active' AND user_id=? AND vehicle_category='two_wheeler'",
            (user_id,)
        ).fetchone()["n"]

        fw_total = con.execute("SELECT COUNT(*) n FROM slots WHERE category='four_wheeler'").fetchone()["n"]
        fw_occ = con.execute("SELECT COUNT(*) n FROM slots WHERE category='four_wheeler' AND status='occupied'").fetchone()["n"]
        fw_active = con.execute(
            "SELECT COUNT(*) n FROM sessions WHERE status='active' AND user_id=? AND vehicle_category='four_wheeler'",
            (user_id,)
        ).fetchone()["n"]

        today = datetime.now().strftime("%Y-%m-%d")
        revenue = con.execute(
            """SELECT COALESCE(SUM(amount),0) n FROM sessions
               WHERE user_id=? AND status='completed' AND substr(exit_time,1,10)=? AND payment_status='paid'""",
            (user_id, today),
        ).fetchone()["n"]
        completed_today = con.execute(
            "SELECT COUNT(*) n FROM sessions WHERE user_id=? AND status='completed' AND substr(exit_time,1,10)=?",
            (user_id, today),
        ).fetchone()["n"]
    return {
        "total": total,
        "occupied": occupied,
        "available": total - occupied,
        "active": active,
        "revenue": revenue,
        "completed_today": completed_today,
        "two_wheeler": {
            "total": tw_total,
            "occupied": tw_occ,
            "available": tw_total - tw_occ,
            "active": tw_active,
        },
        "four_wheeler": {
            "total": fw_total,
            "occupied": fw_occ,
            "available": fw_total - fw_occ,
            "active": fw_active,
        },
    }


def log_activity(event_type, description, vehicle_number=None, slot_code=None, user_id=None):
    """Append an event to the activity log (best-effort; never crashes the caller)."""
    try:
        with db() as con:
            con.execute(
                "INSERT INTO activity_log(event_type,description,vehicle_number,slot_code,user_id,created_at) VALUES(?,?,?,?,?,?)",
                (event_type, description, vehicle_number, slot_code, user_id,
                 datetime.now().isoformat(timespec="seconds")),
            )
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Auth routes
# ---------------------------------------------------------------------------

@app.route("/login", methods=["GET", "POST"])
def login():
    if session.get("user_id"):
        return redirect(url_for("dashboard"))
    if request.method == "POST":
        username = request.form.get("username", "").strip().lower()
        password = request.form.get("password", "")
        with db() as con:
            user = con.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
            if user and user["role"] == "admin":
                admin_pwd = os.environ.get("SMARTPARK_ADMIN_PASSWORD", "Pass@123")
                if not check_password_hash(user["password_hash"], admin_pwd):
                    con.execute(
                        "UPDATE users SET password_hash=? WHERE id=?",
                        (generate_password_hash(admin_pwd), user["id"]),
                    )
                    user = con.execute("SELECT * FROM users WHERE id=?", (user["id"],)).fetchone()

        if user and check_password_hash(user["password_hash"], password):
            session.clear()
            session["user_id"] = user["id"]
            session["username"] = user["username"]
            session["full_name"] = user["full_name"]
            session["role"] = user["role"]
            flash(f"Welcome, {user['full_name']}!", "success")
            return redirect(url_for("dashboard"))
        flash("Invalid username or password.", "error")
    return render_template("login.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if session.get("user_id"):
        return redirect(url_for("dashboard"))
    if request.method == "POST":
        full_name = request.form.get("full_name", "").strip()
        username = request.form.get("username", "").strip().lower()
        password = request.form.get("password", "")
        if not full_name or not username or len(username) < 3 or len(password) < 8:
            flash("Enter your name, a username (at least 3 characters), and a password (at least 8 characters).", "error")
            return redirect(url_for("register"))
        try:
            with db() as con:
                con.execute(
                    "INSERT INTO users(username,full_name,password_hash,role,created_at) VALUES(?,?,?,?,?)",
                    (username, full_name, generate_password_hash(password), "user",
                     datetime.now().isoformat(timespec="seconds")),
                )
        except sqlite3.IntegrityError:
            flash("That username is already taken. Choose another.", "error")
            return redirect(url_for("register"))
        flash("Account created. You can now log in.", "success")
        return redirect(url_for("login"))
    return render_template("register.html")


@app.route("/logout", methods=["POST"])
@login_required
def logout():
    session.clear()
    flash("You have been logged out.", "success")
    return redirect(url_for("login"))


# ---------------------------------------------------------------------------
# Main application routes
# ---------------------------------------------------------------------------

@app.route("/")
@login_required
def dashboard():
    with db() as con:
        slots = [dict(r) for r in con.execute("SELECT * FROM slots ORDER BY slot_code").fetchall()]
        if session.get("role") == "admin":
            active = con.execute(
                "SELECT * FROM sessions WHERE status='active' ORDER BY entry_time DESC"
            ).fetchall()
            recent = con.execute("SELECT * FROM sessions ORDER BY id DESC LIMIT 8").fetchall()
        else:
            active = con.execute(
                "SELECT * FROM sessions WHERE status='active' AND user_id=? ORDER BY entry_time DESC",
                (session["user_id"],),
            ).fetchall()
            recent = con.execute(
                "SELECT * FROM sessions WHERE user_id=? ORDER BY id DESC LIMIT 8",
                (session["user_id"],),
            ).fetchall()
        activity = con.execute(
            "SELECT * FROM activity_log ORDER BY id DESC LIMIT 12"
        ).fetchall()
    stats = get_stats() if session.get("role") == "admin" else user_stats(session["user_id"])
    return render_template(
        "dashboard.html",
        stats=stats,
        slots=slots,
        active=active,
        recent=recent,
        rates=get_rates(),
        rate=get_rate(),
        activity=activity,
        demo_extra=get_demo_extra_minutes(),
    )


@app.route("/entry", methods=["GET", "POST"])
@login_required
def entry():
    with db() as con:
        available_slots = con.execute(
            "SELECT slot_code, category FROM slots WHERE status='available' ORDER BY slot_code"
        ).fetchall()
    rates = get_rates()

    if request.method == "POST":
        name = request.form.get("customer_name", "").strip()
        vehicle = request.form.get("vehicle_number", "").strip().upper()
        category = request.form.get("vehicle_category", "four_wheeler").strip()
        chosen = request.form.get("slot_code", "").strip()
        advance_input = request.form.get("advance_amount", "0").strip()
        advance_method = request.form.get("advance_method", "cash").strip()

        if not name or not vehicle:
            flash("Customer name and vehicle number are required.", "error")
            return redirect(url_for("entry"))

        if category not in ("two_wheeler", "four_wheeler"):
            flash("Invalid vehicle category selected.", "error")
            return redirect(url_for("entry"))

        try:
            advance_amount = max(0.0, float(advance_input or 0))
        except ValueError:
            flash("Enter a valid advance payment amount (or 0).", "error")
            return redirect(url_for("entry"))

        cat_label = "Two-Wheeler" if category == "two_wheeler" else "Four-Wheeler"

        with db() as con:
            # If auto-assign, find first available slot strictly in this category
            if chosen == "AUTO" or not chosen:
                row = con.execute(
                    "SELECT slot_code FROM slots WHERE status='available' AND category=? ORDER BY slot_code LIMIT 1",
                    (category,)
                ).fetchone()
                chosen = row["slot_code"] if row else None

            if not chosen:
                flash(f"Parking is FULL for {cat_label}s! No slots currently available.", "error")
                return redirect(url_for("entry"))

            # Verify slot matches category and is available
            slot = con.execute(
                "SELECT slot_code, category, status FROM slots WHERE slot_code=?", (chosen,)
            ).fetchone()
            if not slot or slot["status"] != "available":
                flash(f"Slot {chosen} is no longer available. Please select another slot.", "error")
                return redirect(url_for("entry"))
            if slot["category"] != category:
                flash(f"Category mismatch: Slot {chosen} is for {slot['category'].replace('_', ' ').title()}, not {cat_label}.", "error")
                return redirect(url_for("entry"))

            # Atomic slot reservation
            rows_updated = con.execute(
                "UPDATE slots SET status='occupied' WHERE slot_code=? AND status='available' AND category=?",
                (chosen, category),
            ).rowcount
            if rows_updated == 0:
                flash("Slot assignment collision. Please try again.", "error")
                return redirect(url_for("entry"))

            now = datetime.now().isoformat(timespec="seconds")
            adv_status = "paid" if advance_amount > 0 else "none"
            adv_method = advance_method if advance_amount > 0 else "none"

            con.execute(
                """INSERT INTO sessions(user_id, customer_name, vehicle_number, vehicle_category,
                                        slot_code, entry_time, advance_amount, advance_method,
                                        advance_status, status, payment_status)
                   VALUES(?,?,?,?,?,?,?,?,?,'active','unpaid')""",
                (session["user_id"], name, vehicle, category, chosen, now,
                 advance_amount, adv_method, adv_status),
            )

        adv_note = f" (Advance: ₹{advance_amount:.2f} via {adv_method.upper()})" if advance_amount > 0 else ""
        log_activity(
            "entry",
            f"{vehicle} ({cat_label}) parked in {chosen}{adv_note}",
            vehicle,
            chosen,
            session["user_id"],
        )
        flash(f"Vehicle checked in successfully! Assigned slot {chosen} for {cat_label}.{adv_note}", "success")
        return redirect(url_for("dashboard"))

    return render_template("entry.html", available=available_slots, rates=rates)


@app.route("/exit/<int:session_id>", methods=["GET", "POST"])
@login_required
def exit_vehicle(session_id):
    extra_minutes = get_demo_extra_minutes()
    with db() as con:
        if session.get("role") == "admin":
            record = con.execute(
                "SELECT * FROM sessions WHERE id=? AND status='active'", (session_id,)
            ).fetchone()
        else:
            record = con.execute(
                "SELECT * FROM sessions WHERE id=? AND status='active' AND user_id=?",
                (session_id, session["user_id"]),
            ).fetchone()

    if not record:
        flash("Active parking session not found or access denied.", "error")
        return redirect(url_for("dashboard"))

    category = record["vehicle_category"] or "four_wheeler"
    rate = get_rate_for_category(category)
    entry_dt = datetime.fromisoformat(record["entry_time"])
    real_minutes = math.ceil((datetime.now() - entry_dt).total_seconds() / 60)
    minutes = max(1, real_minutes + extra_minutes)
    hours = max(1, math.ceil(minutes / 60))
    total_amount = round(hours * rate, 2)
    advance_paid = float(record["advance_amount"] or 0)
    balance_due = round(max(0.0, total_amount - advance_paid), 2)
    refund_due = round(max(0.0, advance_paid - total_amount), 2)
    is_demo_adjusted = extra_minutes != 0

    if request.method == "POST":
        action = request.form.get("action", "complete_exit")
        payment_method = request.form.get("payment_method", "cash")

        if action == "simulate_qr_fail":
            log_activity(
                "payment_fail",
                f"Simulated Online Demo QR payment failed for {record['vehicle_number']} (Balance ₹{balance_due:.2f})",
                record["vehicle_number"],
                record["slot_code"],
                session["user_id"],
            )
            flash("Simulated Online Demo Payment failed (Declined by demo simulator). Please retry or choose Cash.", "error")
            return redirect(url_for("exit_vehicle", session_id=session_id))

        if action == "complete_exit":
            if balance_due == 0:
                payment_method = "advance_settled"
            elif payment_method not in ("cash", "qr_demo"):
                payment_method = "cash"

            exit_time = datetime.now().isoformat(timespec="seconds")
            receipt_number = "RCP-" + uuid.uuid4().hex[:8].upper()

            with db() as con:
                rows_updated = con.execute(
                    """UPDATE sessions
                       SET exit_time=?, duration_minutes=?, amount=?, payment_status='paid',
                           payment_method=?, refund_amount=?, demo_adjusted=?,
                           status='completed', receipt_number=?
                       WHERE id=? AND status='active'""",
                    (exit_time, minutes, total_amount, payment_method, refund_due,
                     1 if is_demo_adjusted else 0, receipt_number, session_id),
                ).rowcount
                if rows_updated == 0:
                    flash("This session was already exited.", "error")
                    return redirect(url_for("dashboard"))
                con.execute("UPDATE slots SET status='available' WHERE slot_code=?", (record["slot_code"],))

            pay_desc = f"₹{balance_due:.2f} via {payment_method.upper()}" if balance_due > 0 else "Fully covered by advance"
            refund_desc = f" (Refund: ₹{refund_due:.2f})" if refund_due > 0 else ""
            log_activity(
                "exit",
                f"{record['vehicle_number']} exited from {record['slot_code']} — Total: ₹{total_amount:.2f} [{pay_desc}{refund_desc}]",
                record["vehicle_number"],
                record["slot_code"],
                session["user_id"],
            )
            flash(f"Exit completed for {record['vehicle_number']}. Receipt {receipt_number} generated.", "success")
            return redirect(url_for("receipt", session_id=session_id))

    return render_template(
        "exit.html",
        parking_session=record,
        category=category,
        minutes=minutes,
        real_minutes=real_minutes,
        hours=hours,
        total_amount=total_amount,
        advance_paid=advance_paid,
        balance_due=balance_due,
        refund_due=refund_due,
        rate=rate,
        is_demo_adjusted=is_demo_adjusted,
        extra_minutes=extra_minutes,
    )


@app.route("/history")
@login_required
def history():
    q = request.args.get("q", "").strip()
    with db() as con:
        if session.get("role") == "admin":
            if q:
                rows = con.execute(
                    "SELECT * FROM sessions WHERE (customer_name LIKE ? OR vehicle_number LIKE ? OR slot_code LIKE ?) ORDER BY id DESC",
                    (f"%{q}%", f"%{q.upper()}%", f"%{q.upper()}%"),
                ).fetchall()
            else:
                rows = con.execute("SELECT * FROM sessions ORDER BY id DESC").fetchall()
        else:
            if q:
                rows = con.execute(
                    "SELECT * FROM sessions WHERE user_id=? AND (customer_name LIKE ? OR vehicle_number LIKE ? OR slot_code LIKE ?) ORDER BY id DESC",
                    (session["user_id"], f"%{q}%", f"%{q.upper()}%", f"%{q.upper()}%"),
                ).fetchall()
            else:
                rows = con.execute(
                    "SELECT * FROM sessions WHERE user_id=? ORDER BY id DESC", (session["user_id"],)
                ).fetchall()
    return render_template("history.html", sessions=rows, q=q)


@app.route("/receipt/<int:session_id>")
@login_required
def receipt(session_id):
    with db() as con:
        if session.get("role") == "admin":
            record = con.execute(
                "SELECT * FROM sessions WHERE id=? AND status='completed'", (session_id,)
            ).fetchone()
        else:
            record = con.execute(
                "SELECT * FROM sessions WHERE id=? AND status='completed' AND user_id=?",
                (session_id, session["user_id"]),
            ).fetchone()

    if not record:
        flash("Receipt not found or access denied.", "error")
        return redirect(url_for("history"))

    category = record["vehicle_category"] or "four_wheeler"
    rate = get_rate_for_category(category)
    entry_dt = datetime.fromisoformat(record["entry_time"])
    exit_dt = datetime.fromisoformat(record["exit_time"]) if record["exit_time"] else datetime.now()
    actual_minutes = math.ceil((exit_dt - entry_dt).total_seconds() / 60)
    total_amount = float(record["amount"] or 0)
    advance_paid = float(record["advance_amount"] or 0)
    balance_paid = round(max(0.0, total_amount - advance_paid), 2)
    refund_amount = float(record["refund_amount"] or 0)

    return render_template(
        "receipt.html",
        s=record,
        category=category,
        rate=rate,
        entry_dt=entry_dt,
        exit_dt=exit_dt,
        actual_minutes=actual_minutes,
        total_amount=total_amount,
        advance_paid=advance_paid,
        balance_paid=balance_paid,
        refund_amount=refund_amount,
    )


@app.route("/settings", methods=["GET", "POST"])
@admin_required
def settings():
    if request.method == "POST":
        action = request.form.get("action", "rates")
        if action == "rates":
            try:
                rate_2w = float(request.form.get("rate_two_wheeler", "10"))
                rate_4w = float(request.form.get("rate_four_wheeler", "20"))
                if rate_2w < 0 or rate_4w < 0 or rate_2w > 100000 or rate_4w > 100000:
                    raise ValueError
            except ValueError:
                flash("Enter valid non-negative hourly rates for Two-Wheeler and Four-Wheeler.", "error")
                return redirect(url_for("settings"))
            with db() as con:
                con.execute("INSERT OR REPLACE INTO settings(key,value) VALUES('rate_two_wheeler',?)", (str(rate_2w),))
                con.execute("INSERT OR REPLACE INTO settings(key,value) VALUES('rate_four_wheeler',?)", (str(rate_4w),))
                con.execute("INSERT OR REPLACE INTO settings(key,value) VALUES('hourly_rate',?)", (str(rate_4w),))
            flash(f"Parking rates updated: Two-Wheeler ₹{rate_2w:.2f}/hr, Four-Wheeler ₹{rate_4w:.2f}/hr.", "success")
        elif action == "demo_duration":
            try:
                extra = int(request.form.get("extra_minutes", "0"))
                if extra < 0 or extra > 525600:
                    raise ValueError
            except ValueError:
                flash("Enter a valid extra-minutes value (0 or more).", "error")
                return redirect(url_for("settings"))
            with db() as con:
                con.execute("INSERT OR REPLACE INTO settings(key,value) VALUES('demo_extra_minutes',?)", (str(extra),))
            flash(f"Demo duration offset set to {extra} extra minutes. [DEMO TIME ADJUSTMENT]", "success")
        elif action == "toggle_slot_category":
            slot_code = request.form.get("slot_code", "").strip()
            new_cat = request.form.get("category", "").strip()
            if new_cat not in ("two_wheeler", "four_wheeler"):
                flash("Invalid category specified.", "error")
                return redirect(url_for("settings"))
            with db() as con:
                slot = con.execute("SELECT status FROM slots WHERE slot_code=?", (slot_code,)).fetchone()
                if not slot:
                    flash(f"Slot {slot_code} does not exist.", "error")
                    return redirect(url_for("settings"))
                if slot["status"] == "occupied":
                    flash(f"Cannot change category of occupied slot {slot_code}.", "error")
                    return redirect(url_for("settings"))
                con.execute("UPDATE slots SET category=? WHERE slot_code=?", (new_cat, slot_code))
            cat_name = "Two-Wheeler" if new_cat == "two_wheeler" else "Four-Wheeler"
            flash(f"Slot {slot_code} category reassigned to {cat_name}.", "success")
        return redirect(url_for("settings"))

    with db() as con:
        all_slots = con.execute("SELECT * FROM slots ORDER BY slot_code").fetchall()

    return render_template(
        "settings.html",
        rates=get_rates(),
        rate=get_rate(),
        total=TOTAL_SLOTS,
        slots=all_slots,
        demo_extra=get_demo_extra_minutes(),
    )


# ---------------------------------------------------------------------------
# API endpoints
# ---------------------------------------------------------------------------

@app.route("/api/status")
@login_required
def api_status():
    is_admin = session.get("role") == "admin"
    user_id = session.get("user_id")

    with db() as con:
        raw_slots = con.execute("SELECT * FROM slots ORDER BY slot_code").fetchall()
        active_sessions = {
            row["slot_code"]: dict(row)
            for row in con.execute(
                """SELECT slot_code, id, user_id, customer_name, vehicle_number,
                          vehicle_category, entry_time, advance_amount, advance_status
                   FROM sessions WHERE status='active'"""
            ).fetchall()
        }

    slots = []
    for s in raw_slots:
        slot_dict = dict(s)
        code = slot_dict["slot_code"]
        sess = active_sessions.get(code)
        if sess:
            slot_dict["session_id"] = sess["id"]
            slot_dict["entry_time"] = sess["entry_time"]
            slot_dict["vehicle_category"] = sess.get("vehicle_category", slot_dict.get("category", "four_wheeler"))
            slot_dict["advance_amount"] = sess.get("advance_amount", 0)
            is_owner = (sess.get("user_id") == user_id)
            slot_dict["is_mine"] = is_owner
            if is_admin or is_owner:
                slot_dict["vehicle_number"] = sess["vehicle_number"]
                slot_dict["customer_name"] = sess["customer_name"]
            else:
                slot_dict["vehicle_number"] = None
                slot_dict["customer_name"] = None
        else:
            slot_dict["session_id"] = None
            slot_dict["entry_time"] = None
            slot_dict["vehicle_category"] = slot_dict.get("category", "four_wheeler")
            slot_dict["advance_amount"] = 0
            slot_dict["vehicle_number"] = None
            slot_dict["customer_name"] = None
            slot_dict["is_mine"] = False
        slots.append(slot_dict)

    stats = get_stats() if is_admin else user_stats(user_id)
    return jsonify({
        "mode": "simulation",
        "stats": stats,
        "slots": slots,
        "rates": get_rates(),
        "is_admin": is_admin,
        "updated_at": datetime.now().isoformat(timespec="seconds"),
    })


@app.route("/api/activity")
@login_required
def api_activity():
    with db() as con:
        rows = con.execute(
            "SELECT * FROM activity_log ORDER BY id DESC LIMIT 15"
        ).fetchall()
    return jsonify([dict(r) for r in rows])


# ---------------------------------------------------------------------------
# Admin-only operations
# ---------------------------------------------------------------------------

@app.route("/reset-demo", methods=["POST"])
@admin_required
def reset_demo():
    with db() as con:
        con.execute("DELETE FROM sessions")
        con.execute("DELETE FROM activity_log")
        con.execute("UPDATE slots SET status='available'")
        con.execute("INSERT OR REPLACE INTO settings(key,value) VALUES('demo_extra_minutes','0')")
    flash("Demo data cleared. All slots are reset to available.", "success")
    return redirect(url_for("dashboard"))


# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------

init_db()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
