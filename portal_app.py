import os, hashlib, json, urllib.request, urllib.error, base64
from datetime import datetime
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, flash, session, g, send_file, abort
import io

try:
    import psycopg2, psycopg2.extras
    HAS_PG = True
except ImportError:
    HAS_PG = False

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "accountx-portal-secret")

SENDER_EMAIL  = os.environ.get("SENDER_EMAIL",  "ivana@accountx.me")
SENDER_NAME   = os.environ.get("SENDER_NAME",   "AccountX DOO")
INBOX_EMAIL   = os.environ.get("INBOX_EMAIL",   "ivana@accountx.me")
SENDGRID_KEY  = os.environ.get("SENDGRID_API_KEY", "")
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
    if db:
        try: db.close()
        except: pass

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
        CREATE TABLE IF NOT EXISTS honorar_saradnici (
            id SERIAL PRIMARY KEY,
            user_id INTEGER REFERENCES portal_users(id),
            pib TEXT NOT NULL,
            ime_prezime TEXT NOT NULL,
            maticni_broj TEXT NOT NULL,
            status_zaposlenja TEXT NOT NULL DEFAULT 'zaposlen/a',
            firma_gdje_radi TEXT DEFAULT '',
            adresa TEXT DEFAULT '',
            telefon TEXT DEFAULT '',
            ziro_racun TEXT DEFAULT '',
            banka TEXT DEFAULT '',
            grad TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT NOW()
        );
        CREATE TABLE IF NOT EXISTS honorar_zahtjevi (
            id SERIAL PRIMARY KEY,
            user_id INTEGER REFERENCES portal_users(id),
            pib TEXT NOT NULL,
            firm_name TEXT NOT NULL,
            saradnik_id INTEGER REFERENCES honorar_saradnici(id),
            saradnik_ime TEXT NOT NULL,
            opis_poslova TEXT NOT NULL,
            neto_iznos REAL NOT NULL,
            datum_ugovora TEXT DEFAULT '',
            status TEXT DEFAULT 'Primljeno',
            pdf_data BYTEA,
            pdf_filename TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT NOW()
        );
    """)
    con.commit()

def hash_password(p): return hashlib.sha256(p.encode()).hexdigest()
def verify_password(p, h): return hashlib.sha256(p.encode()).hexdigest() == h

def send_email(to_email, subject, body, reply_to=None):
    if not SENDGRID_KEY:
        print("UPOZORENJE: SENDGRID_API_KEY nije podešen!")
        return
    data = {
        "personalizations": [{"to": [{"email": to_email}]}],
        "from": {"email": SENDER_EMAIL, "name": SENDER_NAME},
        "subject": subject,
        "content": [{"type": "text/plain", "value": body}]
    }
    if reply_to:
        data["reply_to"] = {"email": reply_to}
    payload = json.dumps(data).encode("utf-8")
    req = urllib.request.Request(
        "https://api.sendgrid.com/v3/mail/send",
        data=payload,
        headers={"Authorization": f"Bearer {SENDGRID_KEY}", "Content-Type": "application/json"},
        method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            print(f"Email poslan na {to_email}, status: {resp.status}")
    except urllib.error.HTTPError as e:
        err = e.read().decode()
        print(f"SendGrid greška {e.code}: {err}")
        raise Exception(f"SendGrid greška: {err}")
    except Exception as e:
        print(f"Email greška: {e}")
        raise

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
        prio    = "Hitno" if request.form.get("priority") else "Normalno"

        if not contact or not cat or not desc:
            flash("Molimo popunite sva obavezna polja.")
            return render_template("request.html", categories=TASK_CATEGORIES, form_data=request.form)

        saved = False
        try:
            con = get_db(); cur = con.cursor()
            cur.execute("""INSERT INTO portal_requests
                (user_id,pib,firm_name,contact_name,email,phone,category,description,priority)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (session["user_id"], session["user_pib"], session["user_firm"],
                 contact, session["user_email"], phone, cat, desc, prio))
            con.commit()
            saved = True
        except Exception as e:
            print(f"DB save error: {e}")

        if not saved:
            flash("Greška pri čuvanju zahtjeva. Pokušajte ponovo.")
            return render_template("request.html", categories=TASK_CATEGORIES, form_data=request.form)

        now = datetime.now().strftime('%d/%m/%Y %H:%M')
        prio_icon = "HITNO" if prio == "Hitno" else "Normalno"
        try:
            send_email(INBOX_EMAIL,
                f"[PORTAL] {cat} — {session['user_firm']} {'HITNO' if prio=='Hitno' else ''}".strip(),
                f"Novi zahtjev sa AccountX portala\n{'='*50}\nDatum: {now}\nFirma: {session['user_firm']}\nKategorija: {cat}\nOpis:\n{desc}",
                reply_to=session["user_email"])
        except: pass
        try:
            send_email(session["user_email"], "AccountX — Vaš zahtjev je primljen",
                f"Poštovani,\n\nVaš zahtjev ({cat}) je primljen {now}.\n\nSrdačan pozdrav,\nAccountX DOO")
        except: pass
        return redirect(url_for("success"))

    return render_template("request.html", categories=TASK_CATEGORIES, form_data={})

@app.route("/uspjesno")
@login_required
def success():
    return render_template("success.html")

@app.route("/zahtjevi")
@login_required
def history():
    try:
        con = get_db(); cur = con.cursor()
        cur.execute("SELECT * FROM portal_requests WHERE user_id=%s ORDER BY created_at DESC", (session["user_id"],))
        requests = cur.fetchall()
    except Exception as e:
        print(f"History error: {e}")
        requests = []
    return render_template("history.html", requests=requests)

# ═══════════════════════════════════════════════════════
# HONORARI
# ═══════════════════════════════════════════════════════

@app.route("/honorari")
@login_required
def honorari():
    try:
        con = get_db(); cur = con.cursor()
        cur.execute("SELECT * FROM honorar_saradnici WHERE user_id=%s ORDER BY ime_prezime", (session["user_id"],))
        saradnici = cur.fetchall()
        cur.execute("""SELECT * FROM honorar_zahtjevi WHERE user_id=%s ORDER BY created_at DESC""", (session["user_id"],))
        zahtjevi = cur.fetchall()
    except Exception as e:
        print(f"Honorari error: {e}")
        saradnici = []; zahtjevi = []
    return render_template("honorari.html", saradnici=saradnici, zahtjevi=zahtjevi)

@app.route("/honorari/saradnik/add", methods=["POST"])
@login_required
def honorar_saradnik_add():
    try:
        con = get_db(); cur = con.cursor()
        cur.execute("""INSERT INTO honorar_saradnici
            (user_id, pib, ime_prezime, maticni_broj, status_zaposlenja,
             firma_gdje_radi, adresa, telefon, ziro_racun, banka, grad)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (session["user_id"], session["user_pib"],
             request.form.get("ime_prezime","").strip(),
             request.form.get("maticni_broj","").strip(),
             request.form.get("status_zaposlenja","zaposlen/a"),
             request.form.get("firma_gdje_radi","").strip(),
             request.form.get("adresa","").strip(),
             request.form.get("telefon","").strip(),
             request.form.get("ziro_racun","").strip(),
             request.form.get("banka","").strip(),
             request.form.get("grad","").strip()))
        con.commit()
        flash("✅ Saradnik je dodat.")
    except Exception as e:
        flash(f"Greška: {e}")
    return redirect(url_for("honorari"))

@app.route("/honorari/saradnik/delete/<int:sid>", methods=["POST"])
@login_required
def honorar_saradnik_delete(sid):
    try:
        con = get_db(); cur = con.cursor()
        cur.execute("DELETE FROM honorar_saradnici WHERE id=%s AND user_id=%s", (sid, session["user_id"]))
        con.commit()
        flash("Saradnik je obrisan.")
    except Exception as e:
        flash(f"Greška: {e}")
    return redirect(url_for("honorari"))

@app.route("/honorari/zahtjev/add", methods=["POST"])
@login_required
def honorar_zahtjev_add():
    try:
        con = get_db(); cur = con.cursor()
        saradnik_id = int(request.form.get("saradnik_id", 0))
        cur.execute("SELECT * FROM honorar_saradnici WHERE id=%s AND user_id=%s", (saradnik_id, session["user_id"]))
        saradnik = cur.fetchone()
        if not saradnik:
            flash("Saradnik nije pronađen.")
            return redirect(url_for("honorari"))
        neto = float(request.form.get("neto_iznos","0").replace(".","").replace(",","."))
        opis = request.form.get("opis_poslova","").strip()
        datum = request.form.get("datum_ugovora","").strip()
        if not opis or neto <= 0:
            flash("Popunite sva obavezna polja.")
            return redirect(url_for("honorari"))
        cur.execute("""INSERT INTO honorar_zahtjevi
            (user_id, pib, firm_name, saradnik_id, saradnik_ime, opis_poslova, neto_iznos, datum_ugovora, status)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'Primljeno')""",
            (session["user_id"], session["user_pib"], session["user_firm"],
             saradnik_id, saradnik["ime_prezime"], opis, neto, datum))
        con.commit()
        # Email agenciji
        try:
            send_email(INBOX_EMAIL,
                f"[PORTAL] Novi zahtjev za honorar — {session['user_firm']}",
                f"Firma: {session['user_firm']}\nSaradnik: {saradnik['ime_prezime']}\nNeto: {neto} €\nOpis: {opis}\nDatum: {datum}")
        except: pass
        flash("✅ Zahtjev za honorar je poslan agenciji.")
    except Exception as e:
        flash(f"Greška: {e}")
        print(f"Honorar zahtjev greška: {e}")
    return redirect(url_for("honorari"))

@app.route("/honorari/pdf/<int:zahtjev_id>")
@login_required
def honorar_pdf_download(zahtjev_id):
    try:
        con = get_db(); cur = con.cursor()
        cur.execute("SELECT * FROM honorar_zahtjevi WHERE id=%s AND user_id=%s", (zahtjev_id, session["user_id"]))
        z = cur.fetchone()
        if not z or not z["pdf_data"]:
            flash("PDF nije još dostupan.")
            return redirect(url_for("honorari"))
        pdf_bytes = bytes(z["pdf_data"])
        filename = z["pdf_filename"] or f"ugovor_{zahtjev_id}.pdf"
        return send_file(io.BytesIO(pdf_bytes), as_attachment=True,
                         download_name=filename, mimetype="application/pdf")
    except Exception as e:
        print(f"PDF download greška: {e}")
        flash("Greška pri preuzimanju PDF-a.")
        return redirect(url_for("honorari"))

# ── API ruta koju lokalna app poziva da uploaduje PDF ──
@app.route("/api/honorar/upload_pdf/<int:zahtjev_id>", methods=["POST"])
def honorar_pdf_upload(zahtjev_id):
    api_key = request.headers.get("X-API-Key","")
    expected = os.environ.get("PORTAL_API_KEY", "accountx-internal-key-2024")
    if api_key != expected:
        return {"error": "Unauthorized"}, 401
    try:
        con = get_db(); cur = con.cursor()
        pdf_data = request.data
        filename = request.headers.get("X-Filename", f"ugovor_{zahtjev_id}.pdf")
        cur.execute("""UPDATE honorar_zahtjevi
            SET pdf_data=%s, pdf_filename=%s, status='Završeno'
            WHERE id=%s""", (pdf_data, filename, zahtjev_id))
        con.commit()
        # Obavijesti klijenta emailom
        cur.execute("""SELECT hz.*, pu.email, pu.firm_name
            FROM honorar_zahtjevi hz
            JOIN portal_users pu ON pu.id = hz.user_id
            WHERE hz.id=%s""", (zahtjev_id,))
        z = cur.fetchone()
        if z:
            try:
                send_email(z["email"],
                    "AccountX — Vaš ugovor o djelu je spreman",
                    f"Poštovani,\n\nUgovor o djelu za saradnika {z['saradnik_ime']} je kreiran i dostupan na portalu.\n\nPrijavite se na portal da preuzmete PDF.\n\nSrdačan pozdrav,\nAccountX DOO")
            except: pass
        return {"success": True}, 200
    except Exception as e:
        print(f"Upload PDF greška: {e}")
        return {"error": str(e)}, 500

# ── API ruta — lokalna app povlači nove zahtjeve ──
@app.route("/api/honorar/zahtjevi", methods=["GET"])
def honorar_api_zahtjevi():
    api_key = request.headers.get("X-API-Key","")
    expected = os.environ.get("PORTAL_API_KEY", "accountx-internal-key-2024")
    if api_key != expected:
        return {"error": "Unauthorized"}, 401
    try:
        con = get_db(); cur = con.cursor()
        cur.execute("""
            SELECT hz.*, pu.email as user_email,
                   hs.maticni_broj, hs.status_zaposlenja, hs.firma_gdje_radi,
                   hs.adresa, hs.telefon, hs.ziro_racun, hs.banka, hs.grad
            FROM honorar_zahtjevi hz
            JOIN portal_users pu ON pu.id = hz.user_id
            LEFT JOIN honorar_saradnici hs ON hs.id = hz.saradnik_id
            WHERE hz.status = 'Primljeno'
            ORDER BY hz.created_at DESC
        """)
        rows = cur.fetchall()
        return {"zahtjevi": [dict(r) for r in rows]}, 200
    except Exception as e:
        return {"error": str(e)}, 500

@app.errorhandler(500)
def internal_error(e):
    print(f"500 error: {e}")
    return render_template("error.html"), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
