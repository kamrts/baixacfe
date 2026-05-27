# frontend/components/dashboard_tab.py
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QFrame, 
                               QLabel, QPushButton, QProgressBar, QPlainTextEdit)
from PySide6.QtGui import QTextCursor
from PySide6.QtCore import Qt, Signal, Slot

class DashboardTab(QWidget):
    """
    Painel Principal (Dashboard) contendo o status de processamento,
    indicadores chave de desempenho (KPIs), console de logs e botões de controle.
    """
    
    # Sinais emitidos pelos botões da interface
    start_batch_requested = Signal()
    start_isolated_requested = Signal()
    stop_requested = Signal()
    resume_requested = Signal()
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.init_ui()
        
    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(15)
        
        # 1. Grade Superior de Cards de Status (KPIs)
        kpi_layout = QHBoxLayout()
        kpi_layout.setSpacing(10)
        
        self.card_status = self.create_kpi_card("STATUS DO ROBÔ", "Parado", "#94a3b8")
        self.card_success = self.create_kpi_card("XMLS BAIXADOS", "0", "#10b981")
        self.card_errors = self.create_kpi_card("ERROS", "0", "#ef4444")
        self.card_time = self.create_kpi_card("TEMPO ESTIMADO", "--:--", "#3b82f6")
        
        kpi_layout.addWidget(self.card_status)
        kpi_layout.addWidget(self.card_success)
        kpi_layout.addWidget(self.card_errors)
        kpi_layout.addWidget(self.card_time)
        layout.addLayout(kpi_layout)
        
        # 2. Barra de Progresso Geral
        progress_layout = QVBoxLayout()
        progress_label = QLabel("Progresso da Execução:")
        progress_label.setObjectName("subtitleLabel")
        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        self.progress_bar.setFixedHeight(20)
        
        progress_layout.addWidget(progress_label)
        progress_layout.addWidget(self.progress_bar)
        layout.addLayout(progress_layout)
        
        # 3. Painel de Controle (Botões Principais)
        controls_layout = QHBoxLayout()
        controls_layout.setSpacing(10)
        
        self.btn_start_batch = QPushButton("Iniciar Busca em Lote")
        self.btn_start_batch.setObjectName("successButton")
        self.btn_start_batch.clicked.connect(self.start_batch_requested.emit)
        
        self.btn_start_isolated = QPushButton("Iniciar Busca Isolada")
        self.btn_start_isolated.setObjectName("successButton")
        self.btn_start_isolated.clicked.connect(self.start_isolated_requested.emit)
        
        self.btn_pause = QPushButton("Pausar Execução")
        self.btn_pause.setObjectName("secondaryButton")
        self.btn_pause.setEnabled(False)
        self.btn_pause.clicked.connect(self.resume_requested.emit)
        
        self.btn_stop = QPushButton("Parar Execução")
        self.btn_stop.setObjectName("dangerButton")
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self.stop_requested.emit)
        
        controls_layout.addWidget(self.btn_start_batch)
        controls_layout.addWidget(self.btn_start_isolated)
        controls_layout.addWidget(self.btn_pause)
        controls_layout.addWidget(self.btn_stop)
        layout.addLayout(controls_layout)
        
        # 4. Console de Logs em Tempo Real
        log_layout = QVBoxLayout()
        log_title = QLabel("Logs em Tempo Real (Console):")
        log_title.setObjectName("subtitleLabel")
        
        self.log_console = QPlainTextEdit()
        self.log_console.setObjectName("logConsole")
        self.log_console.setReadOnly(True)
        self.log_console.setMinimumHeight(280)
        
        log_layout.addWidget(log_title)
        log_layout.addWidget(self.log_console)
        layout.addLayout(log_layout)

    def create_kpi_card(self, title: str, initial_value: str, color_hex: str) -> QFrame:
        """Helper para criar cards de status elegantes (QFrame)."""
        card = QFrame()
        card.setObjectName("cardFrame")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(15, 15, 15, 15)
        card_layout.setAlignment(Qt.AlignCenter)
        
        lbl_title = QLabel(title)
        lbl_title.setStyleSheet("font-size: 10px; font-weight: bold; color: #94a3b8; text-transform: uppercase;")
        lbl_title.setAlignment(Qt.AlignCenter)
        
        lbl_val = QLabel(initial_value)
        lbl_val.setStyleSheet(f"font-size: 22px; font-weight: bold; color: {color_hex};")
        lbl_val.setAlignment(Qt.AlignCenter)
        
        card_layout.addWidget(lbl_title)
        card_layout.addWidget(lbl_val)
        
        # Guardar referência do valor no próprio card para atualização futura
        card.value_label = lbl_val
        return card

    @Slot(str)
    def append_log(self, text: str):
        """Adiciona uma nova linha de log ao console e rotaciona a barra de rolagem."""
        self.log_console.appendPlainText(text)
        self.log_console.moveCursor(QTextCursor.End)

    def clear_logs(self):
        """Limpa o console de logs."""
        self.log_console.clear()

    def update_kpi(self, kpi_name: str, value: str):
        """Atualiza dinamicamente o valor exibido nos cards superior."""
        if kpi_name == "status":
            self.card_status.value_label.setText(value)
            # Mudar cor baseado no estado
            if "andamento" in value.lower() or "ativo" in value.lower():
                self.card_status.value_label.setStyleSheet("font-size: 22px; font-weight: bold; color: #10b981;")
            elif "recuperando" in value.lower() or "pausado" in value.lower():
                self.card_status.value_label.setStyleSheet("font-size: 22px; font-weight: bold; color: #3b82f6;")
            else:
                self.card_status.value_label.setStyleSheet("font-size: 22px; font-weight: bold; color: #94a3b8;")
        elif kpi_name == "success":
            self.card_success.value_label.setText(value)
        elif kpi_name == "errors":
            self.card_errors.value_label.setText(value)
        elif kpi_name == "time":
            self.card_time.value_label.setText(value)

    def set_running_state(self, running: bool):
        """Bloqueia/Desbloqueia os botões da UI conforme o robô está ativo ou inativo."""
        self.btn_start_batch.setEnabled(not running)
        self.btn_start_isolated.setEnabled(not running)
        self.btn_pause.setEnabled(running)
        self.btn_stop.setEnabled(running)
