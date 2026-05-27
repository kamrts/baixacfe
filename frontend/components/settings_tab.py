# frontend/components/settings_tab.py
import logging
import ctypes
from ctypes import wintypes
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QFrame, 
                               QLabel, QLineEdit, QPushButton, QComboBox, 
                               QSpinBox, QDoubleSpinBox, QFormLayout)
from PySide6.QtCore import Signal

logger = logging.getLogger("SAT_Downloader")

# Constantes de DLL de Criptografia do Windows (CryptoAPI)
HCERTSTORE = wintypes.HANDLE
PCCERT_CONTEXT = ctypes.c_void_p
X509_ASN_ENCODING = 0x00000001
PKCS_7_ASN_ENCODING = 0x00010000
CERT_FIND_ANY = 0

class SettingsTab(QWidget):
    """
    Interface para parametrização técnica do robô.
    Lida com o banco SQL Server, Certificados instalados, proxy, delays e modo headless.
    """
    
    save_requested = Signal(dict)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.init_ui()
        
    def list_windows_certificates(self) -> list:
        """
        Consulta a API de criptografia nativa do Windows (crypt32.dll)
        para obter os nomes dos certificados digitais de cliente (e-CNPJ/e-CPF)
        instalados no repositório Pessoal (MY) do usuário ativo.
        """
        cert_names = []
        try:
            crypt32 = ctypes.windll.crypt32

            # Definir tipos explicitamente — OBRIGATÓRIO para evitar access violation no Windows 64-bit
            crypt32.CertOpenSystemStoreW.restype = ctypes.c_void_p
            crypt32.CertOpenSystemStoreW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p]

            crypt32.CertFindCertificateInStore.restype = ctypes.c_void_p
            crypt32.CertFindCertificateInStore.argtypes = [
                ctypes.c_void_p, ctypes.c_ulong, ctypes.c_ulong,
                ctypes.c_ulong, ctypes.c_void_p, ctypes.c_void_p
            ]

            crypt32.CertGetNameStringW.restype = ctypes.c_ulong
            crypt32.CertGetNameStringW.argtypes = [
                ctypes.c_void_p, ctypes.c_ulong, ctypes.c_ulong,
                ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_ulong
            ]

            crypt32.CertCloseStore.restype = ctypes.c_bool
            crypt32.CertCloseStore.argtypes = [ctypes.c_void_p, ctypes.c_ulong]

            # Abrir repositório Pessoal (MY) do CURRENT_USER
            store = crypt32.CertOpenSystemStoreW(None, "MY")
            if not store:
                logger.warning("Não foi possível abrir o store MY do Windows.")
                return cert_names

            prev_context = None
            while True:
                context = crypt32.CertFindCertificateInStore(
                    store,
                    0x00000001 | 0x00010000,  # X509_ASN_ENCODING | PKCS_7_ASN_ENCODING
                    0,
                    0,                         # CERT_FIND_ANY
                    None,
                    prev_context
                )
                if not context:
                    break

                size = crypt32.CertGetNameStringW(context, 4, 0, None, None, 0)
                if size > 1:
                    buf = ctypes.create_unicode_buffer(size)
                    crypt32.CertGetNameStringW(context, 4, 0, None, buf, size)
                    name = buf.value

                    # Filtrar apenas certificados ICP-Brasil (e-CNPJ 14 dígitos / e-CPF 11 dígitos)
                    # Padrão: "RAZAO SOCIAL:CNPJ" ou "NOME PESSOA:CPF"
                    if ":" in name:
                        suffix = name.split(":")[-1].strip()
                        if suffix.isdigit() and len(suffix) in (11, 14):
                            cert_names.append(name)

                prev_context = context

            crypt32.CertCloseStore(store, 0)
        except Exception as e:
            logger.error(f"Erro ao obter certificados digitais do Windows: {e}")

        # Remover duplicados e ordenar alfabeticamente
        return sorted(list(set(cert_names)))

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(15)
        
        # Grid de Configurações Dividida
        main_form_layout = QHBoxLayout()
        main_form_layout.setSpacing(20)
        
        # Coluna 1: Banco de Dados SQL Server
        db_frame = QFrame()
        db_frame.setObjectName("cardFrame")
        db_layout = QVBoxLayout(db_frame)
        db_layout.setContentsMargins(15, 15, 15, 15)
        
        db_title = QLabel("Banco de Dados SQL Server")
        db_title.setObjectName("titleLabel")
        db_layout.addWidget(db_title)
        
        db_form = QFormLayout()
        db_form.setSpacing(10)
        
        self.txt_db_server = QLineEdit()
        self.txt_db_server.setText("127.0.0.1")
        self.txt_db_database = QLineEdit()
        self.txt_db_user = QLineEdit()
        self.txt_db_user.setText("sa")
        self.txt_db_password = QLineEdit()
        self.txt_db_password.setEchoMode(QLineEdit.Password)
        self.txt_db_password.setText("Mrts@2025")
        
        self.spin_db_port = QSpinBox()
        self.spin_db_port.setRange(1, 65535)
        self.spin_db_port.setValue(1433)
        
        db_form.addRow("Endereço do Servidor:", self.txt_db_server)
        db_form.addRow("Nome do Banco:", self.txt_db_database)
        db_form.addRow("Usuário do Banco:", self.txt_db_user)
        db_form.addRow("Senha do Banco:", self.txt_db_password)
        db_form.addRow("Porta SQL Server:", self.spin_db_port)
        db_layout.addLayout(db_form)
        main_form_layout.addWidget(db_frame)
        
        # Coluna 2: Automação e Navegador
        bot_frame = QFrame()
        bot_frame.setObjectName("cardFrame")
        bot_layout = QVBoxLayout(bot_frame)
        bot_layout.setContentsMargins(15, 15, 15, 15)
        
        bot_title = QLabel("Robô e Certificado Digital")
        bot_title.setObjectName("titleLabel")
        bot_layout.addWidget(bot_title)
        
        bot_form = QFormLayout()
        bot_form.setSpacing(10)
        
        # Dropdown de Certificados Detectados
        self.combo_certs = QComboBox()
        self.combo_certs.addItem("Autoseleção do Portal (Recomendado)")
        installed_certs = self.list_windows_certificates()
        for cert in installed_certs:
            self.combo_certs.addItem(cert)
            
        # Controles numéricos
        self.spin_threads = QSpinBox()
        self.spin_threads.setRange(1, 5)
        self.spin_threads.setValue(1)
        
        self.spin_delay = QDoubleSpinBox()
        self.spin_delay.setRange(0.50, 15.00)
        self.spin_delay.setSingleStep(0.50)
        self.spin_delay.setValue(3.00)
        self.spin_delay.setSuffix(" s")
        
        self.spin_retries = QSpinBox()
        self.spin_retries.setRange(1, 10)
        self.spin_retries.setValue(3)
        
        self.spin_timeout = QSpinBox()
        self.spin_timeout.setRange(10, 180)
        self.spin_timeout.setValue(30)
        self.spin_timeout.setSuffix(" s")
        
        self.txt_proxy = QLineEdit()
        self.txt_proxy.setPlaceholderText("http://usuario:senha@ip:porta (Opcional)")
        
        self.combo_headless = QComboBox()
        self.combo_headless.addItems(["Visível (Recomendado para A3 / PIN)", "Oculto (Modo Headless puro)"])
        
        bot_form.addRow("Certificado Digital:", self.combo_certs)
        bot_form.addRow("Quantidade de Threads:", self.spin_threads)
        bot_form.addRow("Delay entre Requisições:", self.spin_delay)
        bot_form.addRow("Quantidade Tentativas:", self.spin_retries)
        bot_form.addRow("Timeout da Conexão:", self.spin_timeout)
        bot_form.addRow("Proxy do Navegador:", self.txt_proxy)
        bot_form.addRow("Modo de Execução:", self.combo_headless)
        
        bot_layout.addLayout(bot_form)
        main_form_layout.addWidget(bot_frame)
        
        layout.addLayout(main_form_layout)
        
        # Botão de Salvamento
        self.btn_save = QPushButton("Salvar Configurações")
        self.btn_save.setObjectName("successButton")
        self.btn_save.clicked.connect(self.save_settings)
        layout.addWidget(self.btn_save)

    def save_settings(self):
        """Coleta todos os dados preenchidos no formulário e emite sinal de salvamento."""
        data = {
            "db_server": self.txt_db_server.text().strip(),
            "db_database": self.txt_db_database.text().strip(),
            "db_user": self.txt_db_user.text().strip(),
            "db_password": self.txt_db_password.text(),
            "db_port": self.spin_db_port.value(),
            "cert_name": self.combo_certs.currentText(),
            "threads_count": self.spin_threads.value(),
            "request_delay": self.spin_delay.value(),
            "max_retries": self.spin_retries.value(),
            "timeout_seconds": self.spin_timeout.value(),
            "proxy_url": self.txt_proxy.text().strip() or None,
            "headless_mode": True if self.combo_headless.currentIndex() == 1 else False
        }
        self.save_requested.emit(data)

    def load_settings_data(self, data: dict):
        """Carrega os campos da UI com as configurações recuperadas do banco."""
        if not data:
            return
            
        self.txt_db_server.setText(data.get("db_server", "127.0.0.1"))
        self.txt_db_database.setText(data.get("db_database", ""))
        self.txt_db_user.setText(data.get("db_user", "sa"))
        self.spin_db_port.setValue(data.get("db_port", 1433))
        
        # Certificado
        cert_name = data.get("cert_name", "")
        idx_cert = self.combo_certs.findText(cert_name)
        if idx_cert >= 0:
            self.combo_certs.setCurrentIndex(idx_cert)
            
        self.spin_threads.setValue(data.get("threads_count", 1))
        self.spin_delay.setValue(float(data.get("request_delay", 3.00)))
        self.spin_retries.setValue(data.get("max_retries", 3))
        self.spin_timeout.setValue(data.get("timeout_seconds", 30))
        self.txt_proxy.setText(data.get("proxy_url") or "")
        
        headless = data.get("headless_mode", False)
        self.combo_headless.setCurrentIndex(1 if headless else 0)
