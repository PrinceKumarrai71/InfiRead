# InfiRead — Smart Library Management System

A responsive full-stack library management starter built with **Flask + SQLite + HTML/CSS/JavaScript**. It includes real database-backed accounts, a modern responsive interface, book catalogue management, issue requests, returns, renewals, reservations, overdue calculations, notifications, member administration, and configurable library policies.

> This is a runnable starter project, not a certified production deployment. Review the security notes below before exposing it publicly.

## Features included

- Public homepage with dynamic catalogue statistics and book cards
- Member registration and login with hashed passwords
- Session-based authentication and admin/librarian/member roles
- Book search across title, author, ISBN, publisher, and category
- Category and availability filters
- Add, edit, and archive books (staff only)
- Member issue requests and staff approval/rejection
- Transactional SQLite persistence for core operations
- Returns, due dates, renewal limits, and estimated overdue fines
- Reservations and waiting queue notifications
- In-app notifications and read status
- Admin member activation/deactivation
- Configurable loan duration, loan limit, renewal limit, and daily fine
- JSON endpoints at `/api/health`, `/api/books`, and `/api/overdues`
- Responsive design, dark hero artwork, animated cards, hover effects, mobile navigation
- Sample book records created automatically on first run

## Requirements

- Python 3.10+
- Internet connection only if you need to install Flask for the first time

## Run on macOS

Open Terminal and run:

```bash
cd /path/to/InfiRead
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python app.py
```

Open `http://127.0.0.1:5000`.

If port 5000 is occupied, use another port:

```bash
PORT=5001 python app.py
```

Do not terminate an unknown process just to free a port. Identify the process first.

## Run on Windows

```powershell
cd path\to\InfiRead
py -m venv .venv
.venv\Scripts\activate
python -m pip install -r requirements.txt
python app.py
```

Open `http://127.0.0.1:5000`.

## Demo administrator

For local evaluation, a development administrator is seeded automatically:

- Email: `admin@infiread.local`
- Password: `Admin123!`

Change or remove this development account before deployment. Anyone who can access the local demo knows these credentials. Do not expose the app publicly with this default password.

Newly registered accounts receive the **member** role. Promote staff only through a controlled administrative process; the starter does not provide a public role-escalation form.

## Main routes

- `/` — Landing page
- `/register` — Create member account
- `/login` — Sign in
- `/dashboard` — Member or staff dashboard
- `/books` — Search and browse books
- `/books/add` — Add book (staff)
- `/reservations` — Reservation queue
- `/notifications` — In-app notifications
- `/admin/members` — Member management (admin)
- `/admin/settings` — Library policy settings (admin)
- `/api/health` — Health check JSON
- `/api/books` — Book catalogue JSON
- `/api/overdues` — Overdue loan JSON (staff login required)

## Notes on current behavior

- A member submits an issue request; a librarian/admin approves it to create an active loan.
- If all copies are issued, a member can join the reservation queue.
- Renewals are available to the loan owner or staff and are blocked when the configured limit is reached, the loan is overdue, or another member is waiting.
- Overdue fine amounts are calculated at return time and displayed to the user. A full fine ledger, payment processing, scheduled email reminders, password reset, email verification, image upload, CSV import/export, PDF reports, and a PostgreSQL deployment profile are **not yet implemented**.
- The current starter uses SQLite and Flask server-rendered templates rather than the React/FastAPI stack described in the original master prompt. This makes it simpler to run locally and avoids needing a separate frontend build.
- Use HTTPS, a strong `INFIREAD_SECRET_KEY`, secure cookie settings, CSRF protection, rate limiting, backups, and a proper admin provisioning flow before production use.

## Configuration

Set environment variables before launching. Example:

```bash
export INFIREAD_SECRET_KEY="$(python -c 'import secrets; print(secrets.token_hex(32))')"
PORT=5000 python app.py
```

To use a custom database location:

```bash
INFIREAD_DB="$HOME/infiread.db" python app.py
```

## Project structure

```text
InfiRead/
├── app.py
├── requirements.txt
├── README.md
├── .env.example
├── .gitignore
├── templates/
│   ├── base.html
│   ├── index.html
│   ├── login.html
│   ├── register.html
│   ├── books.html
│   ├── book_form.html
│   ├── dashboard.html
│   ├── reservations.html
│   ├── notifications.html
│   ├── members.html
│   ├── settings.html
│   ├── 404.html
│   └── 500.html
├── static/
│   ├── style.css
│   └── app.js
└── tests/
```

## Troubleshooting

**`No module named flask`**  
Activate the virtual environment and run `python -m pip install -r requirements.txt`.

**Package installation fails with a DNS/network error**  
Check internet access and retry. Flask must be installed before the app can start. The application itself does not need external APIs at runtime.

**Port already in use**  
Try `PORT=5001 python app.py`, or identify the process listening on the port before stopping it.

**Reset the local demo database**  
Stop the server, back up any important data, then delete `infiread.db`. The database and sample books will be recreated at next startup. This deletes local accounts and activity.

## License

Use and modify this starter for learning and project development. Add a license file if distributing it publicly.
