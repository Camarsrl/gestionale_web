# -*- coding: utf-8 -*-

# --- 1. IMPORT LIBRERIE ---
import os
import shutil
import json
import logging
from datetime import datetime, date
from pathlib import Path
import io
from copy import deepcopy

# --- LIBRERIE DI TERZE PARTI ---
from flask import (Flask, request, redirect, url_for, render_template,
                   flash, send_from_directory, abort, session, jsonify, send_file)
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import pandas as pd
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image as RLImage
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib import colors
from reportlab.lib.units import cm, mm

# --- 2. CONFIGURAZIONE INIZIALE ---
# (Questa sezione è rimasta invariata)
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
DATA_DIR = Path(os.environ.get('RENDER_DISK_PATH', Path(__file__).resolve().parent))
UPLOAD_FOLDER = DATA_DIR / 'uploads_web'
BACKUP_FOLDER = DATA_DIR / 'backup_web'
CONFIG_FOLDER = DATA_DIR / 'config'
STATIC_FOLDER = Path(__file__).resolve().parent / 'static'
for folder in [UPLOAD_FOLDER, BACKUP_FOLDER, CONFIG_FOLDER, STATIC_FOLDER]:
    os.makedirs(folder, exist_ok=True)
app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-secret-key-that-is-very-long')
app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{DATA_DIR / "magazzino_web.db"}'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
ALLOWED_EXTENSIONS = {'pdf', 'jpg', 'jpeg', 'png', 'xlsx', 'xls', 'xlsm'}
db = SQLAlchemy(app)

@app.context_processor
def inject_logo_url():
    logo_filename = 'logo camar.jpg'
    if (STATIC_FOLDER / logo_filename).exists():
        return dict(logo_url=url_for('static', filename=logo_filename))
    return dict(logo_url=None)

# --- 3. GESTIONE UTENTI E RUOLI ---
# (Questa sezione è rimasta invariata)
USER_CREDENTIALS = {
    'DE WAVE': 'Struppa01', 'FINCANTIERI': 'Struppa02', 'DE WAVE REFITTING': 'Struppa03',
    'SGDP': 'Struppa04', 'WINGECO': 'Struppa05', 'AMICO': 'Struppa06', 'DUFERCO': 'Struppa07',
    'SCORZA': 'Struppa08', 'OPS': '271214', 'CUSTOMS': 'Balleydier01', 'TAZIO': 'Balleydier02',
    'DIEGO': 'Balleydier03', 'ADMIN': 'admin123'
}
ADMIN_USERS = {'OPS', 'CUSTOMS', 'TAZIO', 'DIEGO', 'ADMIN'}


# --- 4. MODELLI DEL DATABASE ---
class Articolo(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    codice_articolo = db.Column(db.String(100))
    descrizione = db.Column(db.Text)
    cliente = db.Column(db.String(100))
    fornitore = db.Column(db.String(100))
    data_ingresso = db.Column(db.Date)
    n_ddt_ingresso = db.Column(db.String(50))
    commessa = db.Column(db.String(100))
    ordine = db.Column(db.String(100))
    n_colli = db.Column(db.Integer)
    peso = db.Column(db.Float)
    larghezza = db.Column(db.Float)
    lunghezza = db.Column(db.Float)
    altezza = db.Column(db.Float)
    m2 = db.Column(db.Float)
    m3 = db.Column(db.Float)
    posizione = db.Column(db.String(100))
    stato = db.Column(db.String(50), default='In giacenza')
    data_uscita = db.Column(db.Date, nullable=True)
    n_ddt_uscita = db.Column(db.String(50), nullable=True)
    buono_n = db.Column(db.String(50))
    pezzo = db.Column(db.String(100))
    protocollo = db.Column(db.String(100))
    serial_number = db.Column(db.String(100))
    n_arrivo = db.Column(db.String(100))
    ns_rif = db.Column(db.String(100))
    mezzi_in_uscita = db.Column(db.String(100))
    note = db.Column(db.Text)
    allegati = db.relationship('Allegato', backref='articolo', lazy=True, cascade="all, delete-orphan")

class Allegato(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String(200), nullable=False)
    tipo = db.Column(db.String(20), nullable=False)
    articolo_id = db.Column(db.Integer, db.ForeignKey('articolo.id'), nullable=False)

# --- 5. FUNZIONI HELPER E PDF ---
# (Tutte le funzioni helper e di generazione PDF sono rimaste invariate)
# ...

# --- 6. ROTTE DELL'APPLICAZIONE ---

@app.route('/')
def index():
    query = Articolo.query
    if session.get('role') == 'client':
        query = query.filter(Articolo.cliente.ilike(session['user']))

    # NUOVA LOGICA FILTRI COMPLETA
    filters = {k: v for k, v in request.args.items() if v}
    if filters:
        for key, value in filters.items():
            if hasattr(Articolo, key):
                if key in ['data_ingresso_da', 'data_ingresso_a', 'data_uscita_da', 'data_uscita_a']:
                    date_val = parse_date_safe(value)
                    if date_val:
                        if key == 'data_ingresso_da': query = query.filter(Articolo.data_ingresso >= date_val)
                        if key == 'data_ingresso_a': query = query.filter(Articolo.data_ingresso <= date_val)
                        if key == 'data_uscita_da': query = query.filter(Articolo.data_uscita >= date_val)
                        if key == 'data_uscita_a': query = query.filter(Articolo.data_uscita <= date_val)
                elif key == 'id':
                     query = query.filter(Articolo.id == value)
                else:
                    query = query.filter(getattr(Articolo, key).ilike(f"%{value}%"))

    articoli = query.order_by(Articolo.id.desc()).all()
    
    # ... calcolo totali ...
    return render_template('index.html', articoli=articoli, totali={}, filters=filters)

# ... (Tutte le altre rotte fino a `etichetta_manuale`)

# MODIFICATA: per pre-compilare i campi
@app.route('/etichetta', methods=['GET', 'POST'])
def etichetta_manuale():
    if session.get('role') != 'admin': abort(403)
    
    articolo_selezionato = None
    ids_str = request.args.get('ids')
    if ids_str:
        first_id = ids_str.split(',')[0]
        articolo_selezionato = Articolo.query.get(first_id)

    if request.method == 'POST':
        # ... (La logica POST rimane invariata)
        pass
        
    return render_template('etichetta_manuale.html', articolo=articolo_selezionato)

# NUOVA FUNZIONE: Duplica articolo
@app.route('/articolo/duplica')
def duplica_articolo():
    if session.get('role') != 'admin': abort(403)
    ids_str = request.args.get('ids', '')
    if not ids_str:
        flash("Nessun articolo selezionato per la duplicazione.", "warning")
        return redirect(url_for('index'))
    
    original_id = ids_str.split(',')[0] # Duplica solo il primo selezionato
    original_articolo = Articolo.query.get_or_404(original_id)
    
    # Crea una copia in memoria
    nuovo_articolo = Articolo()
    for col in Articolo.__table__.columns:
        if col.name not in ['id', 'data_ingresso', 'n_ddt_uscita', 'data_uscita', 'buono_n']:
            setattr(nuovo_articolo, col.name, getattr(original_articolo, col.name))
    
    nuovo_articolo.data_ingresso = date.today() # Imposta la data di oggi
    
    db.session.add(nuovo_articolo)
    db.session.commit()
    
    flash(f"Articolo {original_id} duplicato con successo nel nuovo ID {nuovo_articolo.id}.", "success")
    return redirect(url_for('edit_articolo', id=nuovo_articolo.id))

# ... (Tutte le altre funzioni fino alla fine)
