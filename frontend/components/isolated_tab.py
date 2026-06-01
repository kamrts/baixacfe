# frontend/components/isolated_tab.py
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QFrame, 
                               QLabel, QLineEdit, QPushButton, QTableWidget, 
                               QTableWidgetItem, QFileDialog, QHeaderView)
from PySide6.QtCore import Qt, Signal
from datetime import datetime

class IsolatedTab(QWidget):
    """
    Interface para a Busca Isolada de CF-e por Chaves de Acesso.
    Permite carregar uma planilha XLSX, validar as chaves e visualizar a extração de produtos em tempo real.
    """
    
    file_selected = Signal(str)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.start_time = None
        self.total_keys = 0
        self.processed_keys = 0
        self.init_ui()
        
    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(15)
        
        # 1. Painel de Configurações (Formulário)
        form_frame = QFrame()
        form_frame.setObjectName("cardFrame")
        form_layout = QVBoxLayout(form_frame)
        form_layout.setContentsMargins(15, 15, 15, 15)
        form_layout.setSpacing(12)
        
        # Selecionar Arquivo Excel
        file_label = QLabel("Carregar Planilha XLSX contendo as Chaves de Acesso SAT:")
        file_label.setObjectName("subtitleLabel")
        file_picker_layout = QHBoxLayout()
        self.txt_file_path = QLineEdit()
        self.txt_file_path.setPlaceholderText("Selecione o arquivo da planilha (.xlsx)...")
        self.btn_select_file = QPushButton("Selecionar Planilha...")
        self.btn_select_file.setObjectName("secondaryButton")
        self.btn_select_file.clicked.connect(self.select_file)
        
        file_picker_layout.addWidget(self.txt_file_path)
        file_picker_layout.addWidget(self.btn_select_file)
        
        form_layout.addWidget(file_label)
        form_layout.addLayout(file_picker_layout)
        
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
        
        form_layout.addWidget(folder_label)
        form_layout.addLayout(folder_picker_layout)
        
        layout.addWidget(form_frame)
        
        # 2. Painel de Resumo / Estatísticas da Execução
        self.stats_frame = QFrame()
        self.stats_frame.setObjectName("cardFrame")
        self.stats_frame.setStyleSheet("""
            QFrame#cardFrame {
                background-color: #1e293b;
                border: 1px solid #334155;
                border-radius: 6px;
            }
        """)
        stats_layout = QHBoxLayout(self.stats_frame)
        stats_layout.setContentsMargins(15, 10, 15, 10)
        stats_layout.setSpacing(10)
        
        self.lbl_processed = QLabel("Processadas: 0 / 0")
        self.lbl_processed.setStyleSheet("font-weight: bold; color: #3b82f6; font-size: 13px;")
        
        self.lbl_remaining = QLabel("Faltam: 0")
        self.lbl_remaining.setStyleSheet("font-weight: bold; color: #94a3b8; font-size: 13px;")
        
        self.lbl_errors = QLabel("Erros: 0")
        self.lbl_errors.setStyleSheet("font-weight: bold; color: #ef4444; font-size: 13px;")
        
        self.lbl_time = QLabel("Tempo Restante: --:--")
        self.lbl_time.setStyleSheet("font-weight: bold; color: #10b981; font-size: 13px;")
        
        stats_layout.addWidget(self.lbl_processed, 1, Qt.AlignCenter)
        stats_layout.addWidget(self.lbl_remaining, 1, Qt.AlignCenter)
        stats_layout.addWidget(self.lbl_errors, 1, Qt.AlignCenter)
        stats_layout.addWidget(self.lbl_time, 2, Qt.AlignCenter)
        
        layout.addWidget(self.stats_frame)
        
        # 3. Tabela de Resultados
        table_label = QLabel("Status das Chaves Processadas:")
        table_label.setObjectName("subtitleLabel")
        layout.addWidget(table_label)
        
        self.table_results = QTableWidget()
        self.table_results.setColumnCount(5)
        self.table_results.setHorizontalHeaderLabels([
            "Linha Excel", "Chave de Acesso", "CNPJ", "Status", "Resultado / Erro"
        ])
        self.table_results.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table_results.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table_results.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table_results.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        
        layout.addWidget(self.table_results)

    def select_file(self):
        """Abre caixa de diálogo para escolher arquivo Excel (.xlsx)."""
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Selecionar Planilha SAT", "", "Arquivos Excel (*.xlsx)"
        )
        if file_path:
            self.txt_file_path.setText(file_path)
            self.file_selected.emit(file_path)

    def select_folder(self):
        """Abre caixa de diálogo para escolher pasta de downloads."""
        dir_path = QFileDialog.getExistingDirectory(self, "Selecionar Pasta de Downloads")
        if dir_path:
            self.txt_output_dir.setText(dir_path)

    def get_form_data(self) -> dict:
        """Retorna os dados configurados para processamento isolado."""
        return {
            "file_path": self.txt_file_path.text().strip(),
            "download_folder": self.txt_output_dir.text().strip()
        }

    def reset_stats(self):
        """Reinicia as variáveis de estatísticas para uma nova busca."""
        self.start_time = None
        self.processed_keys = 0
        self.update_stats_display()

    def populate_results_table(self, rows: list):
        """Popula a tabela inicialmente após a leitura e validação do Excel."""
        self.table_results.setRowCount(0)
        self.table_results.setRowCount(len(rows))
        
        self.total_keys = len(rows)
        self.processed_keys = 0
        self.start_time = None
        
        for idx, r in enumerate(rows):
            # Linha
            self.table_results.setItem(idx, 0, QTableWidgetItem(str(r["linha"])))
            # Chave
            self.table_results.setItem(idx, 1, QTableWidgetItem(r["chave"]))
            # CNPJ
            self.table_results.setItem(idx, 2, QTableWidgetItem(r["cnpj"]))
            
            # Status
            status_item = QTableWidgetItem(r["status"])
            status_item.setTextAlignment(Qt.AlignCenter)
            if r["status"] == "VALIDADO":
                status_item.setForeground(Qt.cyan)
            elif "ERRO" in r["status"]:
                status_item.setForeground(Qt.red)
            self.table_results.setItem(idx, 3, status_item)
            
            # Mensagem
            self.table_results.setItem(idx, 4, QTableWidgetItem(r["mensagem"]))
            
        self.table_results.resizeRowsToContents()
        self.update_stats_display()

    def update_stats_display(self):
        """Recalcula e atualiza as informações exibidas nos cards superiores."""
        # Contar erros diretamente na tabela para precisão absoluta
        erros = 0
        for r_idx in range(self.table_results.rowCount()):
            status_item = self.table_results.item(r_idx, 3)
            if status_item:
                status_text = status_item.text()
                if "ERRO" in status_text or status_text == "NAO_ENCONTRADO":
                    erros += 1
                    
        self.lbl_processed.setText(f"Processadas: {self.processed_keys} / {self.total_keys}")
        self.lbl_remaining.setText(f"Faltam: {max(0, self.total_keys - self.processed_keys)}")
        self.lbl_errors.setText(f"Erros: {erros}")
        
        # Calcular Tempo Estimado Relativo
        if self.start_time and self.processed_keys > 0:
            elapsed_seconds = (datetime.now() - self.start_time).total_seconds()
            speed = self.processed_keys / elapsed_seconds if elapsed_seconds > 0 else 0
            remaining = max(0, self.total_keys - self.processed_keys)
            
            if speed > 0 and remaining > 0:
                remaining_seconds = int(remaining / speed)
                mins, secs = divmod(remaining_seconds, 60)
                hrs, mins = divmod(mins, 60)
                if hrs > 0:
                    time_str = f"{hrs:02d}h {mins:02d}m {secs:02d}s"
                else:
                    time_str = f"{mins:02d}m {secs:02d}s"
                self.lbl_time.setText(f"Tempo Restante: {time_str}")
            elif remaining == 0:
                self.lbl_time.setText("Tempo Restante: Concluído")
            else:
                self.lbl_time.setText("Tempo Restante: Calculando...")
        else:
            self.lbl_time.setText("Tempo Restante: Calculando...")

    def update_key_status(self, progress_data: dict):
        """Atualiza dinamicamente a célula de status de uma chave específica durante a execução."""
        if self.start_time is None:
            self.start_time = datetime.now()
            
        target_key = progress_data["chave"]
        self.total_keys = progress_data.get("total", self.total_keys)
        self.processed_keys = progress_data.get("atual", self.processed_keys)
        
        # Procurar a linha correspondente na tabela
        for r_idx in range(self.table_results.rowCount()):
            item_key = self.table_results.item(r_idx, 1)
            if item_key and item_key.text() == target_key:
                # Atualizar Status
                status_item = QTableWidgetItem(progress_data["status"])
                status_item.setTextAlignment(Qt.AlignCenter)
                
                if progress_data["status"] == "CONCLUIDO":
                    status_item.setForeground(Qt.green)
                elif "ERRO" in progress_data["status"]:
                    status_item.setForeground(Qt.red)
                elif progress_data["status"] == "PROCESSANDO":
                    status_item.setForeground(Qt.yellow)
                    
                self.table_results.setItem(r_idx, 3, status_item)
                
                # Atualizar Mensagem
                self.table_results.setItem(r_idx, 4, QTableWidgetItem(progress_data["mensagem"]))
                break
                
        self.table_results.resizeRowsToContents()
        self.update_stats_display()
