import os
import smtplib
import ssl
from datetime import datetime
from email.message import EmailMessage
from flask import Flask, render_template, request, redirect, url_for, flash

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "accountx-portal-secret")

# SMTP postavke — čitaju se iz environment varijabli na Render
SMTP_SERVER   = os.environ.get("SMTP_SERVER", "smtp-relay.gmail.com")
SMTP_PORT     = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USE_TLS  = os.environ.get("SMTP_USE_TLS", "1") == "1"
SMTP_USERNAME = os.environ.get("SMTP_USERNAME", "")
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")
SENDER_EMAIL  = os.environ.get("SENDER_EMAIL", "info@accountx.me")
SENDER_NAME   = os.environ.get("SENDER_NAME", "AccountX Portal")
INBOX_EMAIL   = os.environ.get("INBOX_EMAIL", "info@accountx.me")  # gdje stižu zahtjevi

TASK_CATEGORIES = [
    "Plata", "PDV", "Izvodi", "Kartica", "Ugovor", "Honorar",
    "Putni nalog", "Administracija", "Akciza", "Završni račun",
    "Plaćanja", "Preregistracija", "Kalkulacije", "Fakturisanje",
    "Pitanje / Upit", "Ostalo"
]


def send_email(to_email, subject, body, reply_to=None):
    msg = EmailMessage()
    msg["From"]    = f"{SENDER_NAME} <{SENDER_EMAIL}>"
    msg["To"]      = to_email
    msg["Subject"] = subject
    if reply_to:
        msg["Reply-To"] = reply_to
    msg.set_content(body)

    if SMTP_USE_TLS:
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT, timeout=30) as s:
            s.ehlo()
            s.starttls(context=ssl.create_default_context())
            s.ehlo()
            if SMTP_USERNAME and SMTP_PASSWORD:
                s.login(SMTP_USERNAME, SMTP_PASSWORD)
            s.send_message(msg)
    else:
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT, timeout=30) as s:
            s.ehlo()
            if SMTP_USERNAME and SMTP_PASSWORD:
                s.login(SMTP_USERNAME, SMTP_PASSWORD)
            s.send_message(msg)


@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        ime          = request.form.get("ime", "").strip()
        firma        = request.form.get("firma", "").strip()
        email        = request.form.get("email", "").strip()
        telefon      = request.form.get("telefon", "").strip()
        kategorija   = request.form.get("kategorija", "").strip()
        opis         = request.form.get("opis", "").strip()
        hitno        = request.form.get("hitno", "ne")

        if not ime or not firma or not email or not kategorija or not opis:
            flash("Molimo popunite sva obavezna polja.")
            return render_template("index.html", categories=TASK_CATEGORIES,
                                   form_data=request.form)

        # Email agenciji
        hitno_tekst = "🔴 HITNO" if hitno == "da" else "⚪ Normalno"
        agency_body = f"""Novi zahtjev sa AccountX portala
{'='*50}
Datum:      {datetime.now().strftime('%d/%m/%Y %H:%M')}
Prioritet:  {hitno_tekst}

PODACI KLIJENTA:
Ime:        {ime}
Firma:      {firma}
Email:      {email}
Telefon:    {telefon or '—'}

ZAHTJEV:
Kategorija: {kategorija}
Opis:
{opis}
{'='*50}
ACCOUNTX_PORTAL_REQUEST
Kategorija: {kategorija}
Klijent_firma: {firma}
Klijent_ime: {ime}
Klijent_email: {email}
Prioritet: {'Hitno' if hitno == 'da' else 'Normalno'}
"""
        try:
            send_email(
                to_email=INBOX_EMAIL,
                subject=f"[PORTAL] {kategorija} — {firma} {'🔴 HITNO' if hitno == 'da' else ''}".strip(),
                body=agency_body,
                reply_to=email
            )
        except Exception as e:
            print(f"Greška slanja agenciji: {e}")

        # Potvrda klijentu
        client_body = f"""Poštovani/a {ime},

hvala što ste kontaktirali AccountX!

Vaš zahtjev je uspješno primljen i biće obrađen u najkraćem mogućem roku.

Detalji zahtjeva:
- Kategorija: {kategorija}
- Prioritet: {'Hitno' if hitno == 'da' else 'Normalno'}
- Primljeno: {datetime.now().strftime('%d/%m/%Y u %H:%M')}

Naš tim će vas kontaktirati na {email}.

Srdačan pozdrav,
AccountX DOO
tel: +382 69 330 137
email: info@accountx.me
web: www.accountx.me
"""
        try:
            send_email(
                to_email=email,
                subject="AccountX — Vaš zahtjev je primljen",
                body=client_body
            )
        except Exception as e:
            print(f"Greška slanja klijentu: {e}")

        return redirect(url_for("success"))

    return render_template("index.html", categories=TASK_CATEGORIES, form_data={})


@app.route("/uspjesno")
def success():
    return render_template("success.html")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
