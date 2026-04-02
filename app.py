import os, hashlib, json, urllib.request, urllib.error, base64, datetime as dt_module
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
        CREATE TABLE IF NOT EXISTS portal_fakture (
            id SERIAL PRIMARY KEY,
            pib TEXT NOT NULL,
            naziv TEXT DEFAULT '',
            broj_fakture TEXT DEFAULT '',
            iznos REAL DEFAULT 0,
            datum TEXT DEFAULT '',
            pdf_data BYTEA,
            pdf_filename TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT NOW()
        );
        CREATE TABLE IF NOT EXISTS portal_placanja (
            id SERIAL PRIMARY KEY,
            user_id INTEGER REFERENCES portal_users(id),
            pib TEXT NOT NULL,
            firm_name TEXT NOT NULL,
            kome TEXT NOT NULL,
            iznos REAL NOT NULL,
            hitno INTEGER DEFAULT 0,
            napomena TEXT DEFAULT '',
            racun_data BYTEA,
            racun_filename TEXT DEFAULT '',
            status TEXT DEFAULT 'Primljeno',
            created_at TIMESTAMP DEFAULT NOW()
        );
        CREATE TABLE IF NOT EXISTS portal_putni_nalozi (
            id SERIAL PRIMARY KEY,
            user_id INTEGER REFERENCES portal_users(id),
            pib TEXT NOT NULL,
            firm_name TEXT NOT NULL,
            ime_prezime TEXT NOT NULL,
            polaziste TEXT DEFAULT '',
            odrediste TEXT DEFAULT '',
            drzava TEXT DEFAULT '',
            prevozno_sredstvo TEXT DEFAULT 'Automobil',
            registracija TEXT DEFAULT '',
            cijena_goriva REAL DEFAULT 0,
            broj_dana INTEGER DEFAULT 1,
            napomena TEXT DEFAULT '',
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


@app.route("/health")
def health():
    return "OK", 200

@app.route("/")
def index():
    return redirect(url_for("login") if not session.get("user_id") else url_for("submit_request2"))

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
                return redirect(url_for("submit_request2"))
            error = "Pogrešan PIB ili šifra."
        except Exception as e:
            error = "Greška pri prijavi. Pokušajte ponovo."
            print(f"Login error: {e}")
    try:
        return render_template("login.html", error=error)
    except Exception as e:
        return f"<h2>AccountX Portal</h2><p>Greška: {e}</p>", 500

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


# ── Honorar obračun ──────────────────────────────────────────────────────────

def honorar_money(v):
    return f"{float(v):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

def honorar_calculate(status, neto):
    status = (status or "").lower()
    if "nezaposlen" in status:
        bruto    = round(neto / 0.7515, 2)
        osnovica = round(bruto * 0.7, 2)
        porez    = round(osnovica * 0.15, 2)
        pio      = round(osnovica * 0.205, 2)
        prirez   = round(porez * 0.15, 2)
        uk       = round(neto + porez + pio + prirez, 2)
    else:
        bruto    = round(neto / 0.895, 2)
        osnovica = round(bruto * 0.7, 2)
        porez    = round(osnovica * 0.15, 2)
        pio      = 0.0
        prirez   = round(porez * 0.15, 2)
        uk       = round(neto + porez + prirez, 2)
    return dict(bruto=bruto, osnovica=osnovica, porez=porez, pio=pio, prirez=prirez, ukupan_odliv=uk)

def honorar_build_pdf_portal(firma_naziv, firma_pib, firma_adresa, firma_grad, saradnik, ugovor):
    """Generiše PDF ugovor o djelu - isti kao u lokalnoj app. Vraca bytes ili None."""
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.units import cm
        from reportlab.lib import colors
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
        from reportlab.pdfbase.pdfmetrics import stringWidth
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
    except ImportError as e:
        print(f"reportlab nije instaliran: {e}")
        return None

    # Font - na Linuxu koristimo Liberation Sans (ekvivalent Arial)
    F_NORM = "Helvetica"
    F_BOLD = "Helvetica-Bold"
    linux_fonts = [
        ("PortalArial", "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"),
        ("PortalArial", "/usr/share/fonts/liberation/LiberationSans-Regular.ttf"),
        ("PortalArial", "/usr/share/fonts/truetype/freefont/FreeSans.ttf"),
    ]
    linux_bold = [
        ("PortalArial-Bold", "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"),
        ("PortalArial-Bold", "/usr/share/fonts/liberation/LiberationSans-Bold.ttf"),
        ("PortalArial-Bold", "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf"),
    ]
    for name, path in linux_fonts:
        if os.path.exists(path):
            try: pdfmetrics.registerFont(TTFont(name, path)); F_NORM = name; break
            except: pass
    for name, path in linux_bold:
        if os.path.exists(path):
            try: pdfmetrics.registerFont(TTFont(name, path)); F_BOLD = name; break
            except: pass

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4,
        topMargin=1.8*cm, bottomMargin=3.2*cm, leftMargin=2.1*cm, rightMargin=2.1*cm)
    st = getSampleStyleSheet()
    normal = ParagraphStyle("n", parent=st["Normal"], fontName=F_NORM, fontSize=11, leading=15)
    center = ParagraphStyle("c", parent=normal, alignment=1)
    bold_c = ParagraphStyle("t", parent=normal, alignment=1, fontName=F_BOLD)

    raw_datum = ugovor.get("datum_ugovora") or datetime.today().strftime("%Y-%m-%d")
    try:
        datum = datetime.strptime(raw_datum, "%Y-%m-%d").strftime("%d.%m.%Y")
    except:
        datum = raw_datum

    status_txt = "nezaposleno lice" if "nezaposlen" in (saradnik.get("status_zaposlenja") or "").lower() else "zaposleno lice"

    def draw_footer(canvas, doc):
        canvas.saveState()
        pw, _ = A4
        lx = doc.leftMargin; rx = pw - doc.rightMargin
        ly = 1.9*cm; lbl_y = ly + 0.35*cm; date_y = ly + 1.05*cm; lw = 5.6*cm
        canvas.setFont(F_NORM, 11)
        canvas.drawString(lx, date_y, f"U Podgorici, {datum} godine")
        canvas.drawString(lx, lbl_y, "Naručilac")
        sw = stringWidth("Saradnik", F_NORM, 11)
        canvas.drawString(rx - sw, lbl_y, "Saradnik")
        canvas.line(lx, ly, lx + lw, ly)
        canvas.line(rx - lw, ly, rx, ly)
        canvas.restoreState()

    story = [
        Paragraph('Na osnovu Zakona o radu ("Službeni list Crne Gore", br. 074/19, 008/21, 059/21, 068/21, 145/21, 077/24, 084/24, 086/24, 122/25 i 165/25), zaključuje se:', normal),
        Spacer(1, 0.35*cm),
        Paragraph("UGOVOR O DJELU", bold_c),
        Spacer(1, 0.45*cm),
        Paragraph(f'1. <b>{firma_naziv}</b> iz <b>{firma_grad}</b>, PIB <b>{firma_pib}</b>, adresa <b>{firma_adresa}</b>, u daljem tekstu NARUČILAC.', normal),
        Spacer(1, 0.18*cm),
        Paragraph("i", center),
        Spacer(1, 0.18*cm),
    ]

    p2 = f'2. <b>{saradnik["ime_prezime"]}</b> iz <b>{saradnik.get("grad") or ""}</b>, adresa <b>{saradnik.get("adresa") or ""}</b>, JMBG <b>{saradnik["maticni_broj"]}</b>, <b>{status_txt}</b>'
    if saradnik.get("firma_gdje_radi"):
        p2 += f', kod <b>{saradnik["firma_gdje_radi"]}</b>'
    p2 += ", u daljem tekstu SARADNIK."
    story += [
        Paragraph(p2, normal),
        Spacer(1, 0.35*cm),
        Paragraph(f'Dana <b>{datum}</b> u <b>{firma_grad}</b> zaključili su sljedeći:', normal),
        Spacer(1, 0.38*cm)
    ]

    def clan(n, b):
        story.extend([Paragraph(f"Član {n}", normal), Spacer(1, 0.10*cm), Paragraph(b, normal), Spacer(1, 0.30*cm)])

    clan(1, f'Saradnik se ovim Ugovorom o djelu obavezuje da obavi sljedeće poslove: <b>{ugovor["opis_poslova"]}</b>.')
    clan(2, "Posao iz prethodnog člana Saradnik je dužan da obavlja u svemu kako je navedeno u ovom ugovoru i u skladu sa nalozima i uputstvima naručioca posla.")
    clan(3, "Naručilac posla se obavezuje da: - saradniku daje informacije kojima će se rukovoditi u obavljanju posla; - prati i ocjenjuje kvalitet posla koji je obavio saradnik u skladu sa svojom politikom ocjene kvaliteta; - saradniku isplati naknadu za izvršeni posao u dogovorenom iznosu.")

    b4 = f'Naručilac posla se obavezuje da Saradniku plati honorar za obavljeni posao u dogovorenom neto iznosu od <b>{honorar_money(ugovor["neto_iznos"])}</b> €. Naručilac posla će isplatu izvršiti isključivo uplatom na žiro račun Saradnika'
    if saradnik.get("banka"):
        b4 += f' kod <b>{saradnik["banka"]}</b> banke'
    if saradnik.get("ziro_racun"):
        b4 += f', broj žiro računa <b>{saradnik["ziro_racun"]}</b>'
    b4 += "."
    clan(4, b4)
    clan(5, "Naručilac se obavezuje da navedeni ugovor prijavi nadležnom poreskom organu i plati sve obavezujuće troškove poreza i doprinosa, kao i opštinskih taksi u skladu sa Zakonom, a koji su prikazani u obračunu koji je prilog ovog Ugovora.")
    clan(6, "Eventualne sporove iz ovog ugovora stranke će nastojati da riješe mirnim putem, a u suprotnom spor će rješavati stvarno nadležni sud u Podgorici. Ugovor je sačinjen u četiri istovjetna primjerka od kojih svaka strana zadržava po dva primjerka.")

    # Obračun
    story += [PageBreak(), Paragraph("PRILOG 1 - OBRAČUN HONORARA", bold_c), Spacer(1, 0.22*cm)]
    rows = [["Stavka", "Iznos (€)"],
            ["Neto iznos",              honorar_money(ugovor["neto_iznos"])],
            ["Bruto",                   honorar_money(ugovor["bruto"])],
            ["Osnovica",                honorar_money(ugovor["osnovica"])],
            ["Porez",                   honorar_money(ugovor["porez"])]]
    if ugovor.get("pio") and ugovor["pio"] > 0:
        rows.append(["PIO", honorar_money(ugovor["pio"])])
    rows += [["Prirez",                 honorar_money(ugovor["prirez"])],
             ["Ukupan odliv sa računa", honorar_money(ugovor["ukupan_odliv"])]]
    tbl = Table(rows, colWidths=[9.5*cm, 4*cm])
    tbl.setStyle(TableStyle([
        ("FONTNAME",   (0,0), (-1,-1), F_NORM),
        ("FONTNAME",   (0,0), (-1,0),  F_BOLD),
        ("BACKGROUND", (0,0), (-1,0),  colors.HexColor("#4FB2AA")),
        ("TEXTCOLOR",  (0,0), (-1,0),  colors.white),
        ("GRID",       (0,0), (-1,-1), 0.6, colors.HexColor("#FFA633")),
        ("ALIGN",      (1,1), (1,-1),  "RIGHT"),
    ]))
    story.append(tbl)

    doc.build(story, onFirstPage=draw_footer, onLaterPages=draw_footer)
    buf.seek(0)
    return buf.read()

@app.route("/honorari")
@login_required
def honorari():
    try:
        con = get_db(); cur = con.cursor()
        cur.execute("SELECT * FROM honorar_saradnici WHERE user_id=%s ORDER BY ime_prezime", (session["user_id"],))
        saradnici = cur.fetchall()
        cur.execute("""SELECT *, pdf_data IS NOT NULL as has_pdf FROM honorar_zahtjevi WHERE user_id=%s ORDER BY created_at DESC""", (session["user_id"],))
        zahtjevi = cur.fetchall()
    except Exception as e:
        print(f"Honorari error: {e}")
        saradnici = []; zahtjevi = []
    return render_template("honorari.html", saradnici=saradnici, zahtjevi=zahtjevi, now=datetime.today())

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
        neto  = float(request.form.get("neto_iznos","0").replace(".","").replace(",","."))
        opis  = request.form.get("opis_poslova","").strip()
        datum = request.form.get("datum_ugovora","").strip() or datetime.today().strftime("%Y-%m-%d")
        broj  = request.form.get("broj_ugovora","").strip()
        if not opis or neto <= 0:
            flash("Popunite sva obavezna polja.")
            return redirect(url_for("honorari"))

        # Obračun
        obracun = honorar_calculate(saradnik["status_zaposlenja"], neto)

        # Podaci firme iz session
        firma_naziv  = session["user_firm"]
        firma_pib    = session["user_pib"]
        firma_adresa = ""  # portal_users nema adresu - ostaje prazno
        firma_grad   = "Podgorica"

        ugovor_data = {
            "opis_poslova":  opis,
            "neto_iznos":    neto,
            "datum_ugovora": datum,
            "broj_ugovora":  broj,
            **obracun
        }

        # Generiši PDF odmah
        pdf_bytes = honorar_build_pdf_portal(
            firma_naziv, firma_pib, firma_adresa, firma_grad,
            dict(saradnik), ugovor_data
        )

        pdf_filename = f"ugovor_{session['user_pib']}_{saradnik['ime_prezime'].replace(' ','_')}_{datum}.pdf"

        cur.execute("""INSERT INTO honorar_zahtjevi
            (user_id, pib, firm_name, saradnik_id, saradnik_ime, opis_poslova, neto_iznos,
             datum_ugovora, status, pdf_data, pdf_filename)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'Primljeno',%s,%s)""",
            (session["user_id"], session["user_pib"], session["user_firm"],
             saradnik_id, saradnik["ime_prezime"], opis, neto, datum,
             pdf_bytes, pdf_filename))
        con.commit()

        # Email agenciji
        try:
            send_email(INBOX_EMAIL,
                f"[PORTAL] Novi honorar — {session['user_firm']} — {saradnik['ime_prezime']} — {neto:.2f} €",
                f"Firma: {session['user_firm']}\nSaradnik: {saradnik['ime_prezime']}\nNeto: {neto:.2f} €\nUkupan odliv: {obracun['ukupan_odliv']:.2f} €\nOpis: {opis}\nDatum: {datum}\n\nPDF ugovor je generisan i dostupan na portalu.")
        except: pass

        if pdf_bytes:
            flash("✅ Ugovor je kreiran i PDF je spreman za preuzimanje!")
        else:
            flash("✅ Zahtjev poslan, PDF će biti dodan od strane agencije.")
    except Exception as e:
        flash(f"Greška: {e}")
        import traceback; traceback.print_exc()
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


# ─── HELPER: module za korisnika ─────────────────────────────────────────────

def get_user_moduli(pib):
    """Čita iz lokalne baze koje module ima klijent — fallback: sve uključeno."""
    # Portal ne može direktno čitati lokalnu SQLite bazu
    # Moduli se čuvaju u portal_users extended tabeli
    # Za sada vraćamo sve module - agencija ih kontroliše kroz portal_users
    return {
        "zahtjevi": True,
        "honorari": True,
        "placanje": True,
        "putni_nalog": True,
        "fakturisanje": True,
    }


# ─── ZAHTJEV (izmjena - bez kategorija, ime, telefon) ────────────────────────

@app.route("/zahtjev2", methods=["GET", "POST"])
@login_required
def submit_request2():
    """Novi pojednostavljeni zahtjev - samo opis i hitno."""
    if request.method == "POST":
        desc = request.form.get("description","").strip()
        hitno = 1 if request.form.get("priority") else 0
        if not desc:
            flash("Unesite opis zahtjeva.")
            return render_template("zahtjev_novi.html")
        try:
            con = get_db(); cur = con.cursor()
            cur.execute("""INSERT INTO portal_requests
                (user_id, pib, firm_name, contact_name, email, phone, category, description, priority)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (session["user_id"], session["user_pib"], session["user_firm"],
                 session["user_firm"], session["user_email"], "",
                 "Opšti zahtjev", desc, "Hitno" if hitno else "Normalno"))
            con.commit()
        except Exception as e:
            flash(f"Greška: {e}")
            return render_template("zahtjev_novi.html")
        try:
            send_email(INBOX_EMAIL,
                f"[PORTAL] Zahtjev — {session['user_firm']}{'  🔴 HITNO' if hitno else ''}",
                f"Firma: {session['user_firm']}\nPIB: {session['user_pib']}\n\n{desc}")
        except: pass
        return redirect(url_for("moji_zahtjevi"))
    return render_template("zahtjev_novi.html")


@app.route("/moji-zahtjevi")
@login_required
def moji_zahtjevi():
    try:
        con = get_db(); cur = con.cursor()
        cur.execute("""SELECT * FROM portal_requests WHERE user_id=%s ORDER BY created_at DESC""",
                    (session["user_id"],))
        zahtjevi = cur.fetchall()
    except:
        zahtjevi = []
    return render_template("moji_zahtjevi.html", zahtjevi=zahtjevi)


# ─── PLAĆANJE ─────────────────────────────────────────────────────────────────

@app.route("/placanje", methods=["GET", "POST"])
@login_required
def placanje():
    if request.method == "POST":
        kome  = request.form.get("kome","").strip()
        iznos = request.form.get("iznos","0").strip()
        hitno = 1 if request.form.get("hitno") else 0
        nap   = request.form.get("napomena","").strip()
        racun_data = None
        racun_filename = ""

        racun_file = request.files.get("racun_file")
        if racun_file and racun_file.filename:
            racun_data = racun_file.read()
            racun_filename = racun_file.filename

        if not kome or not iznos:
            flash("Popunite obavezna polja.")
            return render_template("placanje.html")
        try:
            con = get_db(); cur = con.cursor()
            cur.execute("""INSERT INTO portal_placanja
                (user_id, pib, firm_name, kome, iznos, hitno, napomena, racun_data, racun_filename)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (session["user_id"], session["user_pib"], session["user_firm"],
                 kome, float(iznos.replace(",",".")), hitno, nap,
                 racun_data, racun_filename))
            con.commit()
            try:
                send_email(INBOX_EMAIL,
                    f"[PORTAL] Zahtjev za plaćanje — {session['user_firm']}{'  🔴 HITNO' if hitno else ''}",
                    f"Firma: {session['user_firm']}\nKome: {kome}\nIznos: {iznos} €\nNapomena: {nap}")
            except: pass
            flash("✅ Zahtjev za plaćanje je poslan.")
            return redirect(url_for("placanje"))
        except Exception as e:
            flash(f"Greška: {e}")
    try:
        con = get_db(); cur = con.cursor()
        cur.execute("SELECT id, kome, iznos, hitno, status, created_at FROM portal_placanja WHERE user_id=%s ORDER BY created_at DESC",
                    (session["user_id"],))
        istorija = cur.fetchall()
    except:
        istorija = []
    return render_template("placanje.html", istorija=istorija)


# ─── PUTNI NALOG ──────────────────────────────────────────────────────────────

@app.route("/putni-nalog", methods=["GET", "POST"])
@login_required
def putni_nalog():
    if request.method == "POST":
        try:
            con = get_db(); cur = con.cursor()
            cur.execute("""INSERT INTO portal_putni_nalozi
                (user_id, pib, firm_name, ime_prezime, polaziste, odrediste, drzava,
                 prevozno_sredstvo, registracija, cijena_goriva, broj_dana, napomena)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (session["user_id"], session["user_pib"], session["user_firm"],
                 request.form.get("ime_prezime","").strip(),
                 request.form.get("polaziste","").strip(),
                 request.form.get("odrediste","").strip(),
                 request.form.get("drzava","").strip(),
                 request.form.get("prevozno_sredstvo","Automobil"),
                 request.form.get("registracija","").strip(),
                 float(request.form.get("cijena_goriva","0").replace(",",".") or 0),
                 int(request.form.get("broj_dana","1") or 1),
                 request.form.get("napomena","").strip()))
            con.commit()
            try:
                send_email(INBOX_EMAIL,
                    f"[PORTAL] Putni nalog — {session['user_firm']}",
                    f"Firma: {session['user_firm']}\nSaradnik: {request.form.get('ime_prezime','')}\nOdredište: {request.form.get('odrediste','')}")
            except: pass
            flash("✅ Putni nalog je poslan.")
            return redirect(url_for("putni_nalog"))
        except Exception as e:
            flash(f"Greška: {e}")
    try:
        con = get_db(); cur = con.cursor()
        cur.execute("""SELECT id, ime_prezime, odrediste, status, created_at, pdf_data, pdf_filename
                       FROM portal_putni_nalozi WHERE user_id=%s ORDER BY created_at DESC""",
                    (session["user_id"],))
        istorija = cur.fetchall()
    except:
        istorija = []
    return render_template("putni_nalog.html", istorija=istorija)


# ─── FAKTURISANJE ─────────────────────────────────────────────────────────────

@app.route("/fakturisanje", methods=["GET", "POST"])
@login_required
def fakturisanje():
    con = get_db(); cur = con.cursor()

    # Kreiraj tabelu za zahtjeve fakturisanja ako ne postoji
    cur.execute("""CREATE TABLE IF NOT EXISTS faktura_zahtjevi (
        id SERIAL PRIMARY KEY,
        user_id INTEGER REFERENCES portal_users(id),
        pib TEXT NOT NULL,
        firm_name TEXT NOT NULL,
        kome TEXT NOT NULL,
        opis TEXT NOT NULL,
        iznos REAL DEFAULT 0,
        status TEXT DEFAULT 'Primljeno',
        pdf_data BYTEA,
        pdf_filename TEXT DEFAULT '',
        created_at TIMESTAMP DEFAULT NOW()
    )""")
    con.commit()

    if request.method == "POST":
        kome  = request.form.get("kome","").strip()
        opis  = request.form.get("opis","").strip()
        iznos = float(request.form.get("iznos","0").replace(",",".") or 0)
        if not kome or not opis:
            flash("Popunite sva obavezna polja.")
        else:
            cur.execute("""INSERT INTO faktura_zahtjevi
                (user_id, pib, firm_name, kome, opis, iznos)
                VALUES (%s,%s,%s,%s,%s,%s)""",
                (session["user_id"], session["user_pib"], session["user_firm"],
                 kome, opis, iznos))
            con.commit()
            try:
                send_email(INBOX_EMAIL,
                    f"[PORTAL] Zahtjev za fakturisanje — {session['user_firm']}",
                    f"Firma: {session['user_firm']}\nKome: {kome}\nIznos: {iznos} €\nOpis: {opis}")
            except: pass
            flash("✅ Zahtjev za fakturisanje je poslan.")
            return redirect(url_for("fakturisanje"))

    # Zahtjevi koje je klijent poslao
    try:
        cur.execute("""SELECT id, kome, opis, iznos, status, pdf_filename, pdf_data IS NOT NULL as has_pdf, created_at
                       FROM faktura_zahtjevi WHERE user_id=%s ORDER BY created_at DESC""",
                    (session["user_id"],))
        zahtjevi = cur.fetchall()
    except:
        zahtjevi = []

    # Fakture koje je agencija uploadovala
    try:
        cur.execute("""SELECT id, naziv, broj_fakture, iznos, datum, pdf_filename, created_at
                       FROM portal_fakture WHERE pib=%s ORDER BY created_at DESC""",
                    (session["user_pib"],))
        fakture = cur.fetchall()
    except:
        fakture = []

    return render_template("fakturisanje.html", zahtjevi=zahtjevi, fakture=fakture)


@app.route("/faktura/download/<int:fakt_id>")
@login_required
def faktura_download(fakt_id):
    try:
        con = get_db(); cur = con.cursor()
        cur.execute("SELECT * FROM portal_fakture WHERE id=%s AND pib=%s",
                    (fakt_id, session["user_pib"]))
        f = cur.fetchone()
        if not f or not f["pdf_data"]:
            flash("Faktura nije dostupna.")
            return redirect(url_for("fakturisanje"))
        return send_file(io.BytesIO(bytes(f["pdf_data"])),
                         as_attachment=True,
                         download_name=f["pdf_filename"] or f"faktura_{fakt_id}.pdf",
                         mimetype="application/pdf")
    except Exception as e:
        flash(f"Greška: {e}")
        return redirect(url_for("fakturisanje"))


# ─── PUTNI NALOG PDF DOWNLOAD ─────────────────────────────────────────────────

@app.route("/putni-nalog/pdf/<int:nalog_id>")
@login_required
def putni_nalog_pdf(nalog_id):
    try:
        con = get_db(); cur = con.cursor()
        cur.execute("SELECT * FROM portal_putni_nalozi WHERE id=%s AND user_id=%s",
                    (nalog_id, session["user_id"]))
        n = cur.fetchone()
        if not n or not n["pdf_data"]:
            flash("PDF nije još dostupan.")
            return redirect(url_for("putni_nalog"))
        return send_file(io.BytesIO(bytes(n["pdf_data"])),
                         as_attachment=True,
                         download_name=n["pdf_filename"] or f"putni_nalog_{nalog_id}.pdf",
                         mimetype="application/pdf")
    except Exception as e:
        flash(f"Greška: {e}")
        return redirect(url_for("putni_nalog"))


# ─── API: upload fakture sa lokalne app ───────────────────────────────────────

@app.route("/api/faktura_zahtjev/upload_pdf/<int:zahtjev_id>", methods=["POST"])
def faktura_zahtjev_pdf_upload(zahtjev_id):
    api_key = request.headers.get("X-API-Key","")
    expected = os.environ.get("PORTAL_API_KEY", "accountx-internal-key-2024")
    if api_key != expected:
        return {"error": "Unauthorized"}, 401
    try:
        con = get_db(); cur = con.cursor()
        pdf_data = request.data
        filename = request.headers.get("X-Filename", f"faktura_{zahtjev_id}.pdf")
        cur.execute("""UPDATE faktura_zahtjevi
            SET pdf_data=%s, pdf_filename=%s, status='Završeno'
            WHERE id=%s""", (pdf_data, filename, zahtjev_id))
        con.commit()
        # Email klijentu
        cur.execute("SELECT fz.*, pu.email FROM faktura_zahtjevi fz JOIN portal_users pu ON pu.id=fz.user_id WHERE fz.id=%s", (zahtjev_id,))
        z = cur.fetchone()
        if z:
            try:
                send_email(z["email"], "AccountX — Vaša faktura je spremna",
                    f"Poštovani,\n\nFaktura za '{z['opis']}' je kreirana i dostupna na portalu.\n\nSrdačan pozdrav,\nAccountX DOO")
            except: pass
        return {"success": True}, 200
    except Exception as e:
        return {"error": str(e)}, 500


@app.route("/faktura_zahtjev/download/<int:zahtjev_id>")
@login_required
def faktura_zahtjev_download(zahtjev_id):
    try:
        con = get_db(); cur = con.cursor()
        cur.execute("SELECT * FROM faktura_zahtjevi WHERE id=%s AND user_id=%s",
                    (zahtjev_id, session["user_id"]))
        z = cur.fetchone()
        if not z or not z["pdf_data"]:
            flash("PDF nije dostupan.")
            return redirect(url_for("fakturisanje"))
        return send_file(io.BytesIO(bytes(z["pdf_data"])),
                         as_attachment=True,
                         download_name=z["pdf_filename"] or f"faktura_{zahtjev_id}.pdf",
                         mimetype="application/pdf")
    except Exception as e:
        flash(f"Greška: {e}")
        return redirect(url_for("fakturisanje"))



def api_faktura_upload():
    api_key = request.headers.get("X-API-Key","")
    expected = os.environ.get("PORTAL_API_KEY", "accountx-internal-key-2024")
    if api_key != expected:
        return {"error": "Unauthorized"}, 401
    try:
        con = get_db(); cur = con.cursor()
        pib      = request.headers.get("X-PIB","")
        naziv    = request.headers.get("X-Naziv","")
        broj     = request.headers.get("X-Broj","")
        iznos    = float(request.headers.get("X-Iznos","0") or 0)
        datum    = request.headers.get("X-Datum","")
        filename = request.headers.get("X-Filename","faktura.pdf")
        pdf_data = request.data
        cur.execute("""INSERT INTO portal_fakture
            (pib, naziv, broj_fakture, iznos, datum, pdf_data, pdf_filename)
            VALUES (%s,%s,%s,%s,%s,%s,%s)""",
            (pib, naziv, broj, iznos, datum, pdf_data, filename))
        con.commit()
        return {"success": True}, 200
    except Exception as e:
        return {"error": str(e)}, 500


# ─── API: upload putnog naloga PDF ────────────────────────────────────────────

@app.route("/api/putni_nalog/upload_pdf/<int:nalog_id>", methods=["POST"])
def putni_nalog_pdf_upload(nalog_id):
    api_key = request.headers.get("X-API-Key","")
    expected = os.environ.get("PORTAL_API_KEY", "accountx-internal-key-2024")
    if api_key != expected:
        return {"error": "Unauthorized"}, 401
    try:
        con = get_db(); cur = con.cursor()
        pdf_data = request.data
        filename = request.headers.get("X-Filename", f"putni_nalog_{nalog_id}.pdf")
        cur.execute("UPDATE portal_putni_nalozi SET pdf_data=%s, pdf_filename=%s, status='Završeno' WHERE id=%s",
                    (pdf_data, filename, nalog_id))
        con.commit()
        return {"success": True}, 200
    except Exception as e:
        return {"error": str(e)}, 500


@app.errorhandler(500)
def internal_error(e):
    print(f"500 error: {e}")
    return render_template("error.html"), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
