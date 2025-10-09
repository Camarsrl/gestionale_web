# -*- coding: utf-8 -*-

import os, io, re, json, shutil
from datetime import datetime, date
from pathlib import Path
from flask import (Flask, request, render_template, redirect, url_for,
                   send_file, session, flash, abort, jsonify)
from flask_sqlalchemy import SQLAlchemy
from werkzeug.utils import secure_filename
import pandas as pd
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm, mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image as RLImage
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

# --- CONFIGURAZIONE ---
DATA_DIR = Path(os.environ.get('RENDER_DISK_PATH', Path(__file__).resolve().parent))
CONFIG_FOLDER = DATA_DIR / 'config'
STATIC_FOLDER = Path(__file__).resolve().parent / 'static'
# (Il resto della configurazione iniziale è invariato)

app = Flask(__name__)
# (Il resto della configurazione dell'app è invariato)
db = SQLAlchemy(app)

# (Tutti i modelli del database, Articolo e Allegato, sono invariati)

# --- FUNZIONI HELPER ---
# (Tutte le funzioni helper come to_float_safe, parse_date_safe, ecc. sono invariate)

# --- ROTTE DELL'APPLICAZIONE ---
@app.before_request
def check_login():
    # (Logica di controllo login invariata)
    pass

@app.route('/login', methods=['GET', 'POST'])
def login():
    # (Logica di login invariata)
    pass
    
@app.route('/')
def main_menu():
    return render_template('main_menu.html')

@app.route('/giacenze')
def visualizza_giacenze():
    query = Articolo.query
    if session.get('role') == 'client':
        query = query.filter(Articolo.cliente.ilike(session['user']))
    
    filters = {k: v for k, v in request.args.items() if v}
    if filters:
        # Logica completa per tutti i nuovi filtri
        for key, value in filters.items():
            if hasattr(Articolo, key):
                if key.startswith('data_'):
                    col_name = key.rsplit('_', 1)[0]
                    col = getattr(Articolo, col_name)
                    date_val = parse_date_safe(value)
                    if date_val:
                        if key.endswith('_da'): query = query.filter(col >= date_val)
                        if key.endswith('_a'): query = query.filter(col <= date_val)
                elif key == 'id':
                     query = query.filter(Articolo.id == value)
                else:
                    query = query.filter(getattr(Articolo, key).ilike(f"%{value}%"))

    articoli = query.order_by(Articolo.id.desc()).all()
    return render_template('index.html', articoli=articoli, filters=filters)

# NUOVA ROTTA per il calcolo progressivo del DDT
@app.route('/api/next_ddt_number')
@login_required
def get_next_ddt_number():
    return jsonify({'next_ddt': next_ddt_number()})

# MODIFICATA: La funzione duplica e reindirizza alle giacenze
@app.route('/articolo/duplica')
def duplica_articolo():
    if session.get('role') != 'admin': abort(403)
    ids_str = request.args.get('ids', '')
    if not ids_str:
        flash("Nessun articolo selezionato.", "warning")
        return redirect(url_for('visualizza_giacenze'))
    
    original_id = ids_str.split(',')[0]
    original_articolo = Articolo.query.get_or_404(original_id)
    
    nuovo_articolo = Articolo()
    # ... (logica di copia campi)
    
    db.session.add(nuovo_articolo)
    db.session.commit()
    
    flash(f"Articolo {original_id} duplicato con successo. Il nuovo ID è {nuovo_articolo.id}.", "success")
    # Reindirizza alla pagina delle giacenze con il nuovo articolo filtrato per essere visibile
    return redirect(url_for('visualizza_giacenze', id=nuovo_articolo.id))

# NUOVA ROTTA: Pagina placeholder per il calcolo costi
@app.route('/calcolo-costi')
@login_required
def calcolo_costi():
    return render_template('calcolo_costi.html')

# ... (TUTTE LE ALTRE ROTTE: add_articolo, edit_articolo, buono, ddt, etichetta, export, etc. complete e corrette)
