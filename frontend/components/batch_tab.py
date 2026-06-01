# frontend/components/batch_tab.py
from datetime import datetime
import json
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QFrame, 
                               QLabel, QPlainTextEdit, QDateEdit, QLineEdit, 
                               QPushButton, QTableWidget, QTableWidgetItem, 
                               QFileDialog, QHeaderView)
from PySide6.QtCore import Qt, QDate

class BatchTab(QWidget):
    """
    Interface para parametrização da Busca de XMLs SAT em Lote.
    Lida com a lista de CNPJs, período de busca, diretório de saída e fila em tempo real.
    """
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.init_ui()
        
    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(15)
        
        # 1. Painel de Configurações do Lote (Formulário)
        form_frame = QFrame()
        form_frame.setObjectName("cardFrame")
        form_layout = QHBoxLayout(form_frame)
        form_layout.setContentsMargins(15, 15, 15, 15)
        form_layout.setSpacing(20)
        
        # Coluna da Esquerda: Lista de CNPJs
        left_layout = QVBoxLayout()
        lbl_cnpj = QLabel("Lista de CNPJs (um por linha):")
        lbl_cnpj.setObjectName("subtitleLabel")
        self.txt_cnpjs = QPlainTextEdit()
        self.txt_cnpjs.setPlaceholderText("00.000.000/0000-00\n11111111111111")
        self.txt_cnpjs.setMinimumWidth(250)
        self.txt_cnpjs.setMaximumHeight(130)
        left_layout.addWidget(lbl_cnpj)
        left_layout.addWidget(self.txt_cnpjs)
        form_layout.addLayout(left_layout)
        
        # Coluna da Direita: Período e Pasta de Saída
        right_layout = QVBoxLayout()
        right_layout.setSpacing(8)
        
        # Período (Data Inicial e Final lado a lado)
        periodo_layout = QHBoxLayout()
        
        start_box = QVBoxLayout()
        lbl_start = QLabel("Data Inicial:")
        lbl_start.setObjectName("subtitleLabel")
        self.date_start = QDateEdit()
        self.date_start.setCalendarPopup(True)
        self.date_start.setDate(QDate.currentDate().addDays(-30))  # Padrão: Último mês
        start_box.addWidget(lbl_start)
        start_box.addWidget(self.date_start)
        
        end_box = QVBoxLayout()
        lbl_end = QLabel("Data Final:")
        lbl_end.setObjectName("subtitleLabel")
        self.date_end = QDateEdit()
        self.date_end.setCalendarPopup(True)
        self.date_end.setDate(QDate.currentDate())
        end_box.addWidget(lbl_end)
        end_box.addWidget(self.date_end)
        
        periodo_layout.addLayout(start_box)
        periodo_layout.addLayout(end_box)
        right_layout.addLayout(periodo_layout)
        
        # Pasta de Destino
        folder_label = QLabel("Pasta de Destino para Downloads:")
        folder_label.setObjectName("subtitleLabel")
        folder_picker_layout = QHBoxLayout()
        self.txt_output_dir = QLineEdit()
        self.txt_output_dir.setPlaceholderText("Pasta padrão (downloads/)")
        self.btn_select_folder = QPushButton("Procurar...")
        self.btn_select_folder.setObjectName("secondaryButton")
        self.btn_select_folder.clicked.connect(self.select_folder)
        
        folder_picker_layout.addWidget(self.txt_output_dir)
        folder_picker_layout.addWidget(self.btn_select_folder)
        
        right_layout.addWidget(folder_label)
        right_layout.addLayout(folder_picker_layout)
        form_layout.addLayout(right_layout)
        
        layout.addWidget(form_frame)
        
        # 2. Painel de Resumo Consolidado do Lote (Novo)
        self.summary_frame = QFrame()
        self.summary_frame.setObjectName("cardFrame")
        self.summary_frame.setStyleSheet("""
            QFrame#cardFrame {
                background-color: #1e293b;
                border: 1px solid #334155;
                border-radius: 6px;
            }
        """)
        summary_layout = QVBoxLayout(self.summary_frame)
        summary_layout.setContentsMargins(15, 12, 15, 12)
        summary_layout.setSpacing(8)
        
        # Primeira linha: Lotes Concluídos e Total XMLs Baixados
        row1_layout = QHBoxLayout()
        self.lbl_lotes_progress = QLabel("Lotes Concluídos: 0 de 0 (0%)")
        self.lbl_lotes_progress.setStyleSheet("font-weight: bold; color: #3b82f6; font-size: 13px;")
        
        self.lbl_xmls_total = QLabel("Total XMLs Baixados: 0")
        self.lbl_xmls_total.setStyleSheet("font-weight: bold; color: #10b981; font-size: 13px;")
        
        row1_layout.addWidget(self.lbl_lotes_progress)
        row1_layout.addStretch()
        row1_layout.addWidget(self.lbl_xmls_total)
        summary_layout.addLayout(row1_layout)
        
        # Segunda linha: Datas Processadas
        self.lbl_dates_processed = QLabel("Datas Processadas: Nenhuma")
        self.lbl_dates_processed.setStyleSheet("color: #94a3b8; font-size: 12px;")
        self.lbl_dates_processed.setWordWrap(True)
        summary_layout.addWidget(self.lbl_dates_processed)
        
        layout.addWidget(self.summary_frame)
        
        # 3. Tabela de Acompanhamento da Fila em Tempo Real
        table_label = QLabel("Fila de Execução e Status em Tempo Real:")
        table_label.setObjectName("subtitleLabel")
        layout.addWidget(table_label)
        
        self.table_queue = QTableWidget()
        self.table_queue.setColumnCount(6)
        self.table_queue.setHorizontalHeaderLabels([
            "CNPJ", "Série SAT", "Período", "XMLs Baixados", "Status", "Última Atualização"
        ])
        self.table_queue.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table_queue.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table_queue.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.table_queue.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        
        layout.addWidget(self.table_queue)

    def select_folder(self):
        """Abre caixa de diálogo nativa do SO para selecionar pasta de downloads."""
        dir_path = QFileDialog.getExistingDirectory(self, "Selecionar Pasta de Downloads")
        if dir_path:
            self.txt_output_dir.setText(dir_path)

    def get_form_data(self) -> dict:
        """Coleta e sanitiza os campos do formulário para passar à thread do Robô."""
        cnpjs_text = self.txt_cnpjs.toPlainText()
        # Separar linhas e limpar espaços/caracteres não numéricos
        cnpjs = []
        for line in cnpjs_text.split("\n"):
            clean = "".join(filter(str.isdigit, line))
            if clean:
                cnpjs.append(clean)
                
        # Obter datas (Python datetime)
        start_qdate = self.date_start.date()
        end_qdate = self.date_end.date()
        
        start_dt = datetime(start_qdate.year(), start_qdate.month(), start_qdate.day())
        end_dt = datetime(end_qdate.year(), end_qdate.month(), end_qdate.day(), 23, 59, 59)
        
        return {
            "cnpjs": cnpjs,
            "start_date": start_dt,
            "end_date": end_dt,
            "download_folder": self.txt_output_dir.text().strip()
        }

    def update_queue_table(self, queue_items: list):
        """Atualiza a grade QTableWidget em tempo real com o status de execução de cada item da fila e consolida o painel de resumo."""
        self.table_queue.setRowCount(0)
        self.table_queue.setRowCount(len(queue_items))
        
        total_lotes = len(queue_items)
        lotes_concluidos = 0
        total_xmls = 0
        datas_concluidas = []
        
        for idx, item in enumerate(queue_items):
            # CNPJ
            self.table_queue.setItem(idx, 0, QTableWidgetItem(item.cnpj))
            
            # Série SAT
            serie = item.numero_serie_sat or "Carregando..."
            self.table_queue.setItem(idx, 1, QTableWidgetItem(serie))
            
            # Período
            periodo = f"{item.periodo_inicio.strftime('%d/%m/%Y')} - {item.periodo_fim.strftime('%d/%m/%Y')}"
            self.table_queue.setItem(idx, 2, QTableWidgetItem(periodo))
            
            # XMLs Baixados
            self.table_queue.setItem(idx, 3, QTableWidgetItem(str(item.xmls_baixados)))
            total_xmls += item.xmls_baixados
            
            # Status (com alinhamento e cores personalizadas)
            status_item = QTableWidgetItem(item.status)
            status_item.setTextAlignment(Qt.AlignCenter)
            if item.status == "CONCLUIDO":
                status_item.setForeground(Qt.green)
                lotes_concluidos += 1
                
                # Armazenar data(s) concluída(s)
                if item.datas_especificas:
                    try:
                        datas = json.loads(item.datas_especificas)
                        datas_concluidas.extend(datas)
                    except Exception:
                        pass
                else:
                    datas_concluidas.append(f"{item.periodo_inicio.strftime('%d/%m/%Y')} a {item.periodo_fim.strftime('%d/%m/%Y')}")
            elif item.status == "ERRO":
                status_item.setForeground(Qt.red)
            elif item.status == "EM_ANDAMENTO":
                status_item.setForeground(Qt.cyan)
            self.table_queue.setItem(idx, 4, status_item)
            
            # Última Atualização
            att_time = item.data_atualizacao.strftime("%H:%M:%S")
            self.table_queue.setItem(idx, 5, QTableWidgetItem(att_time))
            
        self.table_queue.resizeRowsToContents()
        
        # Atualizar painel de resumo
        pct = (lotes_concluidos / total_lotes * 100) if total_lotes > 0 else 0
        self.lbl_lotes_progress.setText(f"Lotes Concluídos: {lotes_concluidos} de {total_lotes} ({pct:.1f}%)")
        self.lbl_xmls_total.setText(f"Total XMLs Baixados: {total_xmls}")
        
        if datas_concluidas:
            # Remover duplicados mantendo a ordem
            unique_datas = list(dict.fromkeys(datas_concluidas))
            self.lbl_dates_processed.setText(f"Datas Processadas: {', '.join(unique_datas)}")
        else:
            self.lbl_dates_processed.setText("Datas Processadas: Nenhuma")
