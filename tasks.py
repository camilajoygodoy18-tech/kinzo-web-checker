import threading
import time
import os
from models import get_db
from checker import NeteaseChecker
import uuid
import json

# in-memory task status cache (for realtime updates)
task_status = {}

def start_check_task(user_id, account_lines, proxies=None, callback=None):
    task_id = str(uuid.uuid4())
    task_status[task_id] = {'stats': {'success': 0, 'failed': 0, 'invalid': 0, 'errors': 0}, 'status': 'running'}

    def run():
        try:
            # Create task record in DB
            db = get_db()
            cursor = db.cursor()
            cursor.execute(
                'INSERT INTO tasks (user_id, status, start_time) VALUES (?, ?, ?)',
                (user_id, 'running', time.strftime('%Y-%m-%d %H:%M:%S'))
            )
            task_db_id = cursor.lastrowid
            db.commit()
            db.close()

            # Save accounts to temp file
            temp_file = f"tasks/{task_id}.txt"
            os.makedirs('tasks', exist_ok=True)
            with open(temp_file, 'w') as f:
                f.write('\n'.join(account_lines))

            # Run checker
            checker = NeteaseChecker(
                accounts=account_lines,
                proxies=proxies,
                callback=update_stats_callback,
                task_id=task_id
            )
            stats, results = checker.run(workers=10)

            # Save results
            for cat, items in results.items():
                if items:
                    with open(f"tasks/{task_id}_{cat}.txt", 'w') as f:
                        f.write('\n'.join(items))

            # Update DB with final stats
            db = get_db()
            db.execute(
                'UPDATE tasks SET status=?, total=?, success=?, failed=?, invalid=?, errors=?, end_time=? WHERE id=?',
                ('completed', len(account_lines), stats['success'], stats['failed'], stats['invalid'], stats['errors'],
                 time.strftime('%Y-%m-%d %H:%M:%S'), task_db_id)
            )
            db.commit()
            db.close()

            task_status[task_id]['status'] = 'completed'
            task_status[task_id]['stats'] = stats
            if callback:
                callback(task_id, stats)

        except Exception as e:
            task_status[task_id]['status'] = 'error'
            task_status[task_id]['error'] = str(e)

    thread = threading.Thread(target=run)
    thread.daemon = True
    thread.start()
    return task_id

def update_stats_callback(task_id, stats):
    task_status[task_id]['stats'] = stats