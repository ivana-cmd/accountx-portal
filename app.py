import os, hashlib, json, urllib.request, urllib.error, base64, glob
from datetime import datetime
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, flash, session, g, send_file, abort
import io


def _find_font(filename):
    """Traži TTF font na svim poznatim putanjama (Ubuntu, Railway/Nixpacks, Nix)."""
    search_patterns = [
        f"/usr/share/fonts/truetype/liberation/{filename}",
        f"/usr/share/fonts/truetype/dejavu/{filename}",
        f"/usr/share/fonts/liberation/{filename}",
        f"/usr/share/fonts/dejavu/{filename}",
        f"/usr/share/fonts/truetype/{filename}",
        f"/usr/share/fonts/{filename}",
        f"/nix/store/*/share/fonts/truetype/{filename}",
        f"/nix/store/*/share/fonts/truetype/liberation/{filename}",
        f"/nix/store/*/share/fonts/opentype/{filename}",
        f"/run/current-system/sw/share/fonts/truetype/{filename}",
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts", filename),
    ]
    for pattern in search_patterns:
        if "*" in pattern:
            matches = glob.glob(pattern)
            if matches:
                return matches[0]
        elif os.path.exists(pattern):
            return pattern
    return None


def _register_fonts():
    """Registruje TTF fontove koji podržavaju ć č š đ ž. Vraća (F_NORM, F_BOLD)."""
    try:
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont

        # Pokušaj Liberation Sans (Ubuntu/Railway)
        reg_norm = _find_font("LiberationSans-Regular.ttf")
        reg_bold = _find_font("LiberationSans-Bold.ttf")

        # Fallback: DejaVu Sans
        if not reg_norm:
            reg_norm = _find_font("DejaVuSans.ttf")
        if not reg_bold:
            reg_bold = _find_font("DejaVuSans-Bold.ttf")

        F_NORM = "Helvetica"
        F_BOLD = "Helvetica-Bold"

        if reg_norm:
            try:
                pdfmetrics.registerFont(TTFont("AppFont", reg_norm))
                F_NORM = "AppFont"
                print(f"[PDF] Font registrovan: {reg_norm}")
            except Exception as e:
                print(f"[PDF] Font greška: {e}")

        if reg_bold:
            try:
                pdfmetrics.registerFont(TTFont("AppFont-Bold", reg_bold))
                F_BOLD = "AppFont-Bold"
            except Exception as e:
                print(f"[PDF] Bold font greška: {e}")

        return F_NORM, F_BOLD
    except Exception as e:
        print(f"[PDF] _register_fonts greška: {e}")
        return "Helvetica", "Helvetica-Bold"

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

DRZAVE_DNEVNICE = {
    "Albanija": 63.0, "Angola": 123.55, "Argentina": 118.65, "Australija": 88.9,
    "Austrija": 78.75, "Avganistan": 81.20, "Azerbejdžan": 76.3, "Bahrein": 106.75,
    "Bangladeš": 36.05, "Belgija": 81.2, "Benin": 46.9, "Bolivia": 60.55,
    "Bosna i Hercegovina": 50.75, "Brazil": 64.75, "Bugarska": 79.45,
    "Burundi": 67.55, "Centralna Afrička Republika": 43.05, "Čad": 93.8,
    "Čile": 83.3, "Češka": 80.5, "Danska": 94.5, "Demokratska Rep. Kongo": 92.05,
    "Djevičanska ostrva": 120.75, "Dominikanska Republika": 84.0, "Egipat": 90.65,
    "Ekvador": 67.9, "Estonija": 63.35, "Etiopija": 64.05, "Filipini": 72.45,
    "Finska": 85.40, "Francuska": 85.75, "Gabon": 87.15, "Gana": 105.35,
    "Grčka": 77.7, "Gvajana": 72.8, "Gvatemala": 56.7, "Gvineja": 88.2,
    "Gvineja Bisao": 58.8, "Haiti": 73.5, "Holandija": 92.05, "Honduras": 64.75,
    "Hrvatska": 63.0, "Indija": 53.2, "Indonezija": 67.55, "Irak": 78.05,
    "Iran": 65.1, "Irska": 88.9, "Island": 86.8, "Italija": 80.5,
    "Izrael": 124.6, "Jamajka": 96.95, "Japan": 78.4, "Jemen": 43.4,
    "Jordan": 78.4, "Južna Afrika": 60.9, "Kambodža": 40.95, "Kamerun": 68.25,
    "Kanada": 100.8, "Kazahstan": 95.9, "Kenija": 96.6, "Kina": 86.1,
    "Kipar": 83.3, "Kolumbija": 47.6, "Korea": 128.8, "Kosovo": 65.0,
    "Kuba": 67.55, "Kuvajt": 101.5, "Lesoto": 39.2, "Letonija": 73.85,
    "Liban": 91.0, "Liberija": 75.95, "Litvanija": 64.05, "Luksemburg": 82.95,
    "Mađarska": 77.7, "Makedonija": 56.0, "Malavi": 70.7, "Malezija": 63.7,
    "Malta": 71.75, "Mauritanija": 49.35, "Meksiko": 105.0, "Moldavija": 59.85,
    "Monako": 101.5, "Mongolija": 65.8, "Namibija": 51.8, "Nepal": 53.2,
    "Nigerija": 70.35, "Nikaragva": 65.45, "Njemačka": 72.8, "Norveška": 85.75,
    "Novi Zeland": 105.35, "Oman": 102.55, "Pakistan": 69.3, "Panama": 72.45,
    "Papua Nova Gvineja": 131.6, "Paragvaj": 78.4, "Peru": 70.35, "Poljska": 75.95,
    "Porto Riko": 112.0, "Portugalija": 71.4, "Ruanda": 65.8, "Rumunija": 77.70,
    "Rusija": 143.50, "SAD": 112.35, "Sao Tome i Principe": 59.5,
    "Saudijska Arabija": 138.6, "Sejšeli": 102.9, "Sierra Leone": 83.65,
    "Singapur": 136.85, "Slovačka": 71.75, "Slovenija": 63.0, "Somalija": 53.55,
    "Srbija": 55.3, "Sudan": 71.05, "Šri Lanka": 65.8, "Španija": 74.2,
    "Švajcarska": 126.35, "Švedska": 89.95, "Tajland": 68.95, "Tanzania": 66.86,
    "Togo": 78.4, "Trinidad i Tobago": 105.35, "Tunis": 49.7, "Turska": 61.25,
    "Uganda": 69.65, "Ujedinjeni Arapski Emirati": 114.45,
    "Ujedinjeno Kraljevstvo": 96.6, "Ukrajina": 100.10, "Urugvaj": 82.95,
    "Uzbekistan": 59.5, "Venecuela": 129.5, "Vijetnam": 53.55, "Zambija": 73.15,
    "Zimbabve": 62.3, "Ostalo": 65.0,
}

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
            radno_mjesto TEXT DEFAULT '',
            polaziste TEXT DEFAULT '',
            odrediste TEXT DEFAULT '',
            drzava TEXT DEFAULT '',
            prevozno_sredstvo TEXT DEFAULT 'Automobil',
            registracija TEXT DEFAULT '',
            cijena_goriva REAL DEFAULT 0,
            kilometraza REAL DEFAULT 0,
            broj_dana INTEGER DEFAULT 1,
            dnevnica REAL DEFAULT 0,
            datum_pocetka TEXT DEFAULT '',
            datum_zavrsetka TEXT DEFAULT '',
            dodatni_troskovi_opis TEXT DEFAULT '',
            dodatni_troskovi_iznos REAL DEFAULT 0,
            ukupno_za_isplatu REAL DEFAULT 0,
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
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.units import cm
        from reportlab.lib import colors
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
        from reportlab.pdfbase.pdfmetrics import stringWidth
    except ImportError as e:
        print(f"reportlab greska: {e}")
        return None

    F_NORM, F_BOLD = _register_fonts()

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4,
        topMargin=1.8*cm, bottomMargin=3.2*cm, leftMargin=2.1*cm, rightMargin=2.1*cm)
    st = getSampleStyleSheet()
    normal = ParagraphStyle("n", parent=st["Normal"], fontName=F_NORM, fontSize=11, leading=15)
    center = ParagraphStyle("c", parent=normal, alignment=1)
    bold_c = ParagraphStyle("t", parent=normal, alignment=1, fontName=F_BOLD)

    raw_datum = ugovor.get("datum_ugovora") or datetime.today().strftime("%Y-%m-%d")
    try: datum = datetime.strptime(raw_datum, "%Y-%m-%d").strftime("%d.%m.%Y")
    except: datum = raw_datum
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
        Spacer(1, 0.35*cm), Paragraph("UGOVOR O DJELU", bold_c), Spacer(1, 0.45*cm),
        Paragraph(f'1. <b>{firma_naziv}</b> iz <b>{firma_grad}</b>, PIB <b>{firma_pib}</b>, adresa <b>{firma_adresa}</b>, u daljem tekstu NARUČILAC.', normal),
        Spacer(1, 0.18*cm), Paragraph("i", center), Spacer(1, 0.18*cm),
    ]
    p2 = f'2. <b>{saradnik["ime_prezime"]}</b> iz <b>{saradnik.get("grad") or ""}</b>, adresa <b>{saradnik.get("adresa") or ""}</b>, JMBG <b>{saradnik["maticni_broj"]}</b>, <b>{status_txt}</b>'
    if saradnik.get("firma_gdje_radi"): p2 += f', kod <b>{saradnik["firma_gdje_radi"]}</b>'
    p2 += ", u daljem tekstu SARADNIK."
    story += [Paragraph(p2, normal), Spacer(1, 0.5*cm)]

    clan_style = ParagraphStyle("clan", parent=normal, fontName=F_BOLD, alignment=1, spaceAfter=4)

    def clan(n, b):
        story.extend([Paragraph(f"Član {n}", clan_style), Spacer(1, 0.08*cm), Paragraph(b, normal), Spacer(1, 0.28*cm)])

    clan(1, f'Saradnik se ovim Ugovorom o djelu obavezuje da obavi sljedeće poslove: <b>{ugovor["opis_poslova"]}</b>.')
    clan(2, "Posao iz prethodnog člana Saradnik je dužan da obavlja u svemu kako je navedeno u ovom ugovoru i u skladu sa nalozima i uputstvima naručioca posla.")
    clan(3, "Naručilac posla se obavezuje da: - saradniku daje informacije kojima će se rukovoditi u obavljanju posla; - prati i ocjenjuje kvalitet posla koji je obavio saradnik u skladu sa svojom politikom ocjene kvaliteta; - saradniku isplati naknadu za izvršeni posao u dogovorenom iznosu.")
    b4 = f'Naručilac posla se obavezuje da Saradniku plati honorar za obavljeni posao u dogovorenom neto iznosu od <b>{honorar_money(ugovor["neto_iznos"])}</b> €. Naručilac posla će isplatu izvršiti isključivo uplatom na žiro račun Saradnika'
    if saradnik.get("banka"): b4 += f' kod <b>{saradnik["banka"]}</b> banke'
    if saradnik.get("ziro_racun"): b4 += f', broj žiro računa <b>{saradnik["ziro_racun"]}</b>'
    b4 += "."
    clan(4, b4)
    clan(5, "Naručilac se obavezuje da navedeni ugovor prijavi nadležnom poreskom organu i plati sve obavezujuće troškove poreza i doprinosa, kao i opštinskih taksi u skladu sa Zakonom, a koji su prikazani u obračunu koji je prilog ovog Ugovora.")
    clan(6, "Eventualne sporove iz ovog ugovora stranke će nastojati da riješe mirnim putem, a u suprotnom spor će rješavati stvarno nadležni sud u Podgorici. Ugovor je sačinjen u četiri istovjetna primjerka od kojih svaka strana zadržava po dva primjerka.")

    story += [PageBreak(), Paragraph("PRILOG 1 - OBRAČUN HONORARA", bold_c), Spacer(1, 0.22*cm)]
    rows = [["Stavka", "Iznos (€)"],
            ["Neto iznos", honorar_money(ugovor["neto_iznos"])],
            ["Bruto", honorar_money(ugovor["bruto"])],
            ["Osnovica", honorar_money(ugovor["osnovica"])],
            ["Porez", honorar_money(ugovor["porez"])]]
    if ugovor.get("pio") and ugovor["pio"] > 0:
        rows.append(["PIO", honorar_money(ugovor["pio"])])
    rows += [["Prirez", honorar_money(ugovor["prirez"])],
             ["Ukupan odliv sa računa", honorar_money(ugovor["ukupan_odliv"])]]
    tbl = Table(rows, colWidths=[9.5*cm, 4*cm])
    tbl.setStyle(TableStyle([
        ("FONTNAME", (0,0), (-1,-1), F_NORM), ("FONTNAME", (0,0), (-1,0), F_BOLD),
        ("BACKGROUND", (0,0), (-1,0), colors.HexColor("#4FB2AA")),
        ("TEXTCOLOR", (0,0), (-1,0), colors.white),
        ("GRID", (0,0), (-1,-1), 0.6, colors.HexColor("#FFA633")),
        ("ALIGN", (1,1), (1,-1), "RIGHT"),
    ]))
    story.append(tbl)

    # PRILOG 2 — Posebni uslovi (opciono)
    posebni = ugovor.get("posebni_uslovi","")
    if posebni and posebni.strip():
        story.append(PageBreak())
        story.append(Paragraph("PRILOG 2 - POSEBNI USLOVI", bold_c))
        story.append(Spacer(1, 0.4*cm))
        for linija in posebni.strip().split("\n"):
            if linija.strip():
                story.append(Paragraph(linija.strip(), normal))
                story.append(Spacer(1, 0.15*cm))

    doc.build(story, onFirstPage=draw_footer, onLaterPages=draw_footer)
    buf.seek(0)
    return buf.read()


# ═══════════════════════════════════════════════════════
# PUTNI NALOG — PDF GENERISANJE
# ═══════════════════════════════════════════════════════

def putni_nalog_build_pdf(nalog, firma_naziv, firma_pib, firma_adresa):
    """Generiše PDF putnog naloga prema zakonskom predlošku."""
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.units import cm
        from reportlab.lib import colors
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    except ImportError as e:
        print(f"reportlab greska: {e}")
        return None

    F_NORM, F_BOLD = _register_fonts()

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4,
                            topMargin=2.0*cm, bottomMargin=3.0*cm,
                            leftMargin=2.2*cm, rightMargin=2.2*cm)
    st = getSampleStyleSheet()
    normal = ParagraphStyle("n", parent=st["Normal"], fontName=F_NORM, fontSize=10.5, leading=16)
    center = ParagraphStyle("c", parent=normal, alignment=1)
    bold_c = ParagraphStyle("t", parent=normal, alignment=1, fontName=F_BOLD, fontSize=13)
    bold_n = ParagraphStyle("bn", parent=normal, fontName=F_BOLD)

    def fmt_date(d):
        if not d: return "___________"
        try: return datetime.strptime(str(d), "%Y-%m-%d").strftime("%d.%m.%Y")
        except: return str(d)

    def money(v):
        return f"{float(v):,.2f} €".replace(",", "X").replace(".", ",").replace("X", ".")

    datum_pocetka    = fmt_date(nalog.get("datum_pocetka",""))
    datum_zavrsetka  = fmt_date(nalog.get("datum_zavrsetka",""))
    broj_dana        = int(nalog.get("broj_dana") or 1)
    dnevnica         = float(nalog.get("dnevnica") or 0)
    kilometraza      = float(nalog.get("kilometraza") or 0)
    cijena_goriva    = float(nalog.get("cijena_goriva") or 0)
    dod_troskovi     = float(nalog.get("dodatni_troskovi_iznos") or 0)
    dod_opis         = nalog.get("dodatni_troskovi_opis") or ""
    ukupno_dnevnice  = round(broj_dana * dnevnica, 2)
    ukupno_prevoz    = round(kilometraza * 0.25 * cijena_goriva, 2)
    ukupno           = round(ukupno_dnevnice + ukupno_prevoz + dod_troskovi, 2)

    ime_prezime   = nalog.get("ime_prezime") or "___________"
    radno_mjesto  = nalog.get("radno_mjesto") or "___________"
    polaziste     = nalog.get("polaziste") or "___________"
    odrediste     = nalog.get("odrediste") or "___________"
    drzava        = nalog.get("drzava") or "___________"
    prevozno      = nalog.get("prevozno_sredstvo") or "Automobil"
    registracija  = nalog.get("registracija") or "___________"
    napomena      = nalog.get("napomena") or ""
    svrha         = napomena if napomena else "Službeni put"

    story = []

    # Zaglavlje firme
    story.append(Paragraph(f"<b>{firma_naziv}</b>", bold_n))
    story.append(Paragraph(f"PIB: {firma_pib}", normal))
    if firma_adresa:
        story.append(Paragraph(f"Adresa: {firma_adresa}", normal))
    story.append(Spacer(1, 0.5*cm))

    story.append(Paragraph("NALOG ZA SLUŽBENO PUTOVANJE", bold_c))
    story.append(Spacer(1, 0.5*cm))

    tekst = (
        f"Radnik/ca <b>{ime_prezime}</b> raspoređen/a na poslovima <b>{radno_mjesto}</b> "
        f"upućuje se na službeni put sa polaznom tačkom <b>{polaziste}</b> "
        f"dana <b>{datum_pocetka}</b> u <b>{drzava}</b>, <b>{odrediste}</b> sa zadatkom:"
    )
    story.append(Paragraph(tekst, normal))
    story.append(Spacer(1, 0.25*cm))
    story.append(Paragraph(f"<b>{svrha}</b>", normal))
    story.append(Spacer(1, 0.35*cm))

    story.append(Paragraph(
        f"Na službenom putu će koristiti <b>{prevozno}</b> registarskih oznaka <b>{registracija}</b>.",
        normal))
    story.append(Spacer(1, 0.25*cm))

    story.append(Paragraph(
        f"Zaposleni/a je za potrebe službenog putovanja gorivo plaćao/la po cijeni od "
        f"<b>{money(cijena_goriva)}/l</b> te ostvario/la pravo na naknadu 25% cijene goriva "
        f"po pređenom kilometru za potrebe putovanja.",
        normal))
    story.append(Spacer(1, 0.25*cm))

    story.append(Paragraph(
        f"Dnevnica za ovo službeno putovanje iznosi <b>{money(dnevnica)}</b>.",
        normal))
    story.append(Spacer(1, 0.6*cm))

    story.append(Paragraph("OBRAČUN TROŠKOVA PUTNOG NALOGA", bold_c))
    story.append(Spacer(1, 0.3*cm))

    obr_rows = [
        ["Stavka", "Vrijednost"],
        ["Period putovanja", f"{datum_pocetka} — {datum_zavrsetka}"],
        ["Broj dana", str(broj_dana)],
        ["Pređena kilometraža", f"{kilometraza:,.0f} km".replace(",", ".")],
        ["Dnevnica", money(dnevnica)],
        ["Ukupno dnevnice", f"{broj_dana} × {money(dnevnica)} = {money(ukupno_dnevnice)}"],
        ["Prevozni troškovi", f"{kilometraza:,.0f} km × 25% × {money(cijena_goriva)}/l = {money(ukupno_prevoz)}"],
    ]
    if dod_troskovi > 0:
        label = f"Dodatni troškovi ({dod_opis})" if dod_opis else "Dodatni troškovi"
        obr_rows.append([label, money(dod_troskovi)])
    obr_rows.append(["UKUPNO ZA ISPLATU", money(ukupno)])

    tbl = Table(obr_rows, colWidths=[10*cm, 6.5*cm])
    tbl.setStyle(TableStyle([
        ("FONTNAME",    (0,0), (-1,-1), F_NORM),
        ("FONTNAME",    (0,0), (-1,0),  F_BOLD),
        ("FONTNAME",    (0,-1),(-1,-1), F_BOLD),
        ("BACKGROUND",  (0,0), (-1,0),  colors.HexColor("#4FB2AA")),
        ("BACKGROUND",  (0,-1),(-1,-1), colors.HexColor("#FFA633")),
        ("TEXTCOLOR",   (0,0), (-1,0),  colors.white),
        ("TEXTCOLOR",   (0,-1),(-1,-1), colors.white),
        ("GRID",        (0,0), (-1,-1), 0.6, colors.HexColor("#cccccc")),
        ("ROWBACKGROUNDS",(0,1),(-1,-2),[colors.white, colors.HexColor("#f5f5f5")]),
        ("FONTSIZE",    (0,0), (-1,-1), 10),
        ("TOPPADDING",  (0,0), (-1,-1), 6),
        ("BOTTOMPADDING",(0,0),(-1,-1), 6),
        ("LEFTPADDING", (0,0), (0,-1),  8),
    ]))
    story.append(tbl)
    story.append(Spacer(1, 0.5*cm))

    story.append(Paragraph(
        f"Putni troškovi po ovom nalogu padaju na teret <b>{firma_naziv}</b>, PIB: <b>{firma_pib}</b>.",
        normal))
    story.append(Spacer(1, 2.0*cm))

    # Potpisi
    pot = [
        ["Rukovodilac", "", "Zaposleni/a"],
        ["_______________________", "", "_______________________"],
    ]
    pot_tbl = Table(pot, colWidths=[6*cm, 4*cm, 6*cm])
    pot_tbl.setStyle(TableStyle([
        ("FONTNAME",  (0,0), (-1,-1), F_NORM),
        ("FONTSIZE",  (0,0), (-1,-1), 10),
        ("ALIGN",     (2,0), (2,-1),  "RIGHT"),
        ("TOPPADDING",(0,0), (-1,-1), 4),
    ]))
    story.append(pot_tbl)

    doc.build(story)
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
        neto = float(request.form.get("neto_iznos","0").replace(".","").replace(",","."))
        opis = request.form.get("opis_poslova","").strip()
        datum = request.form.get("datum_ugovora","").strip()
        if not opis or neto <= 0:
            flash("Popunite sva obavezna polja.")
            return redirect(url_for("honorari"))
        posebni_uslovi = request.form.get("posebni_uslovi","").strip()
        obracun = honorar_calculate(saradnik["status_zaposlenja"], neto)
        ugovor_data = {"opis_poslova": opis, "neto_iznos": neto, "datum_ugovora": datum,
                       "posebni_uslovi": posebni_uslovi, **obracun}
        pdf_bytes = honorar_build_pdf_portal(
            session["user_firm"], session["user_pib"], "", "Podgorica",
            dict(saradnik), ugovor_data
        )
        pdf_filename = f"ugovor_{saradnik['ime_prezime'].replace(' ','_')}_{datum}.pdf"
        cur.execute("""INSERT INTO honorar_zahtjevi
            (user_id, pib, firm_name, saradnik_id, saradnik_ime, opis_poslova, neto_iznos,
             datum_ugovora, status, pdf_data, pdf_filename)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'Primljeno',%s,%s)""",
            (session["user_id"], session["user_pib"], session["user_firm"],
             saradnik_id, saradnik["ime_prezime"], opis, neto, datum,
             pdf_bytes, pdf_filename))
        con.commit()
        try:
            send_email(INBOX_EMAIL,
                f"[PORTAL] Novi honorar — {session['user_firm']} — {saradnik['ime_prezime']} — {neto:.2f} €",
                f"Firma: {session['user_firm']}\nSaradnik: {saradnik['ime_prezime']}\nNeto: {neto:.2f} €\nUkupan odliv: {obracun['ukupan_odliv']:.2f} €\nOpis: {opis}")
        except: pass
        flash("✅ Ugovor je kreiran! PDF je spreman za preuzimanje." if pdf_bytes else "✅ Zahtjev poslan.")
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


# ─── API: dnevnica po državi ──────────────────────────────────────────────────

@app.route("/api/dnevnica")
def api_dnevnica():
    drzava = request.args.get("drzava","")
    iznos  = DRZAVE_DNEVNICE.get(drzava, DRZAVE_DNEVNICE.get("Ostalo", 65.0))
    return {"drzava": drzava, "dnevnica": iznos}


# ─── HELPER ───────────────────────────────────────────────────────────────────

def get_user_moduli(pib):
    return {
        "zahtjevi": True, "honorari": True, "placanje": True,
        "putni_nalog": True, "fakturisanje": True,
    }


# ─── ZAHTJEV (novi) ───────────────────────────────────────────────────────────

@app.route("/zahtjev2", methods=["GET", "POST"])
@login_required
def submit_request2():
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
        racun_data = None; racun_filename = ""
        racun_file = request.files.get("racun_file")
        if racun_file and racun_file.filename:
            racun_data = racun_file.read(); racun_filename = racun_file.filename
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
        cur.execute("SELECT id, kome, iznos, hitno, status, created_at, racun_data IS NOT NULL as has_racun, racun_filename FROM portal_placanja WHERE user_id=%s ORDER BY created_at DESC",
                    (session["user_id"],))
        istorija = cur.fetchall()
    except:
        istorija = []
    return render_template("placanje.html", istorija=istorija)


# ─── PUTNI NALOG ──────────────────────────────────────────────────────────────

@app.route("/putni-nalog", methods=["GET", "POST"])
@login_required
def putni_nalog():
    # Migracija — osiguraj nove kolone ako baza ima staru shemu
    try:
        con = get_db(); cur = con.cursor()
        for col_def in [
            "ALTER TABLE portal_putni_nalozi ADD COLUMN IF NOT EXISTS radno_mjesto TEXT DEFAULT ''",
            "ALTER TABLE portal_putni_nalozi ADD COLUMN IF NOT EXISTS kilometraza REAL DEFAULT 0",
            "ALTER TABLE portal_putni_nalozi ADD COLUMN IF NOT EXISTS dnevnica REAL DEFAULT 0",
            "ALTER TABLE portal_putni_nalozi ADD COLUMN IF NOT EXISTS datum_pocetka TEXT DEFAULT ''",
            "ALTER TABLE portal_putni_nalozi ADD COLUMN IF NOT EXISTS datum_zavrsetka TEXT DEFAULT ''",
            "ALTER TABLE portal_putni_nalozi ADD COLUMN IF NOT EXISTS dodatni_troskovi_opis TEXT DEFAULT ''",
            "ALTER TABLE portal_putni_nalozi ADD COLUMN IF NOT EXISTS dodatni_troskovi_iznos REAL DEFAULT 0",
            "ALTER TABLE portal_putni_nalozi ADD COLUMN IF NOT EXISTS ukupno_za_isplatu REAL DEFAULT 0",
        ]:
            try: cur.execute(col_def)
            except: pass
        con.commit()
    except: pass

    if request.method == "POST":
        try:
            con = get_db(); cur = con.cursor()
            ime_prezime   = request.form.get("ime_prezime","").strip()
            radno_mjesto  = request.form.get("radno_mjesto","").strip()
            polaziste     = request.form.get("polaziste","").strip()
            odrediste     = request.form.get("odrediste","").strip()
            drzava        = request.form.get("drzava","").strip()
            prevozno      = request.form.get("prevozno_sredstvo","Automobil")
            registracija  = request.form.get("registracija","").strip()
            cijena_goriva = float(request.form.get("cijena_goriva","0").replace(",",".") or 0)
            kilometraza   = float(request.form.get("kilometraza","0").replace(",",".") or 0)
            broj_dana     = int(request.form.get("broj_dana","1") or 1)
            dnevnica      = float(request.form.get("dnevnica","0").replace(",",".") or 0)
            datum_pocetka = request.form.get("datum_pocetka","").strip()
            datum_zavrsetka = request.form.get("datum_zavrsetka","").strip()
            dod_opis      = request.form.get("dodatni_troskovi_opis","").strip()
            dod_iznos     = float(request.form.get("dodatni_troskovi_iznos","0").replace(",",".") or 0)
            napomena      = request.form.get("napomena","").strip()

            ukupno = round(
                broj_dana * dnevnica +
                kilometraza * 0.25 * cijena_goriva +
                dod_iznos, 2
            )

            nalog_data = dict(
                ime_prezime=ime_prezime, radno_mjesto=radno_mjesto,
                polaziste=polaziste, odrediste=odrediste, drzava=drzava,
                prevozno_sredstvo=prevozno, registracija=registracija,
                cijena_goriva=cijena_goriva, kilometraza=kilometraza,
                broj_dana=broj_dana, dnevnica=dnevnica,
                datum_pocetka=datum_pocetka, datum_zavrsetka=datum_zavrsetka,
                dodatni_troskovi_opis=dod_opis, dodatni_troskovi_iznos=dod_iznos,
                napomena=napomena,
            )

            pdf_bytes = putni_nalog_build_pdf(
                nalog_data, session["user_firm"], session["user_pib"], "")
            pdf_filename = f"putni_nalog_{ime_prezime.replace(' ','_')}_{datum_pocetka}.pdf"

            cur.execute("""INSERT INTO portal_putni_nalozi
                (user_id, pib, firm_name, ime_prezime, radno_mjesto, polaziste, odrediste,
                 drzava, prevozno_sredstvo, registracija, cijena_goriva, kilometraza,
                 broj_dana, dnevnica, datum_pocetka, datum_zavrsetka,
                 dodatni_troskovi_opis, dodatni_troskovi_iznos,
                 ukupno_za_isplatu, napomena, pdf_data, pdf_filename, status)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'Primljeno')""",
                (session["user_id"], session["user_pib"], session["user_firm"],
                 ime_prezime, radno_mjesto, polaziste, odrediste, drzava,
                 prevozno, registracija, cijena_goriva, kilometraza,
                 broj_dana, dnevnica, datum_pocetka, datum_zavrsetka,
                 dod_opis, dod_iznos, ukupno, napomena, pdf_bytes, pdf_filename))
            con.commit()

            try:
                send_email(INBOX_EMAIL,
                    f"[PORTAL] Putni nalog — {session['user_firm']} — {ime_prezime}",
                    f"Firma: {session['user_firm']}\nSaradnik: {ime_prezime}\n"
                    f"Odredište: {odrediste}, {drzava}\nBroj dana: {broj_dana}\n"
                    f"Ukupno za isplatu: {ukupno:.2f} €")
            except: pass

            flash("✅ Putni nalog je kreiran! PDF je spreman za preuzimanje.")
            return redirect(url_for("putni_nalog"))
        except Exception as e:
            import traceback; traceback.print_exc()
            flash(f"Greška: {e}")

    try:
        con = get_db(); cur = con.cursor()
        cur.execute("""SELECT id, ime_prezime, radno_mjesto, odrediste, drzava,
                          datum_pocetka, datum_zavrsetka, broj_dana, dnevnica,
                          kilometraza, ukupno_za_isplatu,
                          status, created_at,
                          pdf_data IS NOT NULL as has_pdf, pdf_filename
                   FROM portal_putni_nalozi
                   WHERE user_id=%s ORDER BY created_at DESC""", (session["user_id"],))
        istorija = cur.fetchall()
    except:
        istorija = []

    return render_template("putni_nalog.html",
                           istorija=istorija,
                           drzave=sorted(DRZAVE_DNEVNICE.keys()),
                           drzave_json=json.dumps(DRZAVE_DNEVNICE, ensure_ascii=False))


# ─── FAKTURISANJE ─────────────────────────────────────────────────────────────

@app.route("/fakturisanje", methods=["GET", "POST"])
@login_required
def fakturisanje():
    con = get_db(); cur = con.cursor()
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

    try:
        cur.execute("""SELECT id, kome, opis, iznos, status, pdf_filename, (pdf_data IS NOT NULL) as has_pdf, created_at
                       FROM faktura_zahtjevi WHERE user_id=%s ORDER BY created_at DESC""",
                    (session["user_id"],))
        zahtjevi = cur.fetchall()
    except:
        zahtjevi = []

    try:
        cur.execute("""SELECT id, naziv, broj_fakture, iznos, datum, pdf_filename, pdf_data IS NOT NULL as has_pdf, created_at
                       FROM portal_fakture WHERE pib=%s ORDER BY created_at DESC""",
                    (session["user_pib"],))
        fakture = cur.fetchall()
    except:
        fakture = []

    return render_template("fakturisanje.html", zahtjevi=zahtjevi, fakture=fakture)


# ─── DOWNLOAD RUTE ────────────────────────────────────────────────────────────

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

@app.route("/placanje/racun/<int:placanje_id>")
@login_required
def placanje_racun_download(placanje_id):
    try:
        con = get_db(); cur = con.cursor()
        cur.execute("SELECT racun_data, racun_filename FROM portal_placanja WHERE id=%s AND user_id=%s",
                    (placanje_id, session["user_id"]))
        p = cur.fetchone()
        if not p or not p["racun_data"]:
            flash("Račun nije dostupan.")
            return redirect(url_for("placanje"))
        return send_file(io.BytesIO(bytes(p["racun_data"])),
                         as_attachment=True,
                         download_name=p["racun_filename"] or f"racun_{placanje_id}.pdf",
                         mimetype="application/octet-stream")
    except Exception as e:
        flash(f"Greška: {e}")
        return redirect(url_for("placanje"))

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


# ─── API RUTE ─────────────────────────────────────────────────────────────────

@app.route("/api/task/status_update", methods=["POST"])
def api_task_status_update():
    api_key = request.headers.get("X-API-Key","")
    expected = os.environ.get("PORTAL_API_KEY", "accountx-internal-key-2024")
    if api_key != expected:
        return {"error": "Unauthorized"}, 401
    try:
        data = request.get_json()
        tip    = data.get("tip")
        req_id = data.get("id")
        status = data.get("status")
        con = get_db(); cur = con.cursor()
        if tip == "placanje":
            cur.execute("UPDATE portal_placanja SET status=%s WHERE id=%s", (status, req_id))
        elif tip == "putni":
            cur.execute("UPDATE portal_putni_nalozi SET status=%s WHERE id=%s", (status, req_id))
        elif tip == "faktura":
            cur.execute("UPDATE faktura_zahtjevi SET status=%s WHERE id=%s", (status, req_id))
        elif tip == "honorar":
            cur.execute("UPDATE honorar_zahtjevi SET status=%s WHERE id=%s", (status, req_id))
        elif tip == "opsti":
            cur.execute("UPDATE portal_requests SET status=%s WHERE id=%s", (status, req_id))
        con.commit()
        return {"success": True}, 200
    except Exception as e:
        return {"error": str(e)}, 500

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


@app.errorhandler(500)
def internal_error(e):
    print(f"500 error: {e}")
    return render_template("error.html"), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
