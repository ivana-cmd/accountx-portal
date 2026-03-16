import os, smtplib, ssl, hashlib, secrets
from datetime import datetime
from email.message import EmailMessage
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, flash, session, g

try:
    import psycopg2, psycopg2.extras
    HAS_PG = True
except ImportError:
    HAS_PG = False

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "accountx-portal-secret")

SMTP_SERVER   = os.environ.get("SMTP_SERVER",   "smtp-relay.gmail.com")
SMTP_PORT     = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USE_TLS  = os.environ.get("SMTP_USE_TLS",  "1") == "1"
SMTP_USERNAME = os.environ.get("SMTP_USERNAME", "")
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")
SENDER_EMAIL  = os.environ.get("SENDER_EMAIL",  "info@accountx.me")
SENDER_NAME   = os.environ.get("SENDER_NAME",   "AccountX DOO")
INBOX_EMAIL   = os.environ.get("INBOX_EMAIL",   "ivana@accountx.me")
DATABASE_URL  = os.environ.get("DATABASE_URL",  "")

TASK_CATEGORIES = [
    "Plata", "PDV", "Izvodi", "Kartica", "Ugovor", "Honorar",
    "Putni nalog", "Administracija", "Akciza", "Završni račun",
    "Plaćanja", "Preregistracija", "Kalkulacije", "Fakturisanje",
    "Pitanje / Upit", "Ostalo"
]

def get_db():
    if "db" not in g:
        url = DATABASE_URL.replace("postgres://", "postgresql://", 1) if DATABASE_URL.startswith("postgres://") else DATABASE_URL
        g.db = psycopg2.connect(url, cursor_factory=psycopg2.extras.RealDictCursor)
    return g.db

@app.teardown_appcontext
def close_db(e=None):
    db = g.pop("db", None)
    if db: db.close()

def init_db():
    con = get_db(); cur = con.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS portal_users (
            id SERIAL PRIMARY KEY,
            pib TEXT UNIQUE NOT NULL,
            firm_name TEXT NOT NULL,
            email TEXT NOT NULL,
            password_hash TEXT NOT NULL,
            is_active BOOLEAN DEFAULT TRUE,
            created_at TIMESTAMP DEFAULT NOW()
        );
        CREATE TABLE IF NOT EXISTS portal_requests (
            id SERIAL PRIMARY KEY,
            user_id INTEGER REFERENCES portal_users(id),
            pib TEXT NOT NULL,
            firm_name TEXT NOT NULL,
            contact_name TEXT NOT NULL,
            email TEXT NOT NULL,
            phone TEXT,
            category TEXT NOT NULL,
            description TEXT NOT NULL,
            priority TEXT DEFAULT 'Normalno',
            status TEXT DEFAULT 'Primljeno',
            created_at TIMESTAMP DEFAULT NOW()
        );
    """)
    con.commit()

def hash_password(p): return hashlib.sha256(p.encode()).hexdigest()
def verify_password(p, h): return hashlib.sha256(p.encode()).hexdigest() == h

def send_email(to_email, subject, body, reply_to=None):
    msg = EmailMessage()
    msg["From"]    = f"{SENDER_NAME} <{SENDER_EMAIL}>"
    msg["To"]      = to_email
    msg["Subject"] = subject
    if reply_to: msg["Reply-To"] = reply_to
    msg.set_content(body)
    if SMTP_USE_TLS:
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT, timeout=30) as s:
            s.ehlo(); s.starttls(context=ssl.create_default_context()); s.ehlo()
            if SMTP_USERNAME and SMTP_PASSWORD: s.login(SMTP_USERNAME, SMTP_PASSWORD)
            s.send_message(msg)
    else:
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT, timeout=30) as s:
            s.ehlo()
            if SMTP_USERNAME and SMTP_PASSWORD: s.login(SMTP_USERNAME, SMTP_PASSWORD)
            s.send_message(msg)

def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not session.get("user_id"): return redirect(url_for("login"))
        return fn(*args, **kwargs)
    return wrapper

@app.before_request
def setup():
    if DATABASE_URL and request.endpoint not in ("static",):
        try: init_db()
        except Exception as e: print(f"DB init: {e}")

@app.route("/")
def index():
    return redirect(url_for("login") if not session.get("user_id") else url_for("submit_request"))

@app.route("/login", methods=["GET", "POST"])
def login():
    error = ""
    if request.method == "POST":
        pib = request.form.get("pib","").strip()
        pwd = request.form.get("password","").strip()
        try:
            cur = get_db().cursor()
            cur.execute("SELECT * FROM portal_users WHERE pib=%s AND is_active=TRUE", (pib,))
            user = cur.fetchone()
            if user and verify_password(pwd, user["password_hash"]):
                session.update({"user_id": user["id"], "user_pib": user["pib"],
                                "user_firm": user["firm_name"], "user_email": user["email"]})
                return redirect(url_for("submit_request"))
            error = "Pogrešan PIB ili šifra."
        except Exception as e:
            error = "Greška pri prijavi. Pokušajte ponovo."
            print(f"Login error: {e}")
    return render_template("login.html", error=error)

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

@app.route("/zahtjev", methods=["GET", "POST"])
@login_required
def submit_request():
    if request.method == "POST":
        contact = request.form.get("contact_name","").strip()
        phone   = request.form.get("phone","").strip()
        cat     = request.form.get("category","").strip()
        desc    = request.form.get("description","").strip()
        prio    = request.form.get("priority","Normalno")
        if not contact or not cat or not desc:
            flash("Molimo popunite sva obavezna polja.")
            return render_template("request.html", categories=TASK_CATEGORIES, form_data=request.form)
        try:
            con = get_db(); cur = con.cursor()
            cur.execute("""INSERT INTO portal_requests
                (user_id,pib,firm_name,contact_name,email,phone,category,description,priority)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (session["user_id"],session["user_pib"],session["user_firm"],
                 contact,session["user_email"],phone,cat,desc,prio))
            con.commit()
        except Exception as e: print(f"DB save: {e}")

        prio_icon = "🔴 HITNO" if prio=="Hitno" else "⚪ Normalno"
        now = datetime.now().strftime('%d/%m/%Y %H:%M')
        try:
            send_email(INBOX_EMAIL,
                f"[PORTAL] {cat} — {session['user_firm']} {'🔴 HITNO' if prio=='Hitno' else ''}".strip(),
                f"""Novi zahtjev sa AccountX portala\n{'='*50}
Datum:      {now}\nPrioritet:  {prio_icon}
\nPODACI KLIJENTA:\nFirma:      {session['user_firm']}\nPIB:        {session['user_pib']}
Kontakt:    {contact}\nEmail:      {session['user_email']}\nTelefon:    {phone or '—'}
\nZAHTJEV:\nKategorija: {cat}\nOpis:\n{desc}\n{'='*50}
ACCOUNTX_PORTAL_REQUEST\nKategorija: {cat}\nKlijent_firma: {session['user_firm']}
Klijent_pib: {session['user_pib']}\nKlijent_email: {session['user_email']}\nPrioritet: {prio}""",
                reply_to=session["user_email"])
        except Exception as e: print(f"Agency email: {e}")
        try:
            send_email(session["user_email"], "AccountX — Vaš zahtjev je primljen",
                f"""Poštovani/a {contact},\n\nhvala što ste kontaktirali AccountX!\n
Vaš zahtjev je uspješno primljen.\n\nDetalji:\n- Firma: {session['user_firm']}
- Kategorija: {cat}\n- Prioritet: {prio}\n- Primljeno: {now}\n
Naš tim će vam se javiti u najkraćem roku.\n\nSrdačan pozdrav,\nAccountX DOO
tel: +382 69 330 137\nemail: ivana@accountx.me\nweb: www.accountx.me""")
        except Exception as e: print(f"Client email: {e}")
        return redirect(url_for("success"))
    return render_template("request.html", categories=TASK_CATEGORIES, form_data={})

@app.route("/uspjesno")
@login_required
def success():
    return render_template("success.html")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
