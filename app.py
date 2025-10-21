# -*- coding: utf-8 -*-

# --- 1. IMPORT LIBRERIE ---
import os
import shutil
import json
import logging
import calendar
import smtplib
from email.message import EmailMessage
from datetime import datetime, date
from pathlib import Path
import io
from flask import (Flask, request, redirect, url_for, render_template,
                   flash, send_from_directory, abort, session, jsonify, send_file)
from flask_sqlalchemy import SQLAlchemy
from werkzeug.utils import secure_filename
import pandas as pd
from reportlab.lib.pagesizes import A4, landscape
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image as RLImage
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
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
ALLOWED_EXTENSIONS = {'pdf', 'jpg', 'jpeg', 'png', 'xlsx', 'xls', 'xlsm'}
db = SQLAlchemy(app)

@app.context_processor
def inject_now():
    return {'now': datetime.utcnow}

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
        try: return datetime.strptime(str(date_string), fmt).date()
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

def generate_buono_prelievo_pdf(buffer, dati_buono, articoli):
    doc = SimpleDocTemplate(buffer, pagesize=A4, topMargin=1.5*cm, bottomMargin=2*cm, leftMargin=2*cm, rightMargin=2*cm)
    story = []
    styles = getSampleStyleSheet()
    body_style = styles['Normal']
    body_style.fontSize = 9
    
    logo_path = STATIC_FOLDER / 'logo camar.jpg'
    if logo_path.exists():
        img = RLImage(logo_path, width=7*cm, height=3.5*cm, hAlign='CENTER')
        story.append(img)
        story.append(Spacer(1, 1*cm))
        
    style_title = ParagraphStyle(name='Title', parent=styles['h1'], alignment=TA_CENTER, spaceAfter=6)
    style_subtitle = ParagraphStyle(name='SubTitle', parent=styles['h2'], alignment=TA_CENTER)
    story.append(Paragraph(f"BUONO PRELIEVO {dati_buono.get('numero_buono', '')}", style_title))
    story.append(Paragraph(f"{dati_buono.get('cliente', '')} - Commessa {dati_buono.get('commessa', '')}", style_subtitle))
    story.append(Spacer(1, 1*cm))
    
    style_body = ParagraphStyle(name='Body', parent=styles['Normal'], leading=14)
    story.append(Paragraph(f"<b>Data Emissione:</b> {dati_buono.get('data_emissione', '')}", style_body))
    story.append(Paragraph(f"<b>Commessa:</b> {dati_buono.get('commessa', '')}", style_body))
    story.append(Paragraph(f"<b>Fornitore:</b> {dati_buono.get('fornitore', '')}", style_body))
    story.append(Paragraph(f"<b>Protocollo:</b> {dati_buono.get('protocollo', '')}", style_body))
    story.append(Spacer(1, 1*cm))
    
    table_header = [['Ordine', 'Codice Articolo', 'Descrizione', 'Quantità', 'N.Arrivo']]
    table_data = []
    for art in articoli:
        quantita = art.pezzo or art.n_colli or '1'
        n_arrivo = art.n_arrivo or ''
        table_data.append([
            Paragraph(art.ordine or 'None', body_style),
            Paragraph(art.codice_articolo or '', body_style),
            Paragraph(art.descrizione or '', body_style),
            Paragraph(str(quantita), body_style),
            Paragraph(n_arrivo, body_style)
        ])
        
    full_table_data = table_header + table_data
    t = Table(full_table_data, colWidths=[2.5*cm, 4*cm, 7*cm, 2.5*cm, 2.5*cm])
    t.setStyle(TableStyle([('GRID', (0,0), (-1,-1), 1, colors.black),
                           ('BACKGROUND', (0,0), (-1,0), colors.lightgrey),
                           ('VALIGN', (0,0), (-1,-1), 'TOP'),
                           ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold')]))
    story.append(t)
    story.append(Spacer(1, 3*cm))
    story.append(Paragraph("Firma Magazzino: ________________________", style_body))
    story.append(Spacer(1, 1*cm))
    story.append(Paragraph("Firma Cliente: ________________________", style_body))
    doc.build(story)

def generate_ddt_pdf(buffer, ddt_data, articoli, destinatario_info):
    doc = SimpleDocTemplate(buffer, pagesize=A4, topMargin=1*cm, bottomMargin=2.5*cm, leftMargin=1.5*cm, rightMargin=1.5*cm)
    story = []
    styles = getSampleStyleSheet()
    body_style = ParagraphStyle(name='BodyWrap', parent=styles['Normal'], fontSize=8, leading=10)
    
    styles.add(ParagraphStyle(name='HeaderText', parent=styles['Normal'], alignment=TA_LEFT, leading=12))
    logo_path = STATIC_FOLDER / 'logo camar.jpg'
    logo = RLImage(logo_path, width=6*cm, height=3*cm) if logo_path.exists() else Spacer(0, 0)
    mittente_text = """<b>CAMAR S.R.L.</b><br/>Via Luigi Canepa, 2<br/>16165 Genova (GE)<br/>P.IVA / C.F. 03429300101"""
    mittente_p = Paragraph(mittente_text, styles['HeaderText'])
    header_table = Table([[logo, mittente_p]], colWidths=[7*cm, 11*cm], style=[('VALIGN', (0,0), (-1,-1), 'TOP')])
    story.append(header_table)
    story.append(Spacer(1, 1*cm))
    
    dest_rag_soc = destinatario_info.get('ragione_sociale', '')
    dest_indirizzo = destinatario_info.get('indirizzo', '')
    dest_piva = destinatario_info.get('piva', '')
    destinatario_text = f"""<b>Spett.le</b><br/>{dest_rag_soc}<br/>{dest_indirizzo}<br/>P.IVA: {dest_piva}"""
    destinatario_p = Paragraph(destinatario_text, styles['HeaderText'])
    
    data_uscita_str = ""
    data_uscita_obj = parse_date_safe(ddt_data.get('data_uscita'))
    if data_uscita_obj:
        data_uscita_str = data_uscita_obj.strftime('%d/%m/%Y')
    ddt_details_text = f"""<b>DOCUMENTO DI TRASPORTO</b><br/><b>DDT N°:</b> {ddt_data.get('n_ddt', 'N/A')}<br/><b>Data:</b> {data_uscita_str}<br/>"""
    ddt_details_p = Paragraph(ddt_details_text, styles['HeaderText'])
    details_table = Table([[destinatario_p, ddt_details_p]], colWidths=[10*cm, 8*cm], style=[('VALIGN', (0,0), (-1,-1), 'TOP')])
    story.append(details_table)
    story.append(Spacer(1, 1*cm))
    
    table_data_header = [['Descrizione della merce', 'Cod. Articolo', 'Commessa', 'Q.tà Colli', 'Peso Lordo Kg']]
    table_data_rows = []
    total_colli = 0
    total_peso = 0.0
    for art in articoli:
        table_data_rows.append([
            Paragraph(art.descrizione or '', body_style),
            Paragraph(art.codice_articolo or '', body_style),
            Paragraph(art.commessa or '', body_style),
            art.n_colli or 0,
            art.peso or 0.0
        ])
        total_colli += art.n_colli or 0
        total_peso += art.peso or 0.0
        
    full_table_data = table_data_header + table_data_rows
    article_table = Table(full_table_data, colWidths=[7*cm, 3*cm, 3*cm, 2*cm, 3*cm])
    article_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.lightgrey), ('GRID', (0,0), (-1,-1), 1, colors.black),
        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'), ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('ALIGN', (3,1), (-1,-1), 'CENTER'),
    ]))
    story.append(article_table)
    story.append(Spacer(1, 0.5*cm))
    
    body_text_style = styles['Normal']
    causale = Paragraph(f"<b>Causale del trasporto:</b> {ddt_data.get('causale_trasporto', 'C/Lavorazione')}", body_text_style)
    story.append(causale)
    story.append(Spacer(1, 1*cm))
    summary_text = f"""<b>Aspetto dei beni:</b> {ddt_data.get('aspetto_beni', 'Scatole/Pallet')}<br/><b>Totale Colli:</b> {total_colli}<br/><b>Peso Totale Lordo Kg:</b> {total_peso:.2f}<br/>"""
    summary_p = Paragraph(summary_text, body_text_style)
    story.append(summary_p)
    story.append(Spacer(1, 2*cm))
    signature_table = Table([
        ['<b>Firma Vettore</b>', '<b>Firma Destinatario</b>'], [Spacer(1, 2*cm), Spacer(1, 2*cm)],
        ['___________________', '___________________']
    ], colWidths=[9*cm, 9*cm], style=[('ALIGN', (0,0), (-1,-1), 'CENTER')])
    story.append(signature_table)
    doc.build(story)

def send_email_with_attachments(to_address, subject, body_html, attachments):
    smtp_host = os.environ.get("SMTP_HOST")
    smtp_port = int(os.environ.get("SMTP_PORT", 587))
    smtp_user = os.environ.get("SMTP_USER")
    smtp_pass = os.environ.get("SMTP_PASS")
    from_addr = os.environ.get("FROM_EMAIL", smtp_user)
    if not all([smtp_host, smtp_port, smtp_user, smtp_pass, from_addr]):
        raise ValueError("Configurazione SMTP incompleta.")
    msg = EmailMessage()
    msg["From"] = from_addr
    msg["To"] = to_address
    msg["Subject"] = subject
    msg.set_content("Per visualizzare questo messaggio, è necessario un client di posta elettronica compatibile con HTML.")
    msg.add_alternative(body_html, subtype='html')
    for att_path, att_filename in attachments:
        with open(att_path, 'rb') as f:
            file_data = f.read()
            ctype = 'application/octet-stream'
            if att_filename.endswith('.pdf'): ctype = 'application/pdf'
            elif att_filename.lower().endswith(('.jpg', '.jpeg')): ctype = 'image/jpeg'
            elif att_filename.lower().endswith('.png'): ctype = 'image/png'
            maintype, subtype = ctype.split('/', 1)
            msg.add_attachment(file_data, maintype=maintype, subtype=subtype, filename=att_filename)
    with smtplib.SMTP(smtp_host, port=smtp_port) as server:
        server.starttls()
        server.login(smtp_user, smtp_pass)
        server.send_message(msg)

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
        if USER_CREDENTIALS.get(username) == password:
            session['user'] = username
            session['role'] = 'admin' if username in ADMIN_USERS else 'client'
            flash('Login effettuato con successo.', 'success')
            return redirect(url_for('main_menu'))
        else:
            flash('Credenziali non valide.', 'danger')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    flash('Sei stato disconnesso.', 'info')
    return redirect(url_for('login'))

@app.route('/')
def main_menu():
    if 'user' not in session:
        return redirect(url_for('login'))
    return render_template('main_menu.html')

@app.route('/giacenze')
def visualizza_giacenze():
    query = Articolo.query
    if session.get('role') == 'client':
        query = query.filter(Articolo.cliente.ilike(session['user']))

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
                    try:
                        query = query.filter(Articolo.id == int(value))
                    except ValueError:
                        pass
                else:
                    query = query.filter(getattr(Articolo, key).ilike(f"%{value}%"))

    articoli = query.order_by(Articolo.id.desc()).all()

    totali = { 'colli': 0, 'peso': 0.0, 'm2': 0.0, 'm3': 0.0 }
    articoli_in_giacenza = [art for art in articoli if not art.stato or art.stato.lower() != 'uscito']
    for art in articoli_in_giacenza:
        totali['colli'] += art.n_colli or 0
        totali['peso'] += art.peso or 0.0
        totali['m2'] += art.m2 or 0.0
        totali['m3'] += art.m3 or 0.0

    return render_template('index.html', articoli=articoli, totali=totali, filters=filters)

def populate_articolo_from_form(articolo, form):
    for col in Articolo.__table__.columns:
        if col.name in form:
            value = form.get(col.name)
            if 'data' in col.name:
                setattr(articolo, col.name, parse_date_safe(value))
            elif col.name in ['peso', 'larghezza', 'lunghezza', 'altezza']:
                setattr(articolo, col.name, to_float_safe(value))
            elif col.name in ['n_colli']:
                 setattr(articolo, col.name, to_int_safe(value))
            else:
                setattr(articolo, col.name, value if value else None)

    if any(k in form for k in ['lunghezza', 'larghezza', 'altezza', 'n_colli']):
        calc_data = {
            'lunghezza': form.get('lunghezza'),
            'larghezza': form.get('larghezza'),
            'altezza': form.get('altezza'),
            'n_colli': form.get('n_colli')
        }
        articolo.m2, articolo.m3 = calculate_m2_m3(calc_data)

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
    except OSError: pass
    db.session.delete(allegato)
    db.session.commit()
    flash('Allegato eliminato.', 'success')
    return redirect(url_for('edit_articolo', id=allegato.articolo_id))

@app.route('/import', methods=['GET', 'POST'])
def import_excel():
    if session.get('role') != 'admin':
        abort(403)

    profiles_path = CONFIG_FOLDER / 'mappe_excel.json'
    if not profiles_path.exists():
        flash('File profili (mappe_excel.json) non trovato in config/.', 'danger')
        return render_template('import.html', profiles={})

    # Carica profili Excel disponibili
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
            # Legge il file Excel
            df = pd.read_excel(
                file,
                header=profile.get('header_row', 0),
                dtype=str,
                engine='openpyxl'
            ).fillna('')

            col_map = profile.get('column_map', {})
            added_count = 0

            # Lista campi realmente esistenti nel modello Articolo
            colonne_valide = set(c.name for c in Articolo.__table__.columns)

            for index, row in df.iterrows():
                if not any(row.get(excel_col) for excel_col in col_map.keys()):
                    continue

                # Crea nuovo oggetto Articolo
                new_art = Articolo()

                # Mappa i dati da Excel → colonne DB
                form_data = {}
                for excel_col, db_col in col_map.items():
                    if db_col in colonne_valide:
                        value = str(row.get(excel_col)).strip()
                        form_data[db_col] = value if value.lower() not in ['none', 'nan', ''] else None

                populate_articolo_from_form(new_art, form_data)
                db.session.add(new_art)
                added_count += 1

            db.session.commit()
            flash(f'✅ Importazione completata con successo. {added_count} articoli aggiunti.', 'success')
            return redirect(url_for('visualizza_giacenze'))

        except Exception as e:
            db.session.rollback()
            flash(f"❌ Errore durante l'importazione: {e}", "danger")
            logging.error(f"Errore import: {e}", exc_info=True)
            return redirect(request.url)

    return render_template('import.html', profiles=profiles.keys())

@app.route('/export')
def export_excel():
    ids_str = request.args.get('ids')
    query = Articolo.query
    if session.get('role') == 'client':
        query = query.filter(Articolo.cliente.ilike(session['user']))

    filters = {k: v for k, v in request.args.items() if v and k != 'ids'}
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

    if ids_str:
        try:
            ids = [int(i) for i in ids_str.split(',')]
            query = Articolo.query.filter(Articolo.id.in_(ids))
        except ValueError:
            flash('ID per esportazione non validi.', 'warning')
            return redirect(url_for('visualizza_giacenze'))

    articoli = query.order_by(Articolo.id.asc()).all()
    if not articoli:
        flash('Nessun articolo da esportare per i criteri selezionati.', 'info')
        return redirect(url_for('visualizza_giacenze'))

    data = []
    for art in articoli:
        art_data = {c.name: getattr(art, c.name) for c in art.__table__.columns}
        art_data['allegati'] = ", ".join([a.filename for a in art.allegati])
        data.append(art_data)
    df = pd.DataFrame(data)
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Giacenze')
    output.seek(0)
    filename = "esportazione_selezionata.xlsx" if ids_str else "esportazione_completa.xlsx"
    return send_file(output, as_attachment=True, download_name=filename, mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')

@app.route('/export/cliente', methods=['GET', 'POST'])
def export_by_client():
    if session.get('role') != 'admin': abort(403)
    if request.method == 'POST':
        cliente_selezionato = request.form.get('cliente')
        if not cliente_selezionato:
            flash("Nessun cliente selezionato.", "warning")
            return redirect(url_for('export_by_client'))

        articoli = Articolo.query.filter_by(cliente=cliente_selezionato).all()
        if not articoli:
            flash(f"Nessun articolo trovato per il cliente {cliente_selezionato}.", "info")
            return redirect(url_for('export_by_client'))

        data = []
        for art in articoli:
            art_data = {c.name: getattr(art, c.name) for c in art.__table__.columns}
            data.append(art_data)
        df = pd.DataFrame(data)
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df.to_excel(writer, index=False, sheet_name=cliente_selezionato)
        output.seek(0)

        return send_file(output, as_attachment=True, download_name=f'export_{cliente_selezionato}.xlsx', mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')

    clienti = db.session.query(Articolo.cliente).distinct().order_by(Articolo.cliente).all()
    return render_template('export_by_client.html', clienti=[c[0] for c in clienti if c[0]])

@app.route('/buono/setup', methods=['GET', 'POST'])
def buono_setup():
    if session.get('role') != 'admin': abort(403)
    ids_str = request.args.get('ids', '')
    if not ids_str: return redirect(url_for('visualizza_giacenze'))
    ids = [int(i) for i in ids_str.split(',')]
    articoli = Articolo.query.filter(Articolo.id.in_(ids)).all()
    primo_articolo = articoli[0] if articoli else None
    if request.method == 'POST':
        buono_n = request.form.get('buono_n')
        if not buono_n:
            flash("Il numero del buono è obbligatorio.", "danger")
            return render_template('buono_setup.html', articoli=articoli, ids=ids_str, primo_articolo=primo_articolo)
        for art in articoli: art.buono_n = buono_n
        db.session.commit()
        dati_buono = {
            'numero_buono': buono_n, 'cliente': request.form.get('cliente'),
            'commessa': request.form.get('commessa'), 'protocollo': request.form.get('protocollo'),
            'fornitore': primo_articolo.fornitore if primo_articolo else '',
            'data_emissione': date.today().strftime('%d/%m/%Y'),
        }
        buffer = io.BytesIO()
        generate_buono_prelievo_pdf(buffer, dati_buono, articoli)
        buffer.seek(0)
        flash(f"Buono N. {buono_n} assegnato. I dati sono stati salvati.", "success")
        return send_file(buffer, as_attachment=True, download_name=f'Buono_{buono_n}.pdf', mimetype='application/pdf')
    return render_template('buono_setup.html', articoli=articoli, ids=ids_str, primo_articolo=primo_articolo)

@app.route('/buono/preview', methods=['POST'])
def buono_preview():
    if session.get('role') != 'admin': abort(403)
    ids_str = request.args.get('ids', '')
    if not ids_str: return "Errore: Articoli non specificati.", 400
    ids = [int(i) for i in ids_str.split(',')]
    articoli = Articolo.query.filter(Articolo.id.in_(ids)).all()
    primo_articolo = articoli[0] if articoli else None
    dati_buono = {
        'numero_buono': request.form.get('buono_n', '(ANTEPRIMA)'), 'cliente': request.form.get('cliente'),
        'commessa': request.form.get('commessa'), 'protocollo': request.form.get('protocollo'),
        'fornitore': primo_articolo.fornitore if primo_articolo else '',
        'data_emissione': date.today().strftime('%d/%m/%Y'),
    }
    buffer = io.BytesIO()
    generate_buono_prelievo_pdf(buffer, dati_buono, articoli)
    buffer.seek(0)
    return send_file(buffer, as_attachment=False, download_name='Anteprima_Buono.pdf', mimetype='application/pdf')

def next_ddt_number():
    prog_file = CONFIG_FOLDER / "progressivi_ddt.json"
    year_short = date.today().strftime("%y")
    progressivi = {}
    if prog_file.exists():
        try:
            with open(prog_file, 'r') as f:
                progressivi = json.load(f)
        except (IOError, json.JSONDecodeError):
            progressivi = {}

    last_num = progressivi.get(year_short, 0)
    next_num = last_num + 1
    progressivi[year_short] = next_num

    try:
        with open(prog_file, 'w') as f:
            json.dump(progressivi, f)
    except IOError:
        logging.error("Impossibile salvare il file dei progressivi DDT.")
    return f"{next_num:03d}/{year_short}"

@app.route('/api/get_next_ddt_number')
def get_next_ddt_number():
    if session.get('role') != 'admin':
        abort(403)
    return jsonify({'next_ddt': next_ddt_number()})

@app.route('/ddt/finalize', methods=['POST'])
def ddt_finalize():
    if session.get('role') != 'admin':
        abort(403)

    ids_str = request.form.get('ids', '')
    if not ids_str:
        flash("Nessun articolo specificato per il DDT.", "warning")
        return redirect(url_for('visualizza_giacenze'))

    ids = [int(i) for i in ids_str.split(',')]
    n_ddt = request.form.get('n_ddt', '').strip()
    data_uscita_str = request.form.get('data_uscita', date.today().isoformat())
    data_uscita = parse_date_safe(data_uscita_str)

    if not n_ddt:
        flash("Il numero del DDT è un campo obbligatorio.", "danger")
        return redirect(request.referrer)

    articoli = db.session.query(Articolo).filter(Articolo.id.in_(ids)).all()
    for art in articoli:
        art.n_ddt_uscita = n_ddt
        art.data_uscita = data_uscita
        # art.stato = 'Uscito' # RIMOSSO COME DA RICHIESTA
        art.pezzo = to_int_safe(request.form.get(f"pezzi_{art.id}", art.pezzo))
        art.n_colli = to_int_safe(request.form.get(f"colli_{art.id}", art.n_colli))
        art.peso = to_float_safe(request.form.get(f"peso_{art.id}", art.peso))

    db.session.commit()

    dest_path = CONFIG_FOLDER / 'destinatari_saved.json'
    destinatari = {}
    if dest_path.exists():
        try:
            with open(dest_path, 'r', encoding='utf-8') as f:
                destinatari = json.load(f)
        except (json.JSONDecodeError, IOError): pass

    destinatario_scelto = destinatari.get(request.form.get('destinatario_key'), {})

    buffer = io.BytesIO()
    generate_ddt_pdf(buffer, request.form, articoli, destinatario_scelto)
    buffer.seek(0)

    flash(f"Articoli aggiornati con DDT N. {n_ddt}. I dati sono stati salvati.", "success")
    download_name = f'DDT_{n_ddt.replace("/", "-")}.pdf'
    return send_file(buffer, as_attachment=True, download_name=download_name, mimetype='application/pdf')

@app.route('/ddt/setup', methods=['GET'])
def ddt_setup():
    if session.get('role') != 'admin': abort(403)
    ids_str = request.args.get('ids', '')
    if not ids_str: return redirect(url_for('visualizza_giacenze'))
    ids = [int(i) for i in ids_str.split(',')]
    articoli = Articolo.query.filter(Articolo.id.in_(ids)).all()

    articoli_gia_usciti = [art.id for art in articoli if art.data_uscita is not None]
    if articoli_gia_usciti:
        flash(f"Attenzione: Gli articoli ID {articoli_gia_usciti} risultano già spediti (hanno una data di uscita).", "warning")
        articoli = [art for art in articoli if art.data_uscita is None]
        ids_str = ','.join(map(str, [art.id for art in articoli]))
        if not articoli:
            return redirect(url_for('visualizza_giacenze'))

    dest_path = CONFIG_FOLDER / 'destinatari_saved.json'
    destinatari = {}
    if dest_path.exists():
        try:
            with open(dest_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if isinstance(data, dict): destinatari = data
        except (json.JSONDecodeError, IOError): pass

    tot_colli = sum(art.n_colli or 0 for art in articoli)
    tot_peso = sum(art.peso or 0 for art in articoli)

    return render_template('ddt_setup.html',
        articoli=articoli,
        ids=ids_str,
        destinatari=destinatari,
        today=date.today().isoformat(),
        tot_colli=tot_colli,
        tot_peso=tot_peso)

@app.route('/ddt/preview', methods=['GET', 'POST'])
def ddt_preview():
    if session.get('role') != 'admin':
        abort(403)

    # ✅ Supporta sia POST (dal form) che GET (dal link con ?ids=...)
    ids_str = request.form.get('ids') or request.args.get('ids', '')
    if not ids_str:
        return "Errore: Articoli non specificati.", 400

    try:
        ids = [int(i) for i in ids_str.split(',') if i.isdigit()]
    except ValueError:
        return "Errore: ID non validi.", 400

    articoli = Articolo.query.filter(Articolo.id.in_(ids)).all()
    if not articoli:
        return "Errore: Nessun articolo trovato.", 400

    # ✅ Carica i destinatari salvati
    dest_path = CONFIG_FOLDER / 'destinatari_saved.json'
    destinatari = {}
    if dest_path.exists():
        try:
            with open(dest_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if isinstance(data, dict):
                    destinatari = data
        except (json.JSONDecodeError, IOError):
            pass

    # ✅ Crea PDF in memoria
    buffer = io.BytesIO()
    ddt_data = request.form.to_dict()
    ddt_data['n_ddt'] = request.form.get('n_ddt', '(ANTEPRIMA)')
    destinatario_scelto = destinatari.get(request.form.get('destinatario_key'), {})

    # Generazione del PDF del DDT
    generate_ddt_pdf(buffer, ddt_data, articoli, destinatario_scelto)

    buffer.seek(0)
    return send_file(
        buffer,
        as_attachment=False,
        download_name='ANTEPRIMA_DDT.pdf',
        mimetype='application/pdf'
    )


@app.route('/etichetta', methods=['GET'])
def etichetta_manuale():
    if session.get('role') != 'admin':
        abort(403)

    articolo_selezionato = None
    ids_str = request.args.get('ids')
    if ids_str:
        first_id = ids_str.split(',')[0]
        articolo_selezionato = Articolo.query.get(first_id)

    clienti_query = db.session.query(Articolo.cliente).distinct().order_by(Articolo.cliente).all()
    clienti = [c[0] for c in clienti_query if c[0]]

    return render_template('etichetta_manuale.html', articolo=articolo_selezionato, clienti=clienti)

@app.route('/etichetta/preview', methods=['POST'])
def etichetta_preview():
    if session.get('role') != 'admin':
        abort(403)

    buffer = io.BytesIO()
    # Etichetta orizzontale 100x62 mm, margini ridotti
    doc = SimpleDocTemplate(
        buffer,
        pagesize=landscape((100 * mm, 62 * mm)),
        leftMargin=4 * mm,
        rightMargin=4 * mm,
        topMargin=4 * mm,
        bottomMargin=4 * mm
    )

    styles = getSampleStyleSheet()
    styleN = ParagraphStyle(
        name='SmallText',
        parent=styles['Normal'],
        fontSize=8,
        leading=9,
        alignment=TA_LEFT
    )

    form_data = request.form.to_dict()

    # Ordine logico dei campi
    campi_ordinati = [
        'cliente', 'fornitore', 'ordine', 'commessa',
        'n_ddt_ingresso', 'data_ingresso', 'n_arrivo',
        'posizione', 'n_colli', 'protocollo'
    ]

    elements = []

    # Logo in alto a sinistra
    logo_path = STATIC_FOLDER / 'logo camar.jpg'
    if logo_path.exists():
        logo = RLImage(logo_path, width=20 * mm, height=10 * mm)
        elements.append(logo)
        elements.append(Spacer(1, 3 * mm))

    # Tabella con i campi
    label_data = []
    for key in campi_ordinati:
        value = form_data.get(key)
        if value and str(value).strip():
            label = key.replace('_', ' ').replace('n ', 'N. ').title()
            value_text = str(value).strip()
            if len(value_text) > 35:
                value_text = value_text[:35] + "..."
            label_data.append([
                Paragraph(f"<b>{label}:</b>", styleN),
                Paragraph(value_text, styleN)
            ])

    if not label_data:
        return "Nessun dato da stampare.", 400

    # Tabella compatta
    table = Table(label_data, colWidths=[2.8 * cm, 6.8 * cm])
    table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 1),
        ('RIGHTPADDING', (0, 0), (-1, -1), 1),
        ('TOPPADDING', (0, 0), (-1, -1), 1),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 1),
        ('ROWSPACING', (0, 0), (-1, -1), 1),
    ]))

    elements.append(table)

    try:
        # Generazione singola pagina
        doc.build(elements, onFirstPage=lambda canvas, doc: None)
    except Exception as e:
        logging.error(f"Errore generazione etichetta: {e}")
        return "Errore: testo troppo lungo per entrare nell'etichetta.", 400

    buffer.seek(0)
    return send_file(
        buffer,
        as_attachment=False,
        download_name='Etichetta.pdf',
        mimetype='application/pdf'
    )


@app.route('/articolo/duplica')
def duplica_articolo():
    if session.get('role') != 'admin': abort(403)
    ids_str = request.args.get('ids', '')
    if not ids_str:
        flash("Nessun articolo selezionato per la duplicazione.", "warning")
        return redirect(url_for('visualizza_giacenze'))
    original_id = ids_str.split(',')[0]
    original_articolo = Articolo.query.get_or_404(original_id)
    nuovo_articolo = Articolo()
    for col in Articolo.__table__.columns:
        if col.name not in ['id', 'data_ingresso', 'n_ddt_uscita', 'data_uscita', 'buono_n']:
            setattr(nuovo_articolo, col.name, getattr(original_articolo, col.name))
    nuovo_articolo.data_ingresso = date.today()
    db.session.add(nuovo_articolo)
    db.session.commit()
    flash(f"Articolo {original_id} duplicato con successo nel nuovo ID {nuovo_articolo.id}.", "success")
    return redirect(url_for('edit_articolo', id=nuovo_articolo.id))

@app.route('/articoli/delete_bulk', methods=['POST'])
def bulk_delete():
    if session.get('role') != 'admin': abort(403)
    ids_str = request.form.get('selected_ids')
    if ids_str:
        ids = [int(i) for i in ids_str.split(',')]
        Allegato.query.filter(Allegato.articolo_id.in_(ids)).delete(synchronize_session=False)
        Articolo.query.filter(Articolo.id.in_(ids)).delete(synchronize_session=False)
        db.session.commit()
        flash(f"{len(ids)} articoli eliminati con successo.", "success")
    else:
        flash("Nessun articolo selezionato per l'eliminazione.", "warning")
    return redirect(url_for('visualizza_giacenze'))

@app.route('/articoli/edit_multiple', methods=['GET', 'POST'])
def edit_multiple():
    if session.get('role') != 'admin': abort(403)
    ids_str = request.args.get('ids', '')
    if not ids_str:
        flash("Nessun articolo selezionato per la modifica.", "warning")
        return redirect(url_for('visualizza_giacenze'))
    ids = [int(i) for i in ids_str.split(',')]
    articoli = Articolo.query.filter(Articolo.id.in_(ids)).all()
    if request.method == 'POST':
        campi_da_aggiornare = {}
        for field, value in request.form.items():
            if f"update_{field}" in request.form and value.strip() != "":
                campi_da_aggiornare[field] = value

        if not campi_da_aggiornare:
            flash("Nessun campo valido selezionato per l'aggiornamento.", "warning")
            return render_template('edit_multiple.html', articoli=articoli, ids=ids_str)

        for art in articoli:
            for field, value in campi_da_aggiornare.items():
                if 'data' in field:
                    setattr(art, field, parse_date_safe(value))
                elif field in ['peso', 'larghezza', 'lunghezza', 'altezza']:
                    setattr(art, field, to_float_safe(value))
                elif field in ['n_colli']:
                    setattr(art, field, to_int_safe(value))
                else:
                    setattr(art, field, value)

            art_form_data = {col.name: getattr(art, col.name) for col in art.__table__.columns}
            art.m2, art.m3 = calculate_m2_m3(art_form_data)

        db.session.commit()
        flash(f"{len(articoli)} articoli aggiornati.", "success")
        return redirect(url_for('visualizza_giacenze'))
    return render_template('edit_multiple.html', articoli=articoli, ids=ids_str)


@app.route('/destinatari', methods=['GET', 'POST'])
def gestione_destinatari():
    if session.get('role') != 'admin': abort(403)
    dest_path = CONFIG_FOLDER / 'destinatari_saved.json'
    destinatari = {}
    try:
        with open(dest_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            if isinstance(data, dict): destinatari = data
    except (FileNotFoundError, json.JSONDecodeError): pass
    if request.method == 'POST':
        if 'delete_key' in request.form:
            key_to_delete = request.form['delete_key']
            if key_to_delete in destinatari:
                del destinatari[key_to_delete]
                flash(f'Destinatario "{key_to_delete}" eliminato.', 'success')
        else:
            nickname = request.form.get('nickname')
            ragione_sociale = request.form.get('ragione_sociale')
            indirizzo = request.form.get('indirizzo')
            piva = request.form.get('piva')
            if nickname and ragione_sociale and indirizzo:
                destinatari[nickname.upper()] = {"ragione_sociale": ragione_sociale, "indirizzo": indirizzo, "piva": piva}
                flash(f'Destinatario "{nickname.upper()}" aggiunto/aggiornato.', 'success')
            else:
                flash('Nickname, Ragione Sociale e Indirizzo sono obbligatori.', 'warning')
        with open(dest_path, 'w', encoding='utf-8') as f: json.dump(destinatari, f, indent=4, ensure_ascii=False)
        return redirect(url_for('gestione_destinatari'))
    return render_template('destinatari.html', destinatari=destinatari)

# --- FUNZIONE REPORT CORRETTA ---
# La versione precedente chiamava una funzione non esistente (genera_report_costi).
# Ho ripristinato la versione corretta che permette di calcolare la giacenza per cliente/mese.
from sqlalchemy import or_, and_

@app.route('/report', methods=['GET', 'POST'])
def report():
    if session.get('role') != 'admin':
        abort(403)

    risultato = None

    if request.method == 'POST':
        cliente = request.form.get('cliente')
        mese_anno = request.form.get('mese_anno')

        if cliente and mese_anno:
            try:
                # Estrae anno e mese (es: "2025-09")
                anno, mese = map(int, mese_anno.split('-'))
                ultimo_giorno = calendar.monthrange(anno, mese)[1]
                fine_mese = date(anno, mese, ultimo_giorno)

                # Evita date future (utile su Render/UTC)
                oggi = date.today()
                if fine_mese > oggi:
                    fine_mese = oggi

                # Articoli ancora in giacenza a fine mese
                articoli_in_giacenza = Articolo.query.filter(
                    Articolo.cliente == cliente,
                    Articolo.data_ingresso <= fine_mese,
                    or_(
                        Articolo.data_uscita == None,
                        Articolo.data_uscita > fine_mese
                    )
                ).all()

                # Calcolo m² totali
                m2_totali = sum(float(art.m2 or 0) for art in articoli_in_giacenza)

                if not articoli_in_giacenza:
                    flash(f"Nessun articolo trovato per {cliente} in giacenza al {fine_mese.strftime('%d/%m/%Y')}.", "info")

                risultato = {
                    "cliente": cliente,
                    "periodo": fine_mese.strftime("%m-%Y"),
                    "m2_totali": round(m2_totali, 3),
                    "conteggio_articoli": len(articoli_in_giacenza)
                }

            except ValueError:
                flash("Formato data non valido. Usa YYYY-MM.", "danger")

    # Elenco clienti per il menu a tendina
    clienti = db.session.query(Articolo.cliente).distinct().order_by(Articolo.cliente).all()
    clienti = [c[0] for c in clienti if c[0]]

    return render_template('report.html', clienti=clienti, risultato=risultato)

@app.route('/calcolo-costi')
def calcolo_costi():
    return redirect(url_for('report'))

@app.route('/api/attachments')
def get_attachments():
    ids_str = request.args.get('ids', '')
    if not ids_str: return jsonify([])
    ids = [int(i) for i in ids_str.split(',')]
    allegati = Allegato.query.filter(Allegato.articolo_id.in_(ids)).all()
    return jsonify([{'id': a.id, 'filename': a.filename, 'articolo_id': a.articolo_id} for a in allegati])

@app.route('/email/invia', methods=['POST'])
def invia_email():
    if session.get('role') != 'admin': abort(403)
    to_addr = request.form.get('email_destinatario')
    subject = request.form.get('email_oggetto')
    allegati_ids = request.form.getlist('allegati_selezionati')
    if not to_addr or not subject or not allegati_ids:
        flash("Compila tutti i campi per inviare l'email.", "warning")
        return redirect(request.referrer or url_for('visualizza_giacenze'))
    allegati_da_inviare = Allegato.query.filter(Allegato.id.in_(allegati_ids)).all()
    allegati_paths = [(UPLOAD_FOLDER / a.filename, a.filename) for a in allegati_da_inviare]
    firma_html = """<p>Cordiali Saluti,<br><b>Camar Srl</b></p>"""
    body_html = f"<html><body><p>Buongiorno,</p><p>In allegato i file richiesti.</p><br>{firma_html}</body></html>"
    try:
        send_email_with_attachments(to_addr, subject, body_html, allegati_paths)
        flash(f"Email inviata con successo a {to_addr}", "success")
    except Exception as e:
        logging.error(f"Errore invio email: {e}", exc_info=True)
        flash(f"Errore durante l'invio dell'email: {e}", "danger")
    return redirect(request.referrer or url_for('visualizza_giacenze'))

# --- 7. SETUP E AVVIO APPLICAZIONE ---
def initialize_app():
    with app.app_context():
        db_path = DATA_DIR / "magazzino_web.db"
        if db_path.exists():
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_path = BACKUP_FOLDER / f"magazzino_backup_{timestamp}.db"
            try:
                shutil.copy(db_path, backup_path)
                logging.info(f"Backup del database creato con successo: {backup_path}")
            except Exception as e:
                logging.error(f"Errore durante la creazione del backup: {e}")
        source_dir = Path(__file__).resolve().parent
        for filename in ['mappe_excel.json', 'destinatari_saved.json']:
            source_path = source_dir / filename
            dest_path = CONFIG_FOLDER / filename
            if source_path.exists() and not dest_path.exists():
                try:
                    shutil.copy(source_path, dest_path)
                    logging.info(f"Copiato file di configurazione '{filename}' in {CONFIG_FOLDER}")
                except Exception as e:
                    logging.error(f"Impossibile copiare '{filename}': {e}")
        db.create_all()
        logging.info("Database verificato/creato.")

initialize_app()

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5001))
    app.run(host='0.0.0.0', port=port)
