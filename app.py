from flask import Flask, render_template, request, redirect, url_for, session, jsonify, Response, send_file
from werkzeug.security import generate_password_hash, check_password_hash
import uuid
import os
import json
import time
from models import get_db, init_db
from tasks import start_check_task, task_status
import threading
import random

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-production')
app.config['UPLOAD_FOLDER'] = 'uploads'
os.makedirs('uploads', exist_ok=True)
os.makedirs('tasks', exist_ok=True)

# Initialize DB
init_db()

# ------------------- Authentication -------------------
def login_required(f):
    def wrapper(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    wrapper.__name__ = f.__name__
    return wrapper

def admin_required(f):
    def wrapper(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        db = get_db()
        user = db.execute('SELECT * FROM users WHERE id = ?', (session['user_id'],)).fetchone()
        if not user or not user['is_admin']:
            return "Admin access required", 403
        return f(*args, **kwargs)
    wrapper.__name__ = f.__name__
    return wrapper

@app.route('/')
def index():
    if 'user_id' in session:
        return redirect(url_for('checker'))
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        db = get_db()
        user = db.execute('SELECT * FROM users WHERE username = ?', (username,)).fetchone()
        if user and check_password_hash(user['password_hash'], password):
            session['user_id'] = user['id']
            session['username'] = user['username']
            session['is_admin'] = bool(user['is_admin'])
            return redirect(url_for('checker'))
        else:
            return render_template('login.html', error='Invalid credentials')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        db = get_db()
        existing = db.execute('SELECT * FROM users WHERE username = ?', (username,)).fetchone()
        if existing:
            return render_template('login.html', error='Username already exists')
        hashed = generate_password_hash(password)
        api_key = str(uuid.uuid4())
        db.execute(
            'INSERT INTO users (username, password_hash, api_key) VALUES (?, ?, ?)',
            (username, hashed, api_key)
        )
        db.commit()
        return redirect(url_for('login'))
    return render_template('login.html')

# ------------------- Admin -------------------
@app.route('/admin')
@admin_required
def admin_panel():
    db = get_db()
    users = db.execute('SELECT id, username, api_key, is_admin, created_at FROM users').fetchall()
    return render_template('admin.html', users=users)

@app.route('/admin/generate_api/<int:user_id>', methods=['POST'])
@admin_required
def generate_api(user_id):
    new_key = str(uuid.uuid4())
    db = get_db()
    db.execute('UPDATE users SET api_key = ? WHERE id = ?', (new_key, user_id))
    db.commit()
    return redirect(url_for('admin_panel'))

@app.route('/admin/delete_user/<int:user_id>', methods=['POST'])
@admin_required
def delete_user(user_id):
    if user_id == session['user_id']:
        return "Cannot delete yourself", 400
    db = get_db()
    db.execute('DELETE FROM users WHERE id = ?', (user_id,))
    db.commit()
    return redirect(url_for('admin_panel'))

# ------------------- Checker UI -------------------
@app.route('/checker')
@login_required
def checker():
    return render_template('checker.html', username=session['username'])

@app.route('/api/start_check', methods=['POST'])
@login_required
def start_check():
    # Get accounts from file or textarea
    if 'file' in request.files:
        f = request.files['file']
        lines = f.read().decode('utf-8').splitlines()
    else:
        text = request.form.get('accounts', '')
        lines = [l.strip() for l in text.splitlines() if l.strip()]

    if not lines:
        return jsonify({'error': 'No accounts provided'}), 400

    # Optionally get proxies file
    proxies = []
    if 'proxy_file' in request.files:
        pf = request.files['proxy_file']
        proxies = [p.strip() for p in pf.read().decode('utf-8').splitlines() if p.strip()]

    # Start background task
    user_id = session['user_id']
    task_id = start_check_task(user_id, lines, proxies)

    return jsonify({'task_id': task_id, 'total': len(lines)})

@app.route('/api/task_status/<task_id>')
@login_required
def get_task_status(task_id):
    status = task_status.get(task_id)
    if not status:
        return jsonify({'error': 'Task not found'}), 404
    return jsonify(status)

# SSE stream for realtime updates
@app.route('/api/stream/<task_id>')
@login_required
def stream_task(task_id):
    def generate():
        last_stats = None
        while True:
            status = task_status.get(task_id)
            if not status:
                break
            stats = status.get('stats', {})
            if stats != last_stats:
                last_stats = stats.copy()
                yield f"data: {json.dumps(stats)}\n\n"
            if status.get('status') in ('completed', 'error'):
                break
            time.sleep(1)
    return Response(generate(), mimetype='text/event-stream')

@app.route('/api/download/<task_id>/<result_type>')
@login_required
def download_result(task_id, result_type):
    # result_type: success, failed, invalid, errors
    filepath = f"tasks/{task_id}_{result_type}.txt"
    if os.path.exists(filepath):
        return send_file(filepath, as_attachment=True)
    return "No results", 404

@app.route('/api/me')
@login_required
def me():
    db = get_db()
    user = db.execute('SELECT id, username, api_key, is_admin FROM users WHERE id = ?', (session['user_id'],)).fetchone()
    return jsonify(dict(user))

# ------------------- API Key Authentication (for future API endpoints) -------------------
def api_key_required(f):
    def wrapper(*args, **kwargs):
        key = request.headers.get('X-API-Key')
        if not key:
            return jsonify({'error': 'API key required'}), 401
        db = get_db()
        user = db.execute('SELECT * FROM users WHERE api_key = ?', (key,)).fetchone()
        if not user:
            return jsonify({'error': 'Invalid API key'}), 401
        # Attach user to request
        request.user = user
        return f(*args, **kwargs)
    wrapper.__name__ = f.__name__
    return wrapper

# Example API endpoint: start check via API
@app.route('/api/v1/check', methods=['POST'])
@api_key_required
def api_check():
    data = request.json
    accounts = data.get('accounts', [])
    if not accounts:
        return jsonify({'error': 'No accounts'}), 400
    # start task and return task_id
    user_id = request.user['id']
    task_id = start_check_task(user_id, accounts)
    return jsonify({'task_id': task_id})

# ------------------- Run -------------------
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)