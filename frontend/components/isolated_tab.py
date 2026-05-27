# frontend/components/isolated_tab.py
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QFrame, 
                               QLabel, QLineEdit, QPushButton, QTableWidget, 
                               QTableWidgetItem, QFileDialog, QHeaderView)
from PySide6.QtCore import Qt, Signal

class IsolatedTab(QWidget):
    """
    Interface para a Busca Isolada de CF-e por Chaves de Acesso.
    Permite carregar uma planilha XLSX, validar as chaves e visualizar a extração de produtos em tempo real.
    """
    
    file_selected = Signal(str)
    
    def __init__(self, parent=None):
        super().__init__(parent)
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
        
        # 2. Tabela de Resultados
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

    def populate_results_table(self, rows: list):
        """Popula a tabela inicialmente após a leitura e validação do Excel."""
        self.table_results.setRowCount(0)
        self.table_results.setRowCount(len(rows))
        
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

    def update_key_status(self, progress_data: dict):
        """Atualiza dinamicamente a célula de status de uma chave específica durante a execução."""
        target_key = progress_data["chave"]
        
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
