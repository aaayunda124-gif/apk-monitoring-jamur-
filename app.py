from flask import Flask, request, jsonify, render_template, send_file, g, session, redirect, url_for
import psycopg2
from psycopg2.extras import RealDictCursor
import pandas as pd
from datetime import datetime
import io
import os
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash

# ReportLab untuk Pembuatan File PDF Laporan Resmi
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors

app = Flask(__name__)

# Key Rahasia untuk Enkripsi Session Login
app.secret_key = os.environ.get('SECRET_KEY', 'secret_key_sim_jamur_girinata_2026')

# String Koneksi PostgreSQL Supabase (Setel di Environment Variable atau Isikan Langsung URI Supabase Kamu)
# Contoh format URI Supabase: postgresql://postgres.xxxx:PASSWORD@aws-0-ap-southeast-1.pooler.supabase.com:6543/postgres
DATABASE_URL = os.environ.get('DATABASE_URL', 'postgresql://postgres:PASSWORD_SUPABASE_KAMU@db.PROJECT_REF_KAMU.supabase.co:5432/postgres')

def get_db_connection():
    return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)

# ==========================================
# MIDDLEWARE & DECORATOR PEMBATAS AKSES
# ==========================================
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'id_user' not in session:
            return redirect(url_for('route_login'))
        return f(*args, **kwargs)
    return decorated_function

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if session.get('peran') != 'admin':
            return "<script>alert('Akses ditolak! Halaman ini khusus Admin/Perangkat Desa.'); window.location.href='/';</script>"
        return f(*args, **kwargs)
    return decorated_function

# ==========================================
# 1. ROUTE AUTENTIKASI (LOGIN & LOGOUT)
# ==========================================
@app.route('/login')
def route_login():
    if 'id_user' in session:
        return redirect(url_for('route_dashboard'))
    return render_template('login.html')

@app.route('/api/login', methods=['POST'])
def api_login():
    conn = None
    cursor = None
    try:
        username = request.form.get('username')
        password = request.form.get('password')

        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("SELECT * FROM users WHERE username = %s", (username,))
        user = cursor.fetchone()

        if user:
            # Verifikasi password
            is_valid_pw = False
            if user['password'].startswith('pbkdf2:sha256:') or user['password'].startswith('scrypt:'):
                is_valid_pw = check_password_hash(user['password'], password)
            else:
                is_valid_pw = (user['password'] == password)

            if is_valid_pw:
                # DUDUKKAN SESSION SECARA TEGAS
                session.clear()
                session['id_user'] = user['id_user']
                session['nama'] = user['nama']
                session['username'] = user['username']
                session['peran'] = user['peran']
                return jsonify({"status": "success", "message": f"Selamat datang, {user['nama']}!"})

        return jsonify({"status": "error", "message": "Username atau password salah!"}), 401

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        if cursor: cursor.close()
        if conn: conn.close()

# ROUTE LOGOUT
@app.route('/logout')
def route_logout():
    session.clear() # Menghapus seluruh session login
    return redirect(url_for('route_login'))

# ==========================================
# 2. ROUTE TAMPILAN UTAMA (FRONTEND ROUTER)
# ==========================================
@app.route('/')
@login_required
def route_dashboard():
    return render_template('dashboard.html', user=session)

@app.route('/input-panen')
@login_required
def route_input_panen():
    return render_template('index.html', user=session)

@app.route('/input-penjualan')
@login_required
def route_input_penjualan():
    return render_template('penjualan.html', user=session)

# ==========================================
# 3. ENDPOINT PROSES INPUT PANEN, EDIT & HAPUS
# ==========================================
@app.route('/api/process-panen', methods=['POST'])
@login_required
def process_panen():
    conn = None
    cursor = None
    try:
        id_user = session['id_user']
        tanggal_panen = request.form.get('tanggal_panen')
        berat_kg = float(request.form.get('berat_kg', 0))
        kualitas_grade = request.form.get('kualitas_grade')
        jumlah_baglog_rusak = int(request.form.get('jumlah_baglog_rusak', 0))

        conn = get_db_connection()
        cursor = conn.cursor()

        # Insert ke Tabel Hasil Panen
        query_panen = """
            INSERT INTO hasil_panen (id_user, tanggal_panen, berat_kg, kualitas_grade) 
            VALUES (%s, %s, %s, %s)
        """
        cursor.execute(query_panen, (id_user, tanggal_panen, berat_kg, kualitas_grade))

        # Insert ke Tabel Sirkulasi Baglog jika ada baglog rusak
        if jumlah_baglog_rusak > 0:
            keterangan = "Pengurangan baglog rusak/afkir saat panen harian"
            query_baglog = """
                INSERT INTO sirkulasi_baglog (id_user, jumlah_baglog_produktif, jumlah_baglog_rusak, tanggal_masuk, keterangan) 
                VALUES (%s, 0, %s, %s, %s)
            """
            cursor.execute(query_baglog, (id_user, jumlah_baglog_rusak, tanggal_panen, keterangan))

        conn.commit()
        return jsonify({"status": "success", "message": "Data panen harian berhasil disimpan!"})

    except Exception as e:
        if conn: conn.rollback()
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        if cursor: cursor.close()
        if conn: conn.close()

@app.route('/api/panen/<int:id_panen>', methods=['GET'])
@login_required
def get_panen_by_id(id_panen):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM hasil_panen WHERE id_panen = %s", (id_panen,))
    data = cursor.fetchone()
    
    if data:
        data['tanggal_panen'] = str(data['tanggal_panen'])
        cursor.execute("SELECT SUM(jumlah_baglog_rusak) as baglog_rusak FROM sirkulasi_baglog WHERE tanggal_masuk::date = %s::date", (data['tanggal_panen'],))
        row_baglog = cursor.fetchone()
        data['jumlah_baglog_rusak'] = int(row_baglog['baglog_rusak'] or 0) if row_baglog else 0
        
        cursor.close()
        conn.close()
        return jsonify({"status": "success", "data": data})
        
    cursor.close()
    conn.close()
    return jsonify({"status": "error", "message": "Data tidak ditemukan"}), 404

@app.route('/api/update-panen', methods=['POST'])
@login_required
def update_panen():
    conn = None
    cursor = None
    try:
        id_panen = int(request.form.get('id_panen'))
        tanggal_panen = request.form.get('tanggal_panen')
        berat_kg = float(request.form.get('berat_kg', 0))
        kualitas_grade = request.form.get('kualitas_grade')
        jumlah_baglog_rusak = int(request.form.get('jumlah_baglog_rusak', 0))

        conn = get_db_connection()
        cursor = conn.cursor()

        query_update_panen = """
            UPDATE hasil_panen 
            SET tanggal_panen = %s, berat_kg = %s, kualitas_grade = %s 
            WHERE id_panen = %s
        """
        cursor.execute(query_update_panen, (tanggal_panen, berat_kg, kualitas_grade, id_panen))

        cursor.execute("SELECT id_baglog FROM sirkulasi_baglog WHERE tanggal_masuk::date = %s::date", (tanggal_panen,))
        row_sirkulasi = cursor.fetchone()

        if row_sirkulasi:
            query_update_baglog = "UPDATE sirkulasi_baglog SET jumlah_baglog_rusak = %s WHERE id_baglog = %s"
            cursor.execute(query_update_baglog, (jumlah_baglog_rusak, row_sirkulasi['id_baglog']))
        else:
            if jumlah_baglog_rusak > 0:
                query_insert_baglog = """
                    INSERT INTO sirkulasi_baglog (id_user, jumlah_baglog_produktif, jumlah_baglog_rusak, tanggal_masuk, keterangan) 
                    VALUES (%s, 0, %s, %s, 'Pengurangan baglog rusak/afkir saat panen')
                """
                cursor.execute(query_insert_baglog, (session['id_user'], jumlah_baglog_rusak, tanggal_panen))

        conn.commit()
        return jsonify({"status": "success", "message": "Data hasil panen & sirkulasi baglog berhasil diperbarui!"})

    except Exception as e:
        if conn: conn.rollback()
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        if cursor: cursor.close()
        if conn: conn.close()

@app.route('/api/delete-panen/<int:id_panen>', methods=['POST'])
@login_required
def delete_panen(id_panen):
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM hasil_panen WHERE id_panen = %s", (id_panen,))
        conn.commit()
        return jsonify({"status": "success", "message": "Data panen berhasil dihapus"})
    except Exception as e:
        if conn: conn.rollback()
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        if cursor: cursor.close()
        if conn: conn.close()

# ==========================================
# 4. ENDPOINT PENJUALAN
# ==========================================
@app.route('/api/process-penjualan', methods=['POST'])
@login_required
def process_penjualan():
    conn = None
    cursor = None
    try:
        id_user = session['id_user']
        tanggal_jual = request.form.get('tanggal_jual')
        volume_kg = float(request.form.get('volume_kg', 0))
        harga_per_kg = float(request.form.get('harga_per_kg', 0))
        pembeli_tengkulak = request.form.get('pembeli_tengkulak')

        conn = get_db_connection()
        cursor = conn.cursor()

        query_penjualan = """
            INSERT INTO penjualan (id_user, tanggal_jual, volume_kg, harga_per_kg, pembeli_tengkulak) 
            VALUES (%s, %s, %s, %s, %s)
        """
        cursor.execute(query_penjualan, (id_user, tanggal_jual, volume_kg, harga_per_kg, pembeli_tengkulak))
        conn.commit()
        return "<script>alert('Transaksi penjualan berhasil dicatat!'); window.location.href='/input-penjualan';</script>"

    except Exception as e:
        if conn: conn.rollback()
        return f"<script>alert('Gagal menyimpan transaksi: {str(e)}'); window.location.href='/input-penjualan';</script>"
    finally:
        if cursor: cursor.close()
        if conn: conn.close()

@app.route('/api/penjualan/<int:id_penjualan>', methods=['GET'])
@login_required
def get_penjualan_by_id(id_penjualan):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM penjualan WHERE id_penjualan = %s", (id_penjualan,))
    data = cursor.fetchone()
    cursor.close()
    conn.close()
    
    if data:
        data['tanggal_jual'] = str(data['tanggal_jual'])
        data['volume_kg'] = float(data['volume_kg'] or 0)
        data['harga_per_kg'] = float(data['harga_per_kg'] or 0)
        return jsonify({"status": "success", "data": data})
    return jsonify({"status": "error", "message": "Data tidak ditemukan"}), 404

@app.route('/api/update-penjualan', methods=['POST'])
@login_required
def update_penjualan():
    conn = None
    cursor = None
    try:
        id_penjualan = int(request.form.get('id_penjualan'))
        tanggal_jual = request.form.get('tanggal_jual')
        volume_kg = float(request.form.get('volume_kg', 0))
        harga_per_kg = float(request.form.get('harga_per_kg', 0))
        pembeli_tengkulak = request.form.get('pembeli_tengkulak')

        conn = get_db_connection()
        cursor = conn.cursor()

        query_update = """
            UPDATE penjualan 
            SET tanggal_jual = %s, volume_kg = %s, harga_per_kg = %s, pembeli_tengkulak = %s 
            WHERE id_penjualan = %s
        """
        cursor.execute(query_update, (tanggal_jual, volume_kg, harga_per_kg, pembeli_tengkulak, id_penjualan))
        conn.commit()

        return "<script>alert('Data penjualan berhasil diperbarui!'); window.location.href='/input-penjualan';</script>"

    except Exception as e:
        if conn: conn.rollback()
        return f"<script>alert('Gagal memperbarui data: {str(e)}'); window.location.href='/input-penjualan';</script>"
    finally:
        if cursor: cursor.close()
        if conn: conn.close()

@app.route('/api/delete-penjualan/<int:id_penjualan>', methods=['POST'])
@login_required
def delete_penjualan(id_penjualan):
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM penjualan WHERE id_penjualan = %s", (id_penjualan,))
        conn.commit()
        return jsonify({"status": "success", "message": "Data penjualan berhasil dihapus"})
    except Exception as e:
        if conn: conn.rollback()
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        if cursor: cursor.close()
        if conn: conn.close()

@app.route('/api/rekapitulasi/penjualan-semua', methods=['GET'])
@login_required
def get_semua_penjualan():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    query = """
        SELECT id_penjualan, tanggal_jual, volume_kg, harga_per_kg, (volume_kg * harga_per_kg) as total_pendapatan, pembeli_tengkulak 
        FROM penjualan 
        ORDER BY tanggal_jual DESC, id_penjualan DESC 
        LIMIT 50
    """
    cursor.execute(query)
    data = cursor.fetchall()
    
    for item in data:
        item['tanggal_jual'] = str(item['tanggal_jual'])
        item['volume_kg'] = float(item['volume_kg'] or 0)
        item['harga_per_kg'] = float(item['harga_per_kg'] or 0)
        item['total_pendapatan'] = float(item['total_pendapatan'] or 0)
        
    cursor.close()
    conn.close()
    return jsonify({"status": "success", "data": data})

# ==========================================
# 5. ENDPOINT DASHBOARD MONITORING
# ==========================================
@app.route('/api/dashboard-data', methods=['GET'])
@login_required
def get_dashboard_data():
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT SUM(jumlah_baglog_produktif) as produktif, SUM(jumlah_baglog_rusak) as rusak FROM sirkulasi_baglog")
    baglog_stat = cursor.fetchone()
    
    baglog_produktif = int(baglog_stat['produktif'] or 0) if baglog_stat else 0
    baglog_rusak = int(baglog_stat['rusak'] or 0) if baglog_stat else 0

    today_str = datetime.now().strftime('%Y-%m-%d')
    cursor.execute("SELECT SUM(berat_kg) as total FROM hasil_panen WHERE tanggal_panen = %s", (today_str,))
    panen_today_res = cursor.fetchone()
    panen_today = panen_today_res['total'] if panen_today_res and panen_today_res['total'] is not None else 0

    current_month = datetime.now().month
    current_year = datetime.now().year
    cursor.execute("SELECT SUM(berat_kg) as total FROM hasil_panen WHERE EXTRACT(MONTH FROM tanggal_panen) = %s AND EXTRACT(YEAR FROM tanggal_panen) = %s", (current_month, current_year))
    panen_month_res = cursor.fetchone()
    panen_month = panen_month_res['total'] if panen_month_res and panen_month_res['total'] is not None else 0

    cursor.execute("""
        SELECT TO_CHAR(tanggal_panen, 'DD Mon') as label, SUM(berat_kg) as total 
        FROM hasil_panen 
        GROUP BY tanggal_panen 
        ORDER BY tanggal_panen DESC LIMIT 7
    """)
    chart_rows = cursor.fetchall()

    if chart_rows:
        labels = [r['label'] for r in reversed(chart_rows)]
        data_values = [float(r['total']) for r in reversed(chart_rows)]
    else:
        labels = ["Belum Ada Data"]
        data_values = [0]

    cursor.close()
    conn.close()

    return jsonify({
        "status": "success",
        "kpi": {
            "baglog_produktif": baglog_produktif,
            "baglog_rusak": baglog_rusak,
            "panen_hari_ini": float(panen_today),
            "total_panen_bulan_ini": float(panen_month)
        },
        "panen_harian": {
            "labels": labels,
            "data": data_values
        }
    })

# ==========================================
# 6. FUNGSI & ENDPOINT REKAPITULASI LAPORAN
# ==========================================
def hitung_rekap_bulanan(bulan, tahun):
    conn = get_db_connection()
    cursor = conn.cursor()

    query_panen = """
        SELECT id_panen, tanggal_panen, berat_kg, kualitas_grade 
        FROM hasil_panen 
        WHERE EXTRACT(MONTH FROM tanggal_panen) = %s AND EXTRACT(YEAR FROM tanggal_panen) = %s
        ORDER BY tanggal_panen ASC
    """
    cursor.execute(query_panen, (bulan, tahun))
    data_panen = cursor.fetchall()
    
    for p in data_panen:
        p['tanggal_panen'] = str(p['tanggal_panen'])
        p['berat_kg'] = float(p['berat_kg'] or 0)

    query_penjualan = """
        SELECT id_penjualan, tanggal_jual, volume_kg, harga_per_kg, (volume_kg * harga_per_kg) AS total_pendapatan, pembeli_tengkulak 
        FROM penjualan 
        WHERE EXTRACT(MONTH FROM tanggal_jual) = %s AND EXTRACT(YEAR FROM tanggal_jual) = %s
        ORDER BY tanggal_jual ASC
    """
    cursor.execute(query_penjualan, (bulan, tahun))
    data_penjualan = cursor.fetchall()
    
    for j in data_penjualan:
        j['tanggal_jual'] = str(j['tanggal_jual'])
        j['volume_kg'] = float(j['volume_kg'] or 0)
        j['harga_per_kg'] = float(j['harga_per_kg'] or 0)
        j['total_pendapatan'] = float(j['total_pendapatan'] or 0)

    cursor.close()
    conn.close()

    total_volume_panen = sum(item['berat_kg'] for item in data_panen) if data_panen else 0.0
    hari_panen_unik = len(set(item['tanggal_panen'] for item in data_panen)) if data_panen else 0
    rerata_panen_harian = (total_volume_panen / hari_panen_unik) if hari_panen_unik > 0 else 0.0

    total_pendapatan = sum(item['total_pendapatan'] for item in data_penjualan) if data_penjualan else 0.0
    total_volume_terjual = sum(item['volume_kg'] for item in data_penjualan) if data_penjualan else 0.0

    return {
        "periode": f"{bulan:02d}-{tahun}",
        "ringkasan": {
            "total_volume_panen_kg": round(total_volume_panen, 2),
            "hari_aktif_panen": hari_panen_unik,
            "rerata_panen_harian_kg": round(rerata_panen_harian, 2),
            "total_volume_terjual_kg": round(total_volume_terjual, 2),
            "total_pendapatan_rp": round(total_pendapatan, 2)
        },
        "detail_panen": data_panen,
        "detail_penjualan": data_penjualan
    }

@app.route('/api/rekapitulasi', methods=['GET'])
@login_required
def get_rekapitulasi_json():
    bulan = int(request.args.get('bulan', datetime.now().month))
    tahun = int(request.args.get('tahun', datetime.now().year))
    rekap = hitung_rekap_bulanan(bulan, tahun)
    return jsonify({"status": "success", "data": rekap})

@app.route('/api/rekapitulasi/ekspor-excel', methods=['GET'])
@login_required
def ekspor_excel():
    bulan = int(request.args.get('bulan', datetime.now().month))
    tahun = int(request.args.get('tahun', datetime.now().year))
    
    rekap = hitung_rekap_bulanan(bulan, tahun)
    output = io.BytesIO()

    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df_summary = pd.DataFrame([rekap['ringkasan']])
        df_summary.to_excel(writer, sheet_name='Ringkasan Executive', index=False)
        
        if rekap['detail_panen']:
            df_panen = pd.DataFrame(rekap['detail_panen'])
            df_panen.to_excel(writer, sheet_name='Hasil Panen Harian', index=False)
            
        if rekap['detail_penjualan']:
            df_penjualan = pd.DataFrame(rekap['detail_penjualan'])
            df_penjualan.to_excel(writer, sheet_name='Sirkulasi Penjualan', index=False)

    output.seek(0)
    filename = f"Laporan_Panen_Jamur_Desa_Girinata_{bulan:02d}_{tahun}.xlsx"
    return send_file(
        output,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True,
        download_name=filename
    )

@app.route('/api/rekapitulasi/ekspor-pdf', methods=['GET'])
@login_required
def ekspor_pdf():
    bulan = int(request.args.get('bulan', datetime.now().month))
    tahun = int(request.args.get('tahun', datetime.now().year))
    
    rekap = hitung_rekap_bulanan(bulan, tahun)
    buffer = io.BytesIO()

    doc = SimpleDocTemplate(buffer, pagesize=letter, rightMargin=30, leftMargin=30, topMargin=30, bottomMargin=30)
    elements = []
    
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle('TitleStyle', parent=styles['Heading1'], fontName='Helvetica-Bold', fontSize=14, alignment=1, spaceAfter=4)
    subtitle_style = ParagraphStyle('SubTitleStyle', parent=styles['Normal'], fontName='Helvetica', fontSize=10, alignment=1, spaceAfter=15)
    section_style = ParagraphStyle('SectionStyle', parent=styles['Heading2'], fontName='Helvetica-Bold', fontSize=11, spaceBefore=10, spaceAfter=6)

    elements.append(Paragraph("PEMERINTAH DESA GIRINATA", title_style))
    elements.append(Paragraph(f"LAPORAN REKAPITULASI PRODUKTIVITAS BUDIDAYA JAMUR - PERIODE {bulan:02d}/{tahun}", subtitle_style))
    elements.append(Spacer(1, 10))

    ringkasan_data = [
        ["Indikator Kinerja Operasional", "Nilai / Capaian"],
        ["Total Volume Hasil Panen", f"{rekap['ringkasan']['total_volume_panen_kg']} Kg"],
        ["Jumlah Hari Aktif Panen", f"{rekap['ringkasan']['hari_aktif_panen']} Hari"],
        ["Rerata Hasil Panen Harian", f"{rekap['ringkasan']['rerata_panen_harian_kg']} Kg / Hari"],
        ["Total Volume Terjual", f"{rekap['ringkasan']['total_volume_terjual_kg']} Kg"],
        ["Total Estimasi Pendapatan", f"Rp {rekap['ringkasan']['total_pendapatan_rp']:,.2f}"]
    ]
    
    table_ringkasan = Table(ringkasan_data, colWidths=[250, 250])
    table_ringkasan.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (1, 0), colors.HexColor('#198754')),
        ('TEXTCOLOR', (0, 0), (1, 0), colors.whitesmoke),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
    ]))
    
    elements.append(Paragraph("1. Ringkasan Eksekutif", section_style))
    elements.append(table_ringkasan)
    elements.append(Spacer(1, 15))

    elements.append(Paragraph("2. Rincian Sirkulasi Penjualan & Transaksi", section_style))
    penjualan_table_data = [["Tanggal Jual", "Volume (Kg)", "Harga/Kg (Rp)", "Total Transaksi (Rp)", "Pembeli/Tengkulak"]]
    
    for item in rekap['detail_penjualan']:
        penjualan_table_data.append([
            str(item['tanggal_jual']),
            f"{item['volume_kg']} Kg",
            f"Rp {item['harga_per_kg']:,.0f}",
            f"Rp {item['total_pendapatan']:,.0f}",
            item['pembeli_tengkulak']
        ])
        
    if len(penjualan_table_data) == 1:
        penjualan_table_data.append(["-", "-", "-", "-", "Belum ada transaksi"])

    table_penjualan = Table(penjualan_table_data, colWidths=[80, 80, 100, 120, 120])
    table_penjualan.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#41464b')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.lightgrey),
        ('FONTSIZE', (0, 0), (-1, -1), 9)
    ]))
    
    elements.append(table_penjualan)

    doc.build(elements)
    buffer.seek(0)
    filename = f"Laporan_Resmi_Jamur_Desa_Girinata_{bulan:02d}_{tahun}.pdf"
    return send_file(buffer, mimetype='application/pdf', as_attachment=True, download_name=filename)

if __name__ == '__main__':
    app.run(debug=True, port=5000)