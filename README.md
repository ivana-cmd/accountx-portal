# AccountX Portal

Klijentski portal za AccountX DOO — omogućava klijentima da:
- Šalju zahtjeve agenciji
- Kreiraju ugovore o djelu (honorar saradnici) + PDF generisanje
- Šalju zahtjeve za plaćanje sa prilogom
- Kreiraju putne naloge sa automatskim obračunom + PDF
- Šalju zahtjeve za fakturisanje

## Tech stack
- Python / Flask
- PostgreSQL (Railway)
- ReportLab (PDF generisanje)
- SendGrid (email notifikacije)

## Environment varijable (Railway)

| Varijabla | Opis |
|-----------|------|
| `DATABASE_URL` | Railway PostgreSQL connection string |
| `SECRET_KEY` | Flask secret key |
| `SENDGRID_API_KEY` | SendGrid API ključ za email |
| `SENDER_EMAIL` | Email adresa pošiljaoca |
| `SENDER_NAME` | Ime pošiljaoca |
| `INBOX_EMAIL` | Email agencije koji prima obavještenja |
| `PORTAL_API_KEY` | API ključ za komunikaciju sa lokalnom app |

## Struktura

```
portal/
├── app.py                  # Glavna Flask aplikacija
├── requirements.txt
├── Procfile
├── templates/
│   ├── login.html
│   ├── zahtjev_novi.html
│   ├── moji_zahtjevi.html
│   ├── honorari.html
│   ├── placanje.html
│   ├── putni_nalog.html
│   ├── fakturisanje.html
│   ├── history.html
│   ├── request.html
│   ├── success.html
│   └── error.html
└── static/
    ├── style.css
    └── logo.png
```

## Deployment (Railway)

1. Pushuj na GitHub
2. U Railway: New Project → Deploy from GitHub repo
3. Podesi environment varijable
4. Railway automatski detektuje Procfile i deploya
