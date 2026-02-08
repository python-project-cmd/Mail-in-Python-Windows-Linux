import sys
import os
import json
import imaplib
import smtplib
import email
from email.message import EmailMessage
from email.policy import default
from cryptography.fernet import Fernet
from PyQt6.QtWidgets import (QApplication, QWidget, QVBoxLayout, QLineEdit, 
                             QPushButton, QTextEdit, QLabel, QMessageBox, 
                             QHBoxLayout, QComboBox, QTabWidget, QListWidget, 
                             QListWidgetItem, QSplitter, QFileDialog, QFrame)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QIcon

# --- FUNKCJA OBSŁUGI ŚCIEŻEK (DLA APPIMAGE/EXE) ---
def resource_path(relative_path):
    """ Pomaga odnaleźć plik ikony po spakowaniu do jednego pliku """
    try:
        # PyInstaller tworzy folder tymczasowy _MEIPASS
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

# --- SYSTEM SZYFROWANIA ---
class SafeStorage:
    def __init__(self, filename="beauty_vault.json", key_file=".beauty.key"):
        # Zapisujemy w folderze domowym użytkownika, bo AppImage jest tylko do odczytu
        app_data_dir = os.environ.get('APPDATA') or os.path.expanduser("~")
        self.base_path = os.path.join(app_data_dir, ".mail_app_mamy")
        
        if not os.path.exists(self.base_path):
            os.makedirs(self.base_path)

        self.filename = os.path.join(self.base_path, filename)
        self.key_file = os.path.join(self.base_path, key_file)
        self.key = self._get_key()
        self.cipher = Fernet(self.key)

    def _get_key(self):
        if os.path.exists(self.key_file):
            with open(self.key_file, "rb") as f: return f.read()
        key = Fernet.generate_key()
        with open(self.key_file, "wb") as f: f.write(key)
        return key

    def save_data(self, data):
        with open(self.filename, "wb") as f:
            f.write(self.cipher.encrypt(json.dumps(data).encode('utf-8')))

    def load_data(self):
        if not os.path.exists(self.filename): return {}
        try:
            with open(self.filename, "rb") as f:
                return json.loads(self.cipher.decrypt(f.read()).decode('utf-8'))
        except: return {}

# --- KONFIGURACJA ---
PROVIDERS = {
    "Gmail": {"imap": "imap.gmail.com", "smtp": "smtp.gmail.com", "port": 993},
    "WP.pl": {"imap": "imap.wp.pl", "smtp": "smtp.wp.pl", "port": 993}
}

class BeautyEmailApp(QWidget):
    def __init__(self):
        super().__init__()
        self.storage = SafeStorage()
        self.app_data = self.storage.load_data()
        self.accounts = self.app_data.get("accounts", {})
        self.last_account = self.app_data.get("last_account", None)
        self.is_dark = self.app_data.get("theme_dark", True)
        self.current_attachments = []
        self.send_attachments = []
        
        self.init_ui()
        self.apply_theme()
        
        if self.last_account:
            QTimer.singleShot(500, self.sync_emails)

    def init_ui(self):
        # Ustawienie nazwy okna na "Mail"
        self.setWindowTitle("Mail")
        self.resize(1100, 750)
        
        # --- PODMIANA IKONY ---
        # Używamy Twojej nazwy pliku: "icona.png"
        self.setWindowIcon(QIcon(resource_path("icona.png")))
        
        main_layout = QVBoxLayout(self)

        acc_box = QHBoxLayout()
        self.acc_selector = QComboBox()
        self.acc_selector.setPlaceholderText("Wybierz zapisane konto...")
        self.acc_selector.addItems(self.accounts.keys())
        self.acc_selector.currentIndexChanged.connect(self.load_account_data)
        
        self.theme_btn = QPushButton("🌓")
        self.theme_btn.setFixedWidth(50)
        self.theme_btn.clicked.connect(self.toggle_theme)

        acc_box.addWidget(QLabel("KONTO:"))
        acc_box.addWidget(self.acc_selector)
        acc_box.addWidget(self.theme_btn)
        main_layout.addLayout(acc_box)

        login_layout = QHBoxLayout()
        self.email_in = QLineEdit(); self.email_in.setPlaceholderText("Adres Email")
        self.pass_in = QLineEdit(); self.pass_in.setEchoMode(QLineEdit.EchoMode.Password); self.pass_in.setPlaceholderText("Hasło Aplikacji")
        self.prov_in = QComboBox(); self.prov_in.addItems(PROVIDERS.keys())
        login_layout.addWidget(self.email_in); login_layout.addWidget(self.pass_in); login_layout.addWidget(self.prov_in)
        main_layout.addLayout(login_layout)

        self.tabs = QTabWidget()
        
        # ODEBRANE
        receive_tab = QWidget()
        rec_layout = QVBoxLayout(receive_tab)
        self.sync_btn = QPushButton("🔄 Synchronizuj Pocztę")
        self.sync_btn.clicked.connect(self.sync_emails)
        splitter = QSplitter(Qt.Orientation.Vertical)
        self.mail_list = QListWidget()
        self.mail_list.itemClicked.connect(self.display_email)
        view_panel = QWidget()
        view_vbox = QVBoxLayout(view_panel)
        self.mail_view = QTextEdit(); self.mail_view.setReadOnly(True)
        btn_bar = QHBoxLayout()
        self.down_btn = QPushButton("💾 Pobierz Załączniki"); self.down_btn.hide()
        self.down_btn.clicked.connect(self.download_attachments)
        self.del_btn = QPushButton("🗑 Usuń z Serwera"); self.del_btn.hide()
        self.del_btn.clicked.connect(self.delete_email)
        btn_bar.addWidget(self.down_btn); btn_bar.addWidget(self.del_btn)
        view_vbox.addWidget(self.mail_view); view_vbox.addLayout(btn_bar)
        splitter.addWidget(self.mail_list); splitter.addWidget(view_panel)
        rec_layout.addWidget(self.sync_btn); rec_layout.addWidget(splitter)
        
        # WYŚLIJ
        send_tab = QWidget()
        send_layout = QVBoxLayout(send_tab)
        self.to_in = QLineEdit(); self.to_in.setPlaceholderText("Do:")
        self.subj_in = QLineEdit(); self.subj_in.setPlaceholderText("Temat:")
        self.body_in = QTextEdit(); self.body_in.setPlaceholderText("Treść wiadomości...")
        self.attach_btn = QPushButton("📎 Dodaj Załącznik")
        self.attach_btn.clicked.connect(self.add_send_attachment)
        self.attach_label = QLabel("Brak załączników")
        self.send_btn = QPushButton("Wyślij Wiadomość")
        self.send_btn.clicked.connect(self.send_email)
        send_layout.addWidget(self.to_in); send_layout.addWidget(self.subj_in)
        send_layout.addWidget(self.body_in); send_layout.addWidget(self.attach_btn)
        send_layout.addWidget(self.attach_label); send_layout.addWidget(self.send_btn)

        self.tabs.addTab(receive_tab, "Odebrane")
        self.tabs.addTab(send_tab, "Wyślij")
        main_layout.addWidget(self.tabs)

    def apply_theme(self):
        if self.is_dark:
            self.setStyleSheet("""
                QWidget { background-color: #1e1e2e; color: #cdd6f4; font-family: 'Segoe UI'; }
                QLineEdit, QTextEdit, QListWidget, QComboBox { background-color: #313244; border: 1px solid #45475a; border-radius: 8px; color: #cdd6f4; padding: 8px; }
                QPushButton { background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #cba6f7, stop:1 #f5c2e7); color: #11111b; border-radius: 10px; padding: 10px; font-weight: bold; }
                QTabWidget::pane { border: 1px solid #45475a; }
                QTabBar::tab:selected { background: #cba6f7; color: #11111b; }
            """)
        else:
            self.setStyleSheet("""
                QWidget { background-color: #f0f0f0; color: #2e3440; font-family: 'Segoe UI'; }
                QLineEdit, QTextEdit, QListWidget, QComboBox { background-color: #ffffff; border: 1px solid #d8dee9; border-radius: 8px; color: #2e3440; padding: 8px; }
                QPushButton { background: #5e81ac; color: #ffffff; border-radius: 10px; padding: 10px; font-weight: bold; }
                QTabBar::tab:selected { background: #5e81ac; color: #ffffff; }
            """)
        self.storage.save_data({"accounts": self.accounts, "last_account": self.last_account, "theme_dark": self.is_dark})

    def toggle_theme(self):
        self.is_dark = not self.is_dark
        self.apply_theme()

    def load_account_data(self):
        addr = self.acc_selector.currentText()
        if addr in self.accounts:
            self.email_in.setText(addr); self.pass_in.setText(self.accounts[addr]['p'])
            self.prov_in.setCurrentText(self.accounts[addr]['prov'])

    def sync_emails(self):
        addr, pwd = self.email_in.text(), self.pass_in.text()
        if not addr or not pwd: return
        self.accounts[addr] = {'p': pwd, 'prov': self.prov_in.currentText()}
        self.last_account = addr
        self.apply_theme()
        try:
            prov = PROVIDERS[self.prov_in.currentText()]
            mail = imaplib.IMAP4_SSL(prov['imap'], 993)
            mail.login(addr, pwd)
            mail.select("INBOX")
            _, data = mail.search(None, "ALL")
            ids = data[0].split()
            self.mail_list.clear()
            for m_id in reversed(ids[-15:]):
                _, m_data = mail.fetch(m_id, "(RFC822)")
                msg = email.message_from_bytes(m_data[0][1], policy=default)
                item = QListWidgetItem(f"Od: {msg['from']}\nTemat: {msg['subject']}")
                item.setData(Qt.ItemDataRole.UserRole, {'id': m_id, 'raw': m_data[0][1]})
                self.mail_list.addItem(item)
            mail.logout()
        except Exception as e: QMessageBox.critical(self, "Błąd", str(e))

    def display_email(self, item):
        data = item.data(Qt.ItemDataRole.UserRole)
        self.current_msg_id = data['id']
        msg = email.message_from_bytes(data['raw'], policy=default)
        self.current_attachments = []
        body = ""
        for part in msg.walk():
            if part.get_content_maintype() == 'multipart': continue
            filename = part.get_filename()
            if filename: self.current_attachments.append({'name': filename, 'content': part.get_payload(decode=True)})
            elif part.get_content_type() == "text/plain": 
                try: body = part.get_payload(decode=True).decode(errors='replace')
                except: body = "[Błąd dekodowania]"
        self.mail_view.setText(f"Od: {msg['from']}\nData: {msg['date']}\n\n{body}")
        self.down_btn.setVisible(len(self.current_attachments) > 0)
        self.del_btn.show()

    def download_attachments(self):
        folder = QFileDialog.getExistingDirectory(self, "Zapisz w...")
        if folder:
            for a in self.current_attachments:
                with open(os.path.join(folder, a['name']), 'wb') as f: f.write(a['content'])
            QMessageBox.information(self, "OK", "Zapisano!")

    def delete_email(self):
        if QMessageBox.question(self, "Usuń", "Na pewno?") == QMessageBox.StandardButton.Yes:
            try:
                prov = PROVIDERS[self.prov_in.currentText()]
                mail = imaplib.IMAP4_SSL(prov['imap'], 993)
                mail.login(self.email_in.text(), self.pass_in.text())
                mail.select("INBOX")
                mail.store(self.current_msg_id, '+FLAGS', '\\Deleted')
                mail.expunge(); mail.logout()
                self.mail_view.clear(); self.sync_emails()
            except Exception as e: QMessageBox.critical(self, "Błąd", str(e))

    def add_send_attachment(self):
        files, _ = QFileDialog.getOpenFileNames(self, "Wybierz załączniki")
        if files:
            self.send_attachments.extend(files)
            self.attach_label.setText(f"Załączono: {len(self.send_attachments)} plików")

    def send_email(self):
        addr, pwd = self.email_in.text(), self.pass_in.text()
        prov = PROVIDERS[self.prov_in.currentText()]
        try:
            msg = EmailMessage()
            msg['Subject'], msg['From'], msg['To'] = self.subj_in.text(), addr, self.to_in.text()
            msg.set_content(self.body_in.toPlainText())
            for path in self.send_attachments:
                with open(path, 'rb') as f: msg.add_attachment(f.read(), maintype='application', subtype='octet-stream', filename=os.path.basename(path))
            with smtplib.SMTP_SSL(prov['smtp'], 465) as s:
                s.login(addr, pwd); s.send_message(msg)
            QMessageBox.information(self, "Sukces", "Wysłano!")
            self.send_attachments = []; self.attach_label.setText("Brak plików")
        except Exception as e: QMessageBox.critical(self, "Błąd", str(e))

if __name__ == "__main__":
    app = QApplication(sys.argv)
    # Nazwa aplikacji w systemie
    app.setApplicationName("Mail")
    win = BeautyEmailApp()
    win.show()
    sys.exit(app.exec())