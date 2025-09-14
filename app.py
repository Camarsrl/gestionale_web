# -*- coding: utf-8 -*-

# --- 1. IMPORT LIBRERIE ---
import os
import shutil
import json
import logging
from datetime import datetime, date
from pathlib import Path
import io

# --- LIBRERIE DI TERZE PARTI ---
from flask import (Flask, request, redirect, url_for, render_template,
                   flash, send_from_directory, abort, session, jsonify, send_file)
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import or_
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import pandas as pd
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image as RLImage
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib import colors
from reportlab.lib.units import cm, mm

# --- 2. CONFIGURAZIONE INIZIALE ---
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
ALLOWED_EXTENSIONS = {'pdf', 'jpg', 'jpeg', 'png', 'xlsx', 'xls'}

db = SQLAlchemy(app)

# Inietta globalmente l'URL del logo nei template
@app.context_processor
def inject_logo_url():
    logo_filename = 'logo camar.jpg'
    if (STATIC_FOLDER / logo_filename).exists():
        return dict(logo_url=url_for('static', filename=logo_filename))
    return dict(logo_url=None)

# --- 3. GESTIONE UTENTI E RUOLI ---
USER_CREDENTIALS = {
    'DE WAVE': 'Struppa01', 'FINCANTIERI': 'Struppa02', 'DE WAVE REFITTING': 'Struppa03',
    'SGDP': 'Struppa04', 'WINGECO': 'Struppa05', 'AMICO': 'Struppa06', 'DUFERCO': 'Struppa07',
    'SCORZA': 'Struppa08', 'OPS': '271214', 'CUSTOMS': 'Balleydier01', 'TAZIO': 'Balleydier02',
    'DIEGO': 'Balleydier03', 'ADMIN': 'admin123'
}
ADMIN_USERS = {'OPS', 'CUSTOMS', 'TAZIO', 'DIEGO', 'ADMIN'}

# --- 4. MODELLI DEL DATABASE ---
class Utente(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    ruolo = db.Column(db.String(20), nullable=False)
    def set_password(self, password): self.password_hash = generate_password_hash(password)
    def check_password(self, password): return check_password_hash(self.password_hash, password)

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

# --- 5. FUNZIONI HELPER ---
def to_float_safe(val):
    if val is None: return None
    try: return float(str(val).replace(',', '.'))
    except (ValueError, TypeError): return None

def to_int_safe(val):
    f_val = to_float_safe(val)
    return int(f_val) if f_val is not None else None
    
def parse_date_safe(date_string):
    if not date_string: return None
    for fmt in ('%Y-%m-%d', '%d/%m/%Y'):
        try: return datetime.strptime(date_string, fmt).date()
        except (ValueError, TypeError): continue
    return None

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS
    
def calculate_m2_m3(form_data):
    l = to_float_safe(form_data.get('lunghezza', 0)) or 0
    w = to_float_safe(form_data.get('larghezza', 0)) or 0
    h = to_float_safe(form_data.get('altezza', 0)) or 0
    c = to_int_safe(form_data.get('n_colli', 1)) or 1
    m2 = round(l * w * c, 3)
    m3 = round(l * w * h * c, 3)
    return m2, m3

# --- 6. ROTTE DELL'APPLICAZIONE ---
@app.before_request
def check_login():
    if 'user' not in session and request.endpoint not in ['login', 'static']:
        return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username'].upper().strip()
        password = request.form['password']
        if username in USER_CREDENTIALS and USER_CREDENTIALS[username] == password:
            session['user'] = username
            session['role'] = 'admin' if username in ADMIN_USERS else 'client'
            flash('Login effettuato con successo.', 'success')
            return redirect(url_for('index'))
        else:
            flash('Credenziali non valide.', 'danger')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    flash('Sei stato disconnesso.', 'info')
    return redirect(url_for('login'))

@app.route('/')
def index():
    query = Articolo.query
    if session.get('role') == 'client':
        query = query.filter(Articolo.cliente.ilike(session['user']))
    
    search_filters = {}
    for key, value in request.args.items():
        if value:
            search_filters[key] = value
            if hasattr(Articolo, key):
                query = query.filter(getattr(Articolo, key).ilike(f"%{value}%"))

    articoli = query.order_by(Articolo.id.desc()).all()
    return render_template('index.html', articoli=articoli, filters=search_filters)

def populate_articolo_from_form(articolo, form):
    articolo.codice_articolo = form.get('codice_articolo')
    articolo.descrizione = form.get('descrizione')
    articolo.cliente = form.get('cliente')
    articolo.fornitore = form.get('fornitore')
    articolo.data_ingresso = parse_date_safe(form.get('data_ingresso'))
    articolo.n_ddt_ingresso = form.get('n_ddt_ingresso')
    articolo.commessa = form.get('commessa')
    articolo.ordine = form.get('ordine')
    articolo.n_colli = to_int_safe(form.get('n_colli'))
    articolo.peso = to_float_safe(form.get('peso'))
    articolo.larghezza = to_float_safe(form.get('larghezza'))
    articolo.lunghezza = to_float_safe(form.get('lunghezza'))
    articolo.altezza = to_float_safe(form.get('altezza'))
    articolo.m2, articolo.m3 = calculate_m2_m3(form)
    articolo.posizione = form.get('posizione')
    articolo.stato = form.get('stato')
    articolo.note = form.get('note')
    articolo.pezzo = form.get('pezzo')
    articolo.protocollo = form.get('protocollo')
    articolo.serial_number = form.get('serial_number')
    articolo.n_arrivo = form.get('n_arrivo')
    articolo.ns_rif = form.get('ns_rif')
    articolo.mezzi_in_uscita = form.get('mezzi_in_uscita')
    articolo.buono_n = form.get('buono_n')
    articolo.data_uscita = parse_date_safe(form.get('data_uscita'))
    articolo.n_ddt_uscita = form.get('n_ddt_uscita')
    return articolo

@app.route('/articolo/nuovo', methods=['GET', 'POST'])
def add_articolo():
    if session.get('role') != 'admin': abort(403)
    if request.method == 'POST':
        nuovo_articolo = Articolo()
        populate_articolo_from_form(nuovo_articolo, request.form)
        db.session.add(nuovo_articolo)
        db.session.commit()
        flash('Articolo aggiunto con successo!', 'success')
        return redirect(url_for('edit_articolo', id=nuovo_articolo.id))
    return render_template('edit.html', articolo=None, title="Aggiungi Articolo")

@app.route('/articolo/<int:id>/modifica', methods=['GET', 'POST'])
def edit_articolo(id):
    articolo = Articolo.query.get_or_404(id)
    if session.get('role') == 'client' and session.get('user') != articolo.cliente: abort(403)
    if request.method == 'POST':
        if session.get('role') != 'admin': abort(403)
        populate_articolo_from_form(articolo, request.form)
        files = request.files.getlist('files')
        for file in files:
            if file and file.filename != '' and allowed_file(file.filename):
                filename = secure_filename(f"{articolo.id}_{datetime.now().timestamp()}_{file.filename}")
                file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                file.save(file_path)
                ext = filename.rsplit('.', 1)[1].lower()
                tipo = 'doc' if ext == 'pdf' else 'foto'
                allegato = Allegato(filename=filename, tipo=tipo, articolo_id=articolo.id)
                db.session.add(allegato)
        db.session.commit()
        flash('Articolo aggiornato con successo!', 'success')
        return redirect(url_for('edit_articolo', id=id))
    return render_template('edit.html', articolo=articolo, title="Modifica Articolo")

@app.route('/uploads/<path:filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

@app.route('/allegato/<int:id>/elimina', methods=['POST'])
def delete_attachment(id):
    if session.get('role') != 'admin': abort(403)
    allegato = Allegato.query.get_or_404(id)
    try:
        os.remove(os.path.join(app.config['UPLOAD_FOLDER'], allegato.filename))
    except OSError:
        pass 
    db.session.delete(allegato)
    db.session.commit()
    flash('Allegato eliminato.', 'success')
    return redirect(url_for('edit_articolo', id=allegato.articolo_id))

@app.route('/import', methods=['GET', 'POST'])
def import_excel():
    if session.get('role') != 'admin': abort(403)
    profiles_path = CONFIG_FOLDER / 'mappe_excel.json'
    if not profiles_path.exists():
        flash('File profili (mappe_excel.json) non trovato.', 'danger')
        return redirect(url_for('index'))
    with open(profiles_path, 'r', encoding='utf-8') as f:
        profiles = json.load(f)
    if request.method == 'POST':
        file = request.files.get('file')
        profile_name = request.form.get('profile')
        profile = profiles.get(profile_name)
        if not file or file.filename == '' or not profile:
            flash('File o profilo mancante.', 'warning')
            return redirect(request.url)
        try:
            df = pd.read_excel(file, header=profile.get('header_row', 0), dtype=str).fillna('')
            col_map = profile.get('column_map', {})
            added_count = 0
            for index, row in df.iterrows():
                first_excel_col = next(iter(col_map.keys()))
                if not row.get(first_excel_col): continue
                new_art = Articolo()
                form_data = {db_col: row.get(excel_col) for excel_col, db_col in col_map.items()}
                populate_articolo_from_form(new_art, form_data)
                db.session.add(new_art)
                added_count += 1
            db.session.commit()
            flash(f'Importazione completata. {added_count} articoli aggiunti.', 'success')
            return redirect(url_for('index'))
        except Exception as e:
            db.session.rollback()
            flash(f"Errore durante l'importazione: {e}", "danger")
            logging.error(f"Errore import: {e}", exc_info=True)
            return redirect(request.url)
    return render_template('import.html', profiles=profiles.keys())
    
@app.route('/export')
def export_excel():
    ids_str = request.args.get('ids')
    query = Articolo.query
    if session.get('role') == 'client':
        query = query.filter(Articolo.cliente.ilike(session['user']))
    if ids_str:
        try:
            ids = [int(i) for i in ids_str.split(',')]
            query = query.filter(Articolo.id.in_(ids))
        except ValueError:
            flash('ID per esportazione non validi.', 'warning')
            return redirect(url_for('index'))
    articoli = query.all()
    if not articoli:
        flash('Nessun articolo da esportare.', 'info')
        return redirect(url_for('index'))
    data = [{**{key: getattr(art, key) for key in Articolo.__table__.columns.keys()},"allegati": ", ".join([a.filename for a in art.allegati])} for art in articoli]
    df = pd.DataFrame(data)
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Giacenze')
    output.seek(0)
    return send_file(output, as_attachment=True, download_name='esportazione_giacenze.xlsx', mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')

@app.route('/pdf/buono', methods=['POST'])
def generate_pdf_buono():
    ids = request.form.getlist('selected_ids')
    if not ids:
        flash("Seleziona almeno un articolo.", "warning")
        return redirect(url_for('index'))
    articoli = Articolo.query.filter(Articolo.id.in_(ids)).all()
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=20*mm, leftMargin=20*mm, topMargin=20*mm, bottomMargin=20*mm)
    story = []
    styles = getSampleStyleSheet()
    story.append(Paragraph("Buono di Prelievo", styles['h1']))
    story.append(Spacer(1, 1*cm))
    table_data = [['ID', 'Codice Articolo', 'Descrizione', 'Cliente', 'N. Colli']]
    for art in articoli:
        table_data.append([art.id, art.codice_articolo, art.descrizione or '', art.cliente or '', art.n_colli or ''])
    t = Table(table_data, colWidths=[2*cm, 4*cm, 7*cm, 3*cm, 2*cm])
    t.setStyle(TableStyle([('BACKGROUND', (0,0), (-1,0), colors.grey), ('GRID', (0,0), (-1,-1), 1, colors.black), ('VALIGN', (0,0), (-1,-1), 'MIDDLE')]))
    story.append(t)
    doc.build(story)
    buffer.seek(0)
    return send_file(buffer, as_attachment=True, download_name='buono_prelievo.pdf', mimetype='application/pdf')

@app.route('/pdf/ddt', methods=['POST'])
def generate_pdf_ddt():
    if session.get('role') != 'admin': abort(403)
    ids = request.form.getlist('selected_ids')
    if not ids:
        flash("Seleziona almeno un articolo.", "warning")
        return redirect(url_for('index'))
    articoli = Articolo.query.filter(Articolo.id.in_(ids)).all()
    prog_file = CONFIG_FOLDER / 'progressivi_ddt.json'
    try:
        with open(prog_file, 'r') as f: progressivi = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        progressivi = {}
    anno_corrente = str(date.today().year)
    num = progressivi.get(anno_corrente, 0) + 1
    progressivi[anno_corrente] = num
    with open(prog_file, 'w') as f: json.dump(progressivi, f)
    n_ddt = f"{num:03d}/{anno_corrente[-2:]}"
    for art in articoli:
        art.n_ddt_uscita = n_ddt
        art.data_uscita = date.today()
    db.session.commit()
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=20*mm, leftMargin=20*mm, topMargin=20*mm, bottomMargin=20*mm)
    story = []
    styles = getSampleStyleSheet()
    story.append(Paragraph(f"Documento di Trasporto (DDT) N. {n_ddt}", styles['h1']))
    story.append(Spacer(1, 1*cm))
    story.append(Paragraph(f"Data: {date.today().strftime('%d/%m/%Y')}", styles['Normal']))
    story.append(Spacer(1, 1*cm))
    table_data = [['ID', 'Codice Articolo', 'Descrizione', 'Cliente', 'N. Colli', 'Peso']]
    for art in articoli:
        table_data.append([art.id, art.codice_articolo, art.descrizione or '', art.cliente or '', art.n_colli or '', art.peso or ''])
    t = Table(table_data, colWidths=[1.5*cm, 3.5*cm, 6*cm, 3*cm, 1.5*cm, 1.5*cm])
    t.setStyle(TableStyle([('BACKGROUND', (0,0), (-1,0), colors.grey), ('GRID', (0,0), (-1,-1), 1, colors.black)]))
    story.append(t)
    doc.build(story)
    buffer.seek(0)
    flash(f"Articoli scaricati con DDT N. {n_ddt}", "success")
    return send_file(buffer, as_attachment=True, download_name=f'DDT_{n_ddt.replace("/", "-")}.pdf', mimetype='application/pdf')

@app.route('/articoli/delete_bulk', methods=['POST'])
def bulk_delete():
    if session.get('role') != 'admin': abort(403)
    ids = request.form.getlist('selected_ids')
    if ids:
        Allegato.query.filter(Allegato.articolo_id.in_(ids)).delete(synchronize_session=False)
        Articolo.query.filter(Articolo.id.in_(ids)).delete(synchronize_session=False)
        db.session.commit()
        flash(f"{len(ids)} articoli eliminati con successo.", "success")
    else:
        flash("Nessun articolo selezionato per l'eliminazione.", "warning")
    return redirect(url_for('index'))

# --- 7. SETUP E AVVIO APPLICAZIONE ---
def initialize_app():
    """Esegue il backup, la configurazione del database e la copia dei file di configurazione."""
    db_path = DATA_DIR / "magazzino_web.db"
    
    if db_path.exists():
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_filename = f"magazzino_backup_{timestamp}.db"
        backup_path = BACKUP_FOLDER / backup_filename
        try:
            shutil.copy(db_path, backup_path)
            logging.info(f"Backup del database creato con successo: {backup_path}")
        except Exception as e:
            logging.error(f"Errore durante la creazione del backup: {e}")

    source_dir = Path(__file__).resolve().parent
    config_files = ['mappe_excel.json', 'progressivi_ddt.json']
    for filename in config_files:
        source_path = source_dir / filename
        dest_path = CONFIG_FOLDER / filename
        if source_path.exists() and not dest_path.exists():
            try:
                shutil.copy(source_path, dest_path)
                logging.info(f"Copiato file di configurazione '{filename}' in {CONFIG_FOLDER}")
            except Exception as e:
                logging.error(f"Impossibile copiare il file di configurazione '{filename}': {e}")

    db.create_all()
    for username, password in USER_CREDENTIALS.items():
        if not Utente.query.filter_by(username=username).first():
            ruolo = 'admin' if username in ADMIN_USERS else 'client'
            user = Utente(username=username, ruolo=ruolo)
            user.set_password(password)
            db.session.add(user)
    db.session.commit()
    logging.info("Database e utenti verificati/creati.")

with app.app_context():
    initialize_app()

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5001))
    app.run(host='0.0.0.0', port=port, debug=False)
