import os
import sqlite3
from datetime import date, datetime, timedelta
from functools import wraps
from pathlib import Path

from flask import Flask, g, jsonify, redirect, render_template, request, session, url_for, flash
from werkzeug.security import check_password_hash, generate_password_hash

BASE_DIR = Path(__file__).resolve().parent
DATABASE = Path(os.environ.get("INFIREAD_DB", BASE_DIR / "infiread.db"))

app = Flask(__name__)
app.config.update(
    SECRET_KEY=os.environ.get("INFIREAD_SECRET_KEY", "dev-only-change-this-secret-before-deployment"),
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
)


def connect_db():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    with connect_db() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT NOT NULL UNIQUE COLLATE NOCASE,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'member' CHECK(role IN ('admin','librarian','member')),
            active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS books (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            author TEXT NOT NULL,
            isbn TEXT UNIQUE,
            category TEXT NOT NULL DEFAULT 'General',
            publisher TEXT DEFAULT '',
            year INTEGER,
            description TEXT DEFAULT '',
            cover_url TEXT DEFAULT '',
            shelf TEXT DEFAULT '',
            total_copies INTEGER NOT NULL DEFAULT 1 CHECK(total_copies >= 0),
            archived INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS loans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            book_id INTEGER NOT NULL REFERENCES books(id),
            user_id INTEGER NOT NULL REFERENCES users(id),
            issued_by INTEGER REFERENCES users(id),
            issue_date TEXT NOT NULL,
            due_date TEXT NOT NULL,
            returned_at TEXT,
            renewal_count INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'issued' CHECK(status IN ('issued','returned','lost')),
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS issue_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            book_id INTEGER NOT NULL REFERENCES books(id),
            user_id INTEGER NOT NULL REFERENCES users(id),
            status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','approved','rejected','cancelled')),
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            processed_by INTEGER REFERENCES users(id),
            processed_at TEXT
        );
        CREATE TABLE IF NOT EXISTS reservations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            book_id INTEGER NOT NULL REFERENCES books(id),
            user_id INTEGER NOT NULL REFERENCES users(id),
            status TEXT NOT NULL DEFAULT 'waiting' CHECK(status IN ('waiting','ready','fulfilled','cancelled','expired')),
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(book_id, user_id, status)
        );
        CREATE TABLE IF NOT EXISTS notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id),
            message TEXT NOT NULL,
            read_at TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS audit_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            actor_id INTEGER REFERENCES users(id),
            action TEXT NOT NULL,
            details TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        """)
        defaults = {"loan_days": "14", "max_active_loans": "5", "max_renewals": "2", "fine_per_day": "5"}
        for key, value in defaults.items():
            db.execute("INSERT OR IGNORE INTO settings(key,value) VALUES(?,?)", (key, value))
        if not db.execute("SELECT id FROM users WHERE email = ?", ("admin@infiread.local",)).fetchone():
            db.execute("INSERT INTO users(name,email,password_hash,role) VALUES(?,?,?,?)",
                       ("InfiRead Admin", "admin@infiread.local", generate_password_hash("Admin123!"), "admin"))
        if db.execute("SELECT COUNT(*) FROM books").fetchone()[0] == 0:
            samples = [
                ("Clean Code", "Robert C. Martin", "9780132350884", "Programming", "Prentice Hall", 2008, "A practical guide to writing maintainable software.", "", "A-01", 3),
                ("Python Crash Course", "Eric Matthes", "9781593279288", "Programming", "No Starch Press", 2019, "Hands-on Python programming for beginners.", "", "A-02", 4),
                ("Atomic Habits", "James Clear", "9780735211292", "Personal Development", "Avery", 2018, "A practical framework for building better habits.", "", "B-01", 2),
                ("The Alchemist", "Paulo Coelho", "9780061122415", "Fiction", "HarperOne", 1988, "A philosophical novel about following a dream.", "", "C-01", 2),
                ("Introduction to Algorithms", "Thomas H. Cormen et al.", "9780262046305", "Computer Science", "MIT Press", 2022, "A comprehensive introduction to algorithms.", "", "A-03", 2),
                ("Deep Work", "Cal Newport", "9781455586691", "Productivity", "Grand Central Publishing", 2016, "Rules for focused success in a distracted world.", "", "B-02", 2),
            ]
            db.executemany("""INSERT INTO books(title,author,isbn,category,publisher,year,description,cover_url,shelf,total_copies)
                              VALUES(?,?,?,?,?,?,?,?,?,?)""", samples)


def get_db():
    if "db" not in g:
        g.db = connect_db()
    return g.db


@app.teardown_appcontext
def close_db(error=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def current_user():
    uid = session.get("user_id")
    if not uid:
        return None
    return get_db().execute("SELECT id,name,email,role,active FROM users WHERE id=?", (uid,)).fetchone()


def login_required(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        if not current_user():
            if request.path.startswith("/api/"):
                return jsonify(error="Authentication required"), 401
            return redirect(url_for("login", next=request.path))
        return fn(*args, **kwargs)
    return wrapped


def roles_required(*roles):
    def decorator(fn):
        @wraps(fn)
        @login_required
        def wrapped(*args, **kwargs):
            user = current_user()
            if not user or user["role"] not in roles:
                if request.path.startswith("/api/"):
                    return jsonify(error="You do not have permission for this action"), 403
                flash("You do not have permission to perform that action.", "error")
                return redirect(url_for("dashboard"))
            return fn(*args, **kwargs)
        return wrapped
    return decorator


def setting(key, fallback):
    row = get_db().execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return row["value"] if row else fallback


def log_action(action, details=""):
    user = current_user()
    get_db().execute("INSERT INTO audit_logs(actor_id,action,details) VALUES(?,?,?)",
                     (user["id"] if user else None, action, details))


def available_copies(book_id):
    row = get_db().execute("""
        SELECT b.total_copies - (
          SELECT COUNT(*) FROM loans l WHERE l.book_id=b.id AND l.status='issued'
        ) AS available
        FROM books b WHERE b.id=?
    """, (book_id,)).fetchone()
    return max(0, row["available"]) if row else 0


def notify(user_id, message):
    get_db().execute("INSERT INTO notifications(user_id,message) VALUES(?,?)", (user_id, message))


@app.route("/")
def index():
    db = get_db()
    books = db.execute("""SELECT b.*, (b.total_copies - (SELECT COUNT(*) FROM loans l
        WHERE l.book_id=b.id AND l.status='issued')) AS available
        FROM books b WHERE b.archived=0 ORDER BY b.created_at DESC LIMIT 8""").fetchall()
    stats = {
        "titles": db.execute("SELECT COUNT(*) FROM books WHERE archived=0").fetchone()[0],
        "copies": db.execute("SELECT COALESCE(SUM(total_copies),0) FROM books WHERE archived=0").fetchone()[0],
        "members": db.execute("SELECT COUNT(*) FROM users WHERE role='member' AND active=1").fetchone()[0],
    }
    return render_template("index.html", books=books, stats=stats, user=current_user())


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        if len(name) < 2 or "@" not in email or len(password) < 8:
            flash("Enter a valid name and email. Password must be at least 8 characters.", "error")
            return render_template("register.html")
        db = get_db()
        try:
            cur = db.execute("INSERT INTO users(name,email,password_hash,role) VALUES(?,?,?,'member')",
                             (name, email, generate_password_hash(password)))
            db.commit()
            session.clear()
            session["user_id"] = cur.lastrowid
            flash("Welcome to InfiRead! Your account is ready.", "success")
            return redirect(url_for("dashboard"))
        except sqlite3.IntegrityError:
            flash("An account with that email already exists.", "error")
    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        user = get_db().execute("SELECT * FROM users WHERE email=? AND active=1", (email,)).fetchone()
        if user and check_password_hash(user["password_hash"], password):
            session.clear()
            session["user_id"] = user["id"]
            flash("Welcome back!", "success")
            return redirect(url_for("dashboard"))
        flash("Invalid email or password, or the account is inactive.", "error")
    return render_template("login.html")


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    flash("You have been logged out.", "success")
    return redirect(url_for("index"))


@app.route("/dashboard")
@login_required
def dashboard():
    user = current_user()
    db = get_db()
    if user["role"] in ("admin", "librarian"):
        stats = {
            "titles": db.execute("SELECT COUNT(*) FROM books WHERE archived=0").fetchone()[0],
            "copies": db.execute("SELECT COALESCE(SUM(total_copies),0) FROM books WHERE archived=0").fetchone()[0],
            "issued": db.execute("SELECT COUNT(*) FROM loans WHERE status='issued'").fetchone()[0],
            "overdue": db.execute("SELECT COUNT(*) FROM loans WHERE status='issued' AND due_date < ?", (date.today().isoformat(),)).fetchone()[0],
            "members": db.execute("SELECT COUNT(*) FROM users WHERE role='member' AND active=1").fetchone()[0],
            "requests": db.execute("SELECT COUNT(*) FROM issue_requests WHERE status='pending'").fetchone()[0],
        }
        recent = db.execute("""SELECT l.*, b.title, u.name AS member_name FROM loans l
            JOIN books b ON b.id=l.book_id JOIN users u ON u.id=l.user_id
            ORDER BY l.id DESC LIMIT 8""").fetchall()
        requests = db.execute("""SELECT r.*,b.title,u.name AS member_name FROM issue_requests r
            JOIN books b ON b.id=r.book_id JOIN users u ON u.id=r.user_id
            WHERE r.status='pending' ORDER BY r.id DESC LIMIT 6""").fetchall()
    else:
        stats = {
            "issued": db.execute("SELECT COUNT(*) FROM loans WHERE user_id=? AND status='issued'", (user["id"],)).fetchone()[0],
            "overdue": db.execute("SELECT COUNT(*) FROM loans WHERE user_id=? AND status='issued' AND due_date < ?", (user["id"], date.today().isoformat())).fetchone()[0],
            "requests": db.execute("SELECT COUNT(*) FROM issue_requests WHERE user_id=? AND status='pending'", (user["id"],)).fetchone()[0],
            "reservations": db.execute("SELECT COUNT(*) FROM reservations WHERE user_id=? AND status IN ('waiting','ready')", (user["id"],)).fetchone()[0],
        }
        recent = db.execute("""SELECT l.*, b.title, u.name AS member_name FROM loans l
            JOIN books b ON b.id=l.book_id JOIN users u ON u.id=l.user_id
            WHERE l.user_id=? ORDER BY l.id DESC LIMIT 8""", (user["id"],)).fetchall()
        requests = []
    notifications = db.execute("SELECT * FROM notifications WHERE user_id=? ORDER BY id DESC LIMIT 5", (user["id"],)).fetchall()
    return render_template("dashboard.html", user=user, stats=stats, recent=recent, requests=requests, notifications=notifications)


@app.route("/books")
def books():
    q = request.args.get("q", "").strip()
    category = request.args.get("category", "").strip()
    availability = request.args.get("availability", "")
    sql = """SELECT b.*, (b.total_copies - (SELECT COUNT(*) FROM loans l
        WHERE l.book_id=b.id AND l.status='issued')) AS available
        FROM books b WHERE b.archived=0"""
    args = []
    if q:
        sql += " AND (b.title LIKE ? OR b.author LIKE ? OR b.isbn LIKE ? OR b.publisher LIKE ? OR b.category LIKE ?)"
        args.extend([f"%{q}%"] * 5)
    if category:
        sql += " AND b.category=?"
        args.append(category)
    if availability == "yes":
        sql += """ AND (b.total_copies - (SELECT COUNT(*) FROM loans l
            WHERE l.book_id=b.id AND l.status='issued')) > 0"""
    sql += " ORDER BY b.title COLLATE NOCASE"
    rows = get_db().execute(sql, args).fetchall()
    categories = get_db().execute("SELECT DISTINCT category FROM books WHERE archived=0 ORDER BY category").fetchall()
    return render_template("books.html", books=rows, q=q, category=category, categories=categories, user=current_user(), availability=availability)


@app.route("/books/add", methods=["GET", "POST"])
@roles_required("admin", "librarian")
def add_book():
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        author = request.form.get("author", "").strip()
        isbn = request.form.get("isbn", "").strip() or None
        category = request.form.get("category", "General").strip() or "General"
        try:
            copies = max(0, int(request.form.get("total_copies", "1")))
            year_raw = request.form.get("year", "").strip()
            year = int(year_raw) if year_raw else None
        except ValueError:
            flash("Year and copy count must be valid numbers.", "error")
            return render_template("book_form.html", book=None)
        if not title or not author:
            flash("Title and author are required.", "error")
            return render_template("book_form.html", book=None)
        try:
            db = get_db()
            db.execute("""INSERT INTO books(title,author,isbn,category,publisher,year,description,cover_url,shelf,total_copies)
                VALUES(?,?,?,?,?,?,?,?,?,?)""",
                (title, author, isbn, category, request.form.get("publisher","").strip(), year,
                 request.form.get("description","").strip(), request.form.get("cover_url","").strip(),
                 request.form.get("shelf","").strip(), copies))
            log_action("book_created", title)
            db.commit()
            flash("Book added successfully.", "success")
            return redirect(url_for("books"))
        except sqlite3.IntegrityError:
            flash("That ISBN already exists. Use a unique ISBN.", "error")
    return render_template("book_form.html", book=None)


@app.route("/books/<int:book_id>/edit", methods=["GET", "POST"])
@roles_required("admin", "librarian")
def edit_book(book_id):
    db = get_db()
    book = db.execute("SELECT * FROM books WHERE id=? AND archived=0", (book_id,)).fetchone()
    if not book:
        flash("Book not found.", "error")
        return redirect(url_for("books"))
    if request.method == "POST":
        try:
            copies = max(0, int(request.form.get("total_copies", "1")))
            year_raw = request.form.get("year", "").strip()
            year = int(year_raw) if year_raw else None
        except ValueError:
            flash("Year and copy count must be valid numbers.", "error")
            return render_template("book_form.html", book=book)
        active = db.execute("SELECT COUNT(*) FROM loans WHERE book_id=? AND status='issued'", (book_id,)).fetchone()[0]
        if copies < active:
            flash(f"Cannot set copies below the {active} currently issued copy/copies.", "error")
            return render_template("book_form.html", book=book)
        try:
            db.execute("""UPDATE books SET title=?,author=?,isbn=?,category=?,publisher=?,year=?,description=?,cover_url=?,shelf=?,total_copies=?
                WHERE id=?""",
                (request.form.get("title","").strip(), request.form.get("author","").strip(),
                 request.form.get("isbn","").strip() or None, request.form.get("category","General").strip() or "General",
                 request.form.get("publisher","").strip(), year, request.form.get("description","").strip(),
                 request.form.get("cover_url","").strip(), request.form.get("shelf","").strip(), copies, book_id))
            log_action("book_updated", str(book_id))
            db.commit()
            flash("Book updated.", "success")
            return redirect(url_for("books"))
        except sqlite3.IntegrityError:
            flash("That ISBN is already assigned to another book.", "error")
    return render_template("book_form.html", book=book)


@app.route("/books/<int:book_id>/archive", methods=["POST"])
@roles_required("admin", "librarian")
def archive_book(book_id):
    db = get_db()
    active = db.execute("SELECT COUNT(*) FROM loans WHERE book_id=? AND status='issued'", (book_id,)).fetchone()[0]
    if active:
        flash("Return all issued copies before archiving this book.", "error")
    else:
        db.execute("UPDATE books SET archived=1 WHERE id=?", (book_id,))
        log_action("book_archived", str(book_id))
        db.commit()
        flash("Book archived.", "success")
    return redirect(url_for("books"))


@app.route("/books/<int:book_id>/request", methods=["POST"])
@login_required
def request_book(book_id):
    user = current_user()
    db = get_db()
    book = db.execute("SELECT * FROM books WHERE id=? AND archived=0", (book_id,)).fetchone()
    if not book:
        flash("Book not found.", "error")
        return redirect(url_for("books"))
    if user["role"] != "member":
        flash("Staff accounts should issue books from the staff dashboard.", "error")
        return redirect(url_for("books"))
    duplicate = db.execute("SELECT id FROM issue_requests WHERE book_id=? AND user_id=? AND status='pending'", (book_id,user["id"])).fetchone()
    if duplicate:
        flash("You already have a pending request for this book.", "error")
        return redirect(url_for("books"))
    if available_copies(book_id) > 0:
        db.execute("INSERT INTO issue_requests(book_id,user_id) VALUES(?,?)", (book_id,user["id"]))
        db.commit()
        flash("Issue request submitted. A librarian will process it.", "success")
    else:
        existing = db.execute("SELECT id FROM reservations WHERE book_id=? AND user_id=? AND status IN ('waiting','ready')", (book_id,user["id"])).fetchone()
        if not existing:
            db.execute("INSERT INTO reservations(book_id,user_id,status) VALUES(?,?,'waiting')", (book_id,user["id"]))
            db.commit()
            flash("No copies are available. You have been added to the reservation queue.", "success")
        else:
            flash("You already have an active reservation for this book.", "error")
    return redirect(url_for("books"))


@app.route("/requests/<int:request_id>/<decision>", methods=["POST"])
@roles_required("admin", "librarian")
def process_request(request_id, decision):
    if decision not in ("approve", "reject"):
        return redirect(url_for("dashboard"))
    db = get_db()
    req = db.execute("SELECT * FROM issue_requests WHERE id=? AND status='pending'", (request_id,)).fetchone()
    if not req:
        flash("Request not found or already processed.", "error")
        return redirect(url_for("dashboard"))
    if decision == "reject":
        db.execute("UPDATE issue_requests SET status='rejected',processed_by=?,processed_at=CURRENT_TIMESTAMP WHERE id=?",
                   (current_user()["id"], request_id))
        notify(req["user_id"], "Your book request was declined. Please contact the library if you need help.")
        log_action("issue_request_rejected", str(request_id))
        db.commit()
        flash("Request rejected.", "success")
        return redirect(url_for("dashboard"))
    member = db.execute("SELECT * FROM users WHERE id=? AND active=1", (req["user_id"],)).fetchone()
    active_loans = db.execute("SELECT COUNT(*) FROM loans WHERE user_id=? AND status='issued'", (req["user_id"],)).fetchone()[0]
    if not member or active_loans >= int(setting("max_active_loans", "5")) or available_copies(req["book_id"]) < 1:
        flash("Cannot approve: member is inactive, has reached the loan limit, or no copy is available.", "error")
        return redirect(url_for("dashboard"))
    today = date.today()
    due = today + timedelta(days=int(setting("loan_days", "14")))
    db.execute("INSERT INTO loans(book_id,user_id,issued_by,issue_date,due_date) VALUES(?,?,?,?,?)",
               (req["book_id"], req["user_id"], current_user()["id"], today.isoformat(), due.isoformat()))
    db.execute("UPDATE issue_requests SET status='approved',processed_by=?,processed_at=CURRENT_TIMESTAMP WHERE id=?",
               (current_user()["id"], request_id))
    book = db.execute("SELECT title FROM books WHERE id=?", (req["book_id"],)).fetchone()
    notify(req["user_id"], f"Your request for '{book['title']}' was approved. Due date: {due.isoformat()}.")
    log_action("book_issued", f"request={request_id}, user={req['user_id']}, book={req['book_id']}")
    db.commit()
    flash(f"Book issued. Due date: {due.isoformat()}.", "success")
    return redirect(url_for("dashboard"))


@app.route("/loans/<int:loan_id>/return", methods=["POST"])
@roles_required("admin", "librarian")
def return_book(loan_id):
    db = get_db()
    loan = db.execute("SELECT * FROM loans WHERE id=? AND status='issued'", (loan_id,)).fetchone()
    if not loan:
        flash("Active loan not found.", "error")
        return redirect(url_for("dashboard"))
    returned = date.today()
    due = date.fromisoformat(loan["due_date"])
    late_days = max(0, (returned - due).days)
    fine = late_days * int(setting("fine_per_day", "5"))
    db.execute("UPDATE loans SET status='returned',returned_at=? WHERE id=?", (returned.isoformat(), loan_id))
    book = db.execute("SELECT title FROM books WHERE id=?", (loan["book_id"],)).fetchone()
    notify(loan["user_id"], f"'{book['title']}' has been marked returned. Late days: {late_days}. Estimated fine: ₹{fine}.")
    # Release the next waiting reservation, if any.
    reservation = db.execute("""SELECT * FROM reservations WHERE book_id=? AND status='waiting' ORDER BY id LIMIT 1""",
                             (loan["book_id"],)).fetchone()
    if reservation:
        db.execute("UPDATE reservations SET status='ready' WHERE id=?", (reservation["id"],))
        notify(reservation["user_id"], f"A reserved copy of '{book['title']}' is now available. Please contact the library.")
    log_action("book_returned", f"loan={loan_id}, fine={fine}")
    db.commit()
    flash(f"Book returned. Late by {late_days} day(s); estimated fine ₹{fine}.", "success")
    return redirect(url_for("dashboard"))


@app.route("/loans/<int:loan_id>/renew", methods=["POST"])
@login_required
def renew_book(loan_id):
    user = current_user()
    db = get_db()
    loan = db.execute("SELECT * FROM loans WHERE id=? AND status='issued'", (loan_id,)).fetchone()
    if not loan or (user["role"] == "member" and loan["user_id"] != user["id"]):
        flash("Active loan not found.", "error")
        return redirect(url_for("dashboard"))
    if loan["renewal_count"] >= int(setting("max_renewals", "2")):
        flash("Renewal limit reached.", "error")
        return redirect(url_for("dashboard"))
    reservation = db.execute("SELECT id FROM reservations WHERE book_id=? AND status IN ('waiting','ready') AND user_id<>? LIMIT 1",
                             (loan["book_id"], loan["user_id"])).fetchone()
    if reservation:
        flash("This book has another member waiting; renewal is not allowed.", "error")
        return redirect(url_for("dashboard"))
    today = date.today()
    if date.fromisoformat(loan["due_date"]) < today:
        flash("Overdue books cannot be renewed. Please contact the librarian.", "error")
        return redirect(url_for("dashboard"))
    new_due = max(date.fromisoformat(loan["due_date"]), today) + timedelta(days=int(setting("loan_days", "14")))
    db.execute("UPDATE loans SET due_date=?,renewal_count=renewal_count+1 WHERE id=?",
               (new_due.isoformat(), loan_id))
    notify(loan["user_id"], f"Your loan was renewed. New due date: {new_due.isoformat()}.")
    log_action("book_renewed", f"loan={loan_id}, due={new_due.isoformat()}")
    db.commit()
    flash(f"Renewed successfully. New due date: {new_due.isoformat()}.", "success")
    return redirect(url_for("dashboard"))


@app.route("/reservations")
@login_required
def reservations():
    user = current_user()
    db = get_db()
    if user["role"] in ("admin", "librarian"):
        rows = db.execute("""SELECT r.*,b.title,u.name AS member_name,u.email FROM reservations r
            JOIN books b ON b.id=r.book_id JOIN users u ON u.id=r.user_id
            WHERE r.status IN ('waiting','ready') ORDER BY r.id""").fetchall()
    else:
        rows = db.execute("""SELECT r.*,b.title FROM reservations r JOIN books b ON b.id=r.book_id
            WHERE r.user_id=? ORDER BY r.id DESC""", (user["id"],)).fetchall()
    return render_template("reservations.html", rows=rows, user=user)


@app.route("/reservations/<int:reservation_id>/cancel", methods=["POST"])
@login_required
def cancel_reservation(reservation_id):
    user = current_user()
    db = get_db()
    row = db.execute("SELECT * FROM reservations WHERE id=?", (reservation_id,)).fetchone()
    if not row or (user["role"] == "member" and row["user_id"] != user["id"]):
        flash("Reservation not found.", "error")
    elif row["status"] not in ("waiting", "ready"):
        flash("This reservation cannot be cancelled.", "error")
    else:
        db.execute("UPDATE reservations SET status='cancelled' WHERE id=?", (reservation_id,))
        log_action("reservation_cancelled", str(reservation_id))
        db.commit()
        flash("Reservation cancelled.", "success")
    return redirect(url_for("reservations"))


@app.route("/notifications")
@login_required
def notifications():
    user = current_user()
    rows = get_db().execute("SELECT * FROM notifications WHERE user_id=? ORDER BY id DESC", (user["id"],)).fetchall()
    return render_template("notifications.html", rows=rows, user=user)


@app.route("/notifications/<int:nid>/read", methods=["POST"])
@login_required
def mark_notification(nid):
    user = current_user()
    db = get_db()
    db.execute("UPDATE notifications SET read_at=CURRENT_TIMESTAMP WHERE id=? AND user_id=?", (nid, user["id"]))
    db.commit()
    return redirect(url_for("notifications"))


@app.route("/admin/members")
@roles_required("admin")
def members():
    rows = get_db().execute("SELECT id,name,email,role,active,created_at FROM users ORDER BY id DESC").fetchall()
    return render_template("members.html", rows=rows, user=current_user())


@app.route("/admin/members/<int:user_id>/toggle", methods=["POST"])
@roles_required("admin")
def toggle_member(user_id):
    db = get_db()
    target = db.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    if not target or target["id"] == current_user()["id"]:
        flash("Member not found or cannot change your own account status.", "error")
    else:
        new_state = 0 if target["active"] else 1
        db.execute("UPDATE users SET active=? WHERE id=?", (new_state, user_id))
        log_action("account_status_changed", f"user={user_id}, active={new_state}")
        db.commit()
        flash("Account status updated.", "success")
    return redirect(url_for("members"))


@app.route("/admin/settings", methods=["GET", "POST"])
@roles_required("admin")
def settings():
    db = get_db()
    if request.method == "POST":
        try:
            values = {
                "loan_days": str(max(1, min(90, int(request.form.get("loan_days", "14"))))),
                "max_active_loans": str(max(1, min(30, int(request.form.get("max_active_loans", "5"))))),
                "max_renewals": str(max(0, min(10, int(request.form.get("max_renewals", "2"))))),
                "fine_per_day": str(max(0, min(10000, int(request.form.get("fine_per_day", "5"))))),
            }
        except ValueError:
            flash("Settings must be valid numbers.", "error")
            values = {k: setting(k, v) for k, v in {"loan_days":"14","max_active_loans":"5","max_renewals":"2","fine_per_day":"5"}.items()}
            return render_template("settings.html", values=values, user=current_user())
        for key, value in values.items():
            db.execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))
        log_action("library_settings_updated", json.dumps(values))
        db.commit()
        flash("Library settings saved.", "success")
    values = {k: setting(k, v) for k, v in {"loan_days":"14","max_active_loans":"5","max_renewals":"2","fine_per_day":"5"}.items()}
    return render_template("settings.html", values=values, user=current_user())


@app.route("/api/health")
def health():
    return jsonify(status="ok", app="InfiRead", date=date.today().isoformat())


@app.route("/api/books")
def api_books():
    rows = get_db().execute("""SELECT b.id,b.title,b.author,b.category,b.total_copies,
        (b.total_copies-(SELECT COUNT(*) FROM loans l WHERE l.book_id=b.id AND l.status='issued')) AS available
        FROM books b WHERE b.archived=0 ORDER BY b.title""").fetchall()
    return jsonify([dict(row) for row in rows])


@app.route("/api/overdues")
@roles_required("admin", "librarian")
def api_overdues():
    rows = get_db().execute("""SELECT l.id,l.due_date,b.title,u.name,u.email
        FROM loans l JOIN books b ON b.id=l.book_id JOIN users u ON u.id=l.user_id
        WHERE l.status='issued' AND l.due_date < ? ORDER BY l.due_date""", (date.today().isoformat(),)).fetchall()
    return jsonify([dict(row) for row in rows])


@app.errorhandler(404)
def not_found(error):
    if request.path.startswith("/api/"):
        return jsonify(error="Not found"), 404
    return render_template("404.html", user=current_user()), 404


@app.errorhandler(500)
def server_error(error):
    if request.path.startswith("/api/"):
        return jsonify(error="Internal server error"), 500
    return render_template("500.html", user=current_user()), 500


with app.app_context():
    init_db()


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", "5000")), debug=os.environ.get("FLASK_DEBUG") == "1")
