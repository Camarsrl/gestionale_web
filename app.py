from flask import Flask, render_template, request
import mysql.connector
import os

app = Flask(__name__)

def get_db_connection():
    return mysql.connector.connect(
        host=os.environ.get('MYSQL_HOST'),
        user=os.environ.get('MYSQL_USER'),
        password=os.environ.get('MYSQL_PASSWORD'),
        database=os.environ.get('MYSQL_DATABASE')
    )

@app.route('/')
def index():
    filtro = request.args.get('filtro', '')
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    if filtro:
        cursor.execute("SELECT * FROM magazzino WHERE codice_articolo LIKE %s", ('%' + filtro + '%',))
    else:
        cursor.execute("SELECT * FROM magazzino")
    articoli = cursor.fetchall()
    conn.close()
    return render_template('giacenze.html', articoli=articoli, filtro=filtro)
