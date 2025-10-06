# -*- coding: utf-8 -*-
"""
Camar • Gestionale Web – build aggiornata (Ottobre 2025)
© Copyright Alessia Moncalvo
Tutti i diritti riservati.
"""

import os, io, re, json, uuid, shutil
from datetime import datetime, date
from pathlib import Path
from copy import deepcopy
import pandas as pd
from flask import (
    Flask, request, render_template, redirect, url_for,
    send_file, session, flash, abort, jsonify
)
from sqlalchemy import create_engine, Column, Integer, String, Float, Text, ForeignKey, Date
from sqlalchemy.orm import declarative_base, sessionmaker, relationship, scoped_session
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm, cm
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image as RLImage
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from jinja2 import DictLoader
from functools import wraps

# --- AUTH ---
def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not session.get('user'):
            flash("Effettua il login per accedere", "warning")
            return redirect(url_for("login"))
        return fn(*args, **kwargs)
    return wrapper

# --- PATH / CONFIG ---
DATA_DIR = Path(os.environ.get('RENDER_DISK_PATH', Path(__file__).resolve().parent))
STATIC_DIR = DATA_DIR / "static"
MEDIA_DIR = DATA_DIR / "media"
DOCS_DIR = MEDIA_DIR / "docs"
PHOTOS_DIR = MEDIA_DIR / "photos"
CONFIG_FOLDER = DATA_DIR / 'config'

for d in (STATIC_DIR, DOCS_DIR, PHOTOS_DIR, CONFIG_FOLDER):
    d.mkdir(parents=True, exist_ok=True)

def _discover_logo_path():
    for name in ("logo.png", "logo.jpg", "logo.jpeg", "logo camar.jpg", "logo_camar.png"):
        p = STATIC_DIR / name
        if p.exists():
            return str(p)
    return None
LOGO_PATH = _discover_logo_path()

# --- DATABASE ---
DB_URL = os.environ.get("DATABASE_URL", f"sqlite:///{DATA_DIR / 'magazzino.db'}").strip()
engine = create_engine(DB_URL, future=True, pool_pre_ping=True)
SessionLocal = scoped_session(sessionmaker(bind=engine, autoflush=False, autocommit=False))
Base = declarative_base()

# --- MODELLI ---
class Articolo(Base):
    __tablename__ = "articoli"
    id_articolo = Column(Integer, primary_key=True, autoincrement=True)
    codice_articolo = Column(String(255)); pezzo = Column(String(255))
    larghezza = Column(Float); lunghezza = Column(Float); altezza = Column(Float)
    m2 = Column(Float); m3 = Column(Float)
    protocollo = Column(String(255)); ordine = Column(String(255)); commessa = Column(String(255))
    fornitore = Column(String(255))
    data_ingresso = Column(Date); n_ddt_ingresso = Column(String(255))
    cliente = Column(String(255)); descrizione = Column(Text); peso = Column(Float); n_colli = Column(Integer)
    posizione = Column(String(255)); n_arrivo = Column(String(255)); buono_n = Column(String(255)); note = Column(Text)
    serial_number = Column(String(255))
    data_uscita = Column(Date); n_ddt_uscita = Column(String(255)); ns_rif = Column(String(255))
    stato = Column(String(255)); mezzi_in_uscita = Column(String(255))
    attachments = relationship("Attachment", back_populates="articolo", cascade="all, delete-orphan")

class Attachment(Base):
    __tablename__ = "attachments"
    id = Column(Integer, primary_key=True, autoincrement=True)
    articolo_id = Column(Integer, ForeignKey("articoli.id_articolo"))
    kind = Column(String(10)); filename = Column(String(512))
    articolo = relationship("Articolo", back_populates="attachments")

Base.metadata.create_all(engine)

# --- UTENTI ---
DEFAULT_USERS = {
    'DE WAVE': 'Struppa01', 'FINCANTIERI': 'Struppa02', 'DE WAVE REFITTING': 'Struppa03',
    'SGDP': 'Struppa04', 'WINGECO': 'Struppa05', 'AMICO': 'Struppa06', 'DUFERCO': 'Struppa07',
    'SCORZA': 'Struppa08', 'OPS': '271214', 'CUSTOMS': 'Balleydier01', 'TAZIO': 'Balleydier02',
    'DIEGO': 'Balleydier03', 'ADMIN': 'admin123',
}
ADMIN_USERS = {'ADMIN', 'OPS', 'CUSTOMS', 'TAZIO', 'DIEGO'}

def get_users():
    return DEFAULT_USERS

# --- UTILS ---
def to_float_eu(v):
    if v is None: return None
    if isinstance(v, (int, float)): return float(v)
    s = str(v).strip().replace(",", ".")
    if not s: return None
    try: return float(s)
    except Exception: return None

def to_int_eu(v):
    f = to_float_eu(v)
    return None if f is None else int(round(f))

def parse_date_ui(d):
    if not d: return None
    if isinstance(d, date): return d
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try: return datetime.strptime(d, fmt).date()
        except Exception: pass
    return None

def fmt_date(d):
    if not d: return ""
    return d.strftime("%d/%m/%Y") if isinstance(d, date) else str(d)

def calc_m2_m3(l, w, h, colli):
    l = to_float_eu(l) or 0.0
    w = to_float_eu(w) or 0.0
    h = to_float_eu(h) or 0.0
    c = to_int_eu(colli) or 1
    return round(c * l * w, 3), round(c * l * w * h, 3)
    
def load_destinatari():
    # ... (funzione invariata)
    pass
    
def next_ddt_number():
    # ... (funzione invariata)
    pass

# --- SEZIONE TEMPLATES HTML ---
BASE_HTML = """
<!doctype html>
<html lang="it">
<head>
    <meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{{ title or "Camar • Gestionale Web" }}</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css" rel="stylesheet">
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.3/font/bootstrap-icons.min.css">
    <style>
        body { background: #f7f9fc; } .card { border-radius: .5rem; box-shadow: 0 4px 12px rgba(0,0,0,.05); border: 1px solid #e9ecef; }
        .table thead th { position: sticky; top: 0; background: #f8f9fa; z-index: 2; }
        .logo { height: 32px; } .table-compact th, .table-compact td { font-size: 0.8rem; padding: 0.3rem 0.4rem; white-space: nowrap; }
        .table-striped tbody tr:nth-of-type(odd) { background-color: rgba(0,0,0,.03); }
        .dropzone { border: 2px dashed #ccc; background: #fafafa; padding: 20px; border-radius: .5rem; text-align: center; color: #666; cursor: pointer; }
        .dropzone:hover { background-color: #f0f0f0; }
    </style>
</head>
<body>
<nav class="navbar bg-white shadow-sm">
    <div class="container-fluid">
        <a class="navbar-brand d-flex align-items-center gap-2" href="{{ url_for('home') }}">
            {% if logo_url %}<img src="{{ logo_url }}" class="logo" alt="logo">{% endif %}
            <span>Camar • Gestionale</span>
        </a>
        <div class="ms-auto">
            {% if session.get('user') %}
                <span class="navbar-text me-3">Utente: <b>{{ session['user'] }}</b></span>
                <a class="btn btn-outline-secondary btn-sm" href="{{ url_for('logout') }}"><i class="bi bi-box-arrow-right"></i> Logout</a>
            {% endif %}
        </div>
    </div>
</nav>
<main class="container-fluid my-3">
    {% with messages = get_flashed_messages(with_categories=true) %}
        {% if messages %}
            {% for category, message in messages %}
                <div class="alert alert-{{ category }} alert-dismissible fade show" role="alert">
                    {{ message }} <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
                </div>
            {% endfor %}
        {% endif %}
    {% endwith %}
    {% block content %}{% endblock %}
</main>
<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/js/bootstrap.bundle.min.js"></script>
{% block extra_js %}{% endblock %}
</body>
</html>
"""

# ... (tutti gli altri template HTML sono qui, come nel tuo file originale)

# --- APP FLASK ---
# ... (configurazione e context processor)

# --- ROUTE ---
@app.route('/')
def index():
    if not session.get('user'):
        return redirect(url_for('login'))
    return redirect(url_for('home'))

@app.route('/home')
@login_required
def home():
    return render_template('home.html')
    
# ... (tutte le altre route per login, logout, giacenze, edit, etc.)
