import sys
import os
import json
import imaplib
import email
import subprocess
from email.policy import default
from cryptography.fernet import Fernet

from PyQt6 import QtWidgets, uic, QtCore, QtGui
from PyQt6.QtWidgets import QApplication, QListWidgetItem, QMessageBox
from PyQt6.QtCore import Qt, QTimer, QPropertyAnimation, QEasingCurve


# --- KLASA SZYFROWANIA ---
class SafeStorage:
    def __init__(self, filename="Duck_vault.json", key_file=".duck.key"):
        self.base_path = os.path.join(os.path.expanduser("~"), ".duck_mail_data")
        if not os.path.exists(self.base_path):
            os.makedirs(self.base_path)

        self.filename = os.path.join(self.base_path, filename)
        self.key_file = os.path.join(self.base_path, key_file)

        if os.path.exists(self.key_file):
            with open(self.key_file, "rb") as f:
                self.key = f.read()
        else:
            self.key = Fernet.generate_key()
            with open(self.key_file, "wb") as f:
                f.write(self.key)
        self.cipher = Fernet(self.key)

    def save_data(self, data):
        encrypted = self.cipher.encrypt(json.dumps(data).encode('utf-8'))
        with open(self.filename, "wb") as f: f.write(encrypted)

    def load_data(self):
        if not os.path.exists(self.filename): return {}
        try:
            with open(self.filename, "rb") as f:
                decrypted = self.cipher.decrypt(f.read()).decode('utf-8')
                return json.loads(decrypted)
        except:
            return {}


# --- MOTYWY CSS ---
DARK_CSS = """
    QMainWindow { background-color: #1e1e2e; }
    #sideBar { background-color: #181825; border-right: 1px solid #313244; min-width: 200px; }
    QPushButton { background-color: #313244; color: #cdd6f4; border: none; padding: 10px; border-radius: 4px; }
    QPushButton:hover { background-color: #45475a; }
    QLineEdit, QTextEdit, QListWidget, QComboBox { background-color: #313244; border: 1px solid #45475a; color: #cdd6f4; }
    QLabel { color: #cdd6f4; }
"""
LIGHT_CSS = """
    QMainWindow { background-color: #f0f0f0; }
    #sideBar { background-color: #ffffff; border-right: 1px solid #cccccc; min-width: 200px; }
    QPushButton { background-color: #e0e0e0; color: #000000; border: 1px solid #cccccc; padding: 10px; border-radius: 4px; }
    QPushButton:hover { background-color: #d0d0d0; }
    QLineEdit, QTextEdit, QListWidget, QComboBox { background-color: #ffffff; border: 1px solid #cccccc; color: #000000; }
    QLabel { color: #000000; }
"""


# --- GŁÓWNA KLASA ---
class DuckMail(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        # 1. Ładujemy UI
        uic.loadUi('design.ui', self)

        # 2. Dane
        self.storage = SafeStorage()
        self.app_data = self.storage.load_data()
        self.accounts = self.app_data.get("accounts", {})
        self.last_account = self.app_data.get("last_account")
        self.is_dark = self.app_data.get("theme_dark", True)
        self.last_seen_id = None

        # 3. Setup UI
        self.combo_prov.addItems(["Gmail", "WP.pl"])
        self.verticalLayout_side.insertStretch(3)
        self.apply_theme()

        # 4. Connects
        self.btn_theme.clicked.connect(self.toggle_theme)
        self.btn_add_acc.clicked.connect(self.add_account)
        self.btn_sync.clicked.connect(self.sync_emails)
        self.btn_nav_inbox.clicked.connect(lambda: self.stackedWidget.setCurrentIndex(0))
        self.btn_nav_send.clicked.connect(lambda: self.stackedWidget.setCurrentIndex(1))
        self.mail_list.itemClicked.connect(self.display_email)

        # 5. Animacja i Timer
        self.sync_anim = QPropertyAnimation(self.btn_sync, b"windowOpacity")
        self.sync_anim.setDuration(800)
        self.sync_anim.setStartValue(1.0)
        self.sync_anim.setEndValue(0.4)
        self.sync_anim.setLoopCount(-1)

        self.bg_timer = QTimer(self)
        self.bg_timer.setInterval(300000)  # 5 min
        self.bg_timer.timeout.connect(self.sync_emails)

        # 6. Autostart
        if self.last_account:
            self.input_email.setText(self.last_account)
            self.bg_timer.start()
            QTimer.singleShot(1000, self.sync_emails)

    def apply_theme(self):
        self.setStyleSheet(DARK_CSS if self.is_dark else LIGHT_CSS)
        self.btn_theme.setText("☀️ Jasny" if self.is_dark else "🌙 Ciemny")

    def toggle_theme(self):
        self.is_dark = not self.is_dark
        self.apply_theme()
        self.app_data["theme_dark"] = self.is_dark
        self.storage.save_data(self.app_data)

    def add_account(self):
        email_val = self.input_email.text().strip()
        pass_val = self.input_pass.text().strip()
        if email_val and pass_val:
            self.accounts[email_val] = {"p": pass_val, "prov": self.combo_prov.currentText()}
            self.last_account = email_val
            self.app_data.update({"accounts": self.accounts, "last_account": email_val})
            self.storage.save_data(self.app_data)
            QMessageBox.information(self, "Duck Mail", "Konto dodane!")
            self.sync_emails()
            self.bg_timer.start()

    def sync_emails(self):
        if not self.last_account or not self.btn_sync.isEnabled(): return
        self.btn_sync.setEnabled(False)
        self.sync_anim.start()
        QTimer.singleShot(100, self._run_sync)

    def _run_sync(self):
        acc = self.accounts.get(self.last_account)
        if not acc:
            self._end_sync();
            return

        prov_map = {"Gmail": "imap.gmail.com", "WP.pl": "imap.wp.pl"}
        try:
            mail = imaplib.IMAP4_SSL(prov_map[acc['prov']], 993)
            mail.login(self.last_account, acc['p'])
            mail.select("INBOX")
            _, data = mail.search(None, "ALL")
            ids = data[0].split()

            if ids:
                curr_id = ids[-1]
                if self.last_seen_id and curr_id != self.last_seen_id:
                    subprocess.Popen(['notify-send', 'Duck Mail', 'Nowa wiadomość!'])
                self.last_seen_id = curr_id

                self.mail_list.clear()
                for m_id in reversed(ids[-15:]):
                    _, m_data = mail.fetch(m_id, "(RFC822)")
                    msg = email.message_from_bytes(m_data[0][1], policy=default)
                    item = QListWidgetItem(f"📬 {msg['from']}\n{msg['subject']}")
                    item.setData(Qt.ItemDataRole.UserRole, m_data[0][1])
                    self.mail_list.addItem(item)

                # Auto-ładowanie ostatniego maila
                if self.mail_list.count() > 0:
                    self.mail_list.setCurrentRow(0)
                    self.display_email(self.mail_list.item(0))
            mail.logout()
        except Exception as e:
            print(f"Error: {e}")
        finally:
            self._end_sync()

    def _end_sync(self):
        self.sync_anim.stop()
        self.btn_sync.setWindowOpacity(1.0)
        self.btn_sync.setEnabled(True)

    def display_email(self, item):
        raw_data = item.data(Qt.ItemDataRole.UserRole)
        msg = email.message_from_bytes(raw_data, policy=default)
        body = ""
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                body = part.get_payload(decode=True).decode(errors='replace')
                break
        self.mail_view.setHtml(f"<b>Od:</b> {msg['from']}<hr><pre>{body}</pre>")


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    win = DuckMail()
    win.show()
    sys.exit(app.exec())