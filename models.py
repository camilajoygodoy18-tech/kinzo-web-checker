import sqlite3
import datetime
import uuid
from werkzeug.security import generate_password_hash, check_password_hash

DB_PATH = 'instance/kinzo.db'

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    conn.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            api_key TEXT UNIQUE,
            is_admin INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.execute('''
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            filename TEXT,
            status TEXT DEFAULT 'pending',
            total INTEGER DEFAULT 0,
            success INTEGER DEFAULT 0,
            failed INTEGER DEFAULT 0,
            invalid INTEGER DEFAULT 0,
            errors INTEGER DEFAULT 0,
            start_time TIMESTAMP,
            end_time TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
    ''')
    # Create default admin if not exists
    admin = conn.execute('SELECT * FROM users WHERE username = "admin"').fetchone()
    if not admin:
        hashed = generate_password_hash('admin123')
        api_key = str(uuid.uuid4())
        conn.execute(
            'INSERT INTO users (username, password_hash, api_key, is_admin) VALUES (?, ?, ?, ?)',
            ('admin', hashed, api_key, 1)
        )
    conn.commit()
    conn.close()