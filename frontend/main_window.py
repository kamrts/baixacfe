# frontend/main_window.py
import os
import asyncio
import logging
from pathlib import Path
from PySide6.QtWidgets import QMainWindow, QTabWidget, QMessageBox
from PySide6.QtCore import QThread, Signal, Slot

from database.connection import create_db_engine, get_session_factory, initialize_database
from database.models import QueueProgress
from backend.state_manager import StateManager
from backend.sat_bot import SATBot
from backend.sat_bot_isolated import SATBotIsolated

from frontend.components.dashboard_tab import DashboardTab
from frontend.components.batch_tab import BatchTab
from frontend.components.isolated_tab import IsolatedTab
from frontend.components.settings_tab import SettingsTab

logger = logging.getLogger("SAT_Downloader")

class BotWorker(QThread):
    """
    Worker genérico em QThread que cria e gerencia seu próprio loop de eventos AsyncIO.
    Permite rodar o robô Playwright em background sem travar a interface Qt principal.
    """
    log_received = Signal(str)
    progress_received = Signal(dict)
    finished_signal = Signal(str)  # Retorna mensagem de fim (sucesso/erro)
    
    def __init__(self, bot_instance, run_type="batch", xlsx_path=None, output_folder=None):
        super().__init__()
        self.bot = bot_instance
        self.run_type = run_type
        self.xlsx_path = xlsx_path
        self.output_folder = output_folder
        self.loop = None

    def run(self):
        # Inicializar loop assíncrono para esta thread de background
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        
        # Bind de callbacks do robô com sinais do Qt
        self.bot.on_log = lambda msg: self.log_received.emit(msg)
        
        try:
            if self.run_type == "batch":
                self.loop.run_until_complete(self.bot.run())
                self.finished_signal.emit("Busca em lote finalizada.")
            elif self.run_type == "isolated":
                # Robô de busca isolada recebe xlsx e destino
                self.bot.on_progress = lambda data: self.progress_received.emit(data)
                self.loop.run_until_complete(
                    self.bot.processar_planilha_xlsx(
                        Path(self.xlsx_path), Path(self.output_folder)
                    )
                )
                self.finished_signal.emit("Busca isolada por planilha finalizada.")
        except Exception as e:
            logger.error(f"Erro na execução da thread do robô: {e}")
            self.log_received.emit(f"Erro crítico na thread: {e}")
            self.finished_signal.emit(f"Finalizado com erro: {e}")
        finally:
            self.loop.close()


class MainWindow(QMainWindow):
    """
    Janela Principal do Sistema de Download de XML SAT.
    Orquestra a navegação, conexões de banco e despacho de threads em background.
    """
    
    def __init__(self):
        super().__init__()
        self.setWindowTitle("SAT/SP XML Downloader — Automação Fiscal")
        self.resize(1000, 720)
        self.session_factory = None
        self.bot_instance = None
        self.worker = None
        
        self.init_ui()
        self.load_stylesheet()
        
        # Carregar configuração inicial local (se houver banco configurado)
        self.carregar_configuracao_inicial()

    def init_ui(self):
        # Widget Central (Abas)
        self.tabs = QTabWidget()
        self.setCentralWidget(self.tabs)
        
        # Inicializar Componentes de Tab
        self.tab_dashboard = DashboardTab()
        self.tab_batch = BatchTab()
        self.tab_isolated = IsolatedTab()
        self.tab_settings = SettingsTab()
        
        # Adicionar abas
        self.tabs.addTab(self.tab_dashboard, "Painel de Controle")
        self.tabs.addTab(self.tab_batch, "Busca em Lote")
        self.tabs.addTab(self.tab_isolated, "Busca Isolada (XLSX)")
        self.tabs.addTab(self.tab_settings, "Configurações Técnicas")
        
        # Conectar Sinais de Tab com Lógica Principal
        self.tab_settings.save_requested.connect(self.salvar_configuracoes)
        self.tab_dashboard.start_batch_requested.connect(self.iniciar_busca_lote)
        self.tab_dashboard.start_isolated_requested.connect(self.iniciar_busca_isolada)
        self.tab_dashboard.stop_requested.connect(self.parar_execucao)
        
        # Repassar arquivo selecionado na aba isolada para pre-visualização na tabela
        self.tab_isolated.file_selected.connect(self.pre_validar_planilha)

    def load_stylesheet(self):
        """Carrega e aplica o arquivo QSS moderno de estilização."""
        import sys
        if getattr(sys, 'frozen', False):
            base_path = Path(sys._MEIPASS) / "frontend"
        else:
            base_path = Path(__file__).resolve().parent
            
        css_path = base_path / "styles.css"
        if css_path.exists():
            with open(css_path, "r", encoding="utf-8") as f:
                self.setStyleSheet(f.read())
        else:
            fallback_path = Path(__file__).resolve().parent / "styles.css"
            if fallback_path.exists():
                with open(fallback_path, "r", encoding="utf-8") as f:
                    self.setStyleSheet(f.read())
            else:
                logger.warning(f"Arquivo styles.css não encontrado em {css_path}. Utilizando tema básico.")

    def carregar_configuracao_inicial(self):
        """Tenta conectar ao banco SQL Server local com a senha encriptada localmente."""
        from config.settings import DEFAULT_DB_SERVER, DEFAULT_DB_DATABASE, DEFAULT_DB_USER, DEFAULT_DB_PASSWORD, DEFAULT_DB_PORT
        
        # 1. Tentar ler conexão do arquivo de ambiente .env
        server = DEFAULT_DB_SERVER
        db = DEFAULT_DB_DATABASE
        user = DEFAULT_DB_USER
        port = int(DEFAULT_DB_PORT)
        pwd = DEFAULT_DB_PASSWORD
        
        if not db:
            self.tab_dashboard.append_log("Banco de dados não configurado. Por favor, acesse a aba 'Configurações Técnicas' para ajustar.")
            self.tabs.setCurrentIndex(3)  # Joga o usuário na aba de Configurações
            return
            
        self.tab_dashboard.append_log(f"Tentando estabelecer conexão com SQL Server: {server}...")
        
        # Inicializar banco e tabelas (auto-generation)
        sucesso = initialize_database(server, db, user, pwd, port)
        
        if sucesso:
            engine = create_db_engine(server, db, user, pwd, port)
            self.session_factory = get_session_factory(engine)
            
            # Carregar e preencher dados na UI
            with self.session_factory() as session:
                config_db = StateManager.get_or_create_config(session)
                
                # Descriptografar senha salva
                decrypted_pwd = StateManager.get_decrypted_db_password(session)
                
                config_data = {
                    "db_server": config_db.db_server,
                    "db_database": config_db.db_database,
                    "db_user": config_db.db_user,
                    "db_port": config_db.db_port,
                    "cert_name": config_db.cert_name,
                    "threads_count": config_db.threads_count,
                    "request_delay": config_db.request_delay,
                    "max_retries": config_db.max_retries,
                    "timeout_seconds": config_db.timeout_seconds,
                    "proxy_url": config_db.proxy_url,
                    "headless_mode": config_db.headless_mode
                }
                
                # Atualizar campos na UI
                self.tab_settings.load_settings_data(config_data)
                # Manter senha carregada para edição futura
                self.tab_settings.txt_db_password.setText(decrypted_pwd or pwd)
                
                # Carregar pasta de download padrão da UI
                if config_db.download_folder:
                    self.tab_batch.txt_output_dir.setText(config_db.download_folder)
                    self.tab_isolated.txt_output_dir.setText(config_db.download_folder)
                    
            self.tab_dashboard.append_log("Conexão com SQL Server ativa. Tabelas de cabeçalho e itens operacionais.")
        else:
            self.tab_dashboard.append_log("FALHA DE CONEXÃO: Verifique se o serviço SQL Server está rodando ou valide as credenciais.", logging.ERROR)
            QMessageBox.critical(self, "Falha de Conexão", "Não foi possível conectar ao SQL Server local.\nAjuste as credenciais nas Configurações.")

    @Slot(dict)
    def salvar_configuracoes(self, data: dict):
        """Salva as configurações do formulário no banco de dados local."""
        if not self.session_factory:
            # Se ainda não conectou, tentar conectar agora com os dados novos
            server = data["db_server"]
            db = data["db_database"]
            user = data["db_user"]
            pwd = data["db_password"]
            port = data["db_port"]
            
            sucesso = initialize_database(server, db, user, pwd, port)
            if sucesso:
                engine = create_db_engine(server, db, user, pwd, port)
                self.session_factory = get_session_factory(engine)
            else:
                QMessageBox.critical(self, "Falha de Conexão", "Não foi possível conectar com os dados inseridos.")
                return
                
        # Salvar
        with self.session_factory() as session:
            sucesso = StateManager.save_config(session, data)
            
        if sucesso:
            QMessageBox.information(self, "Configurações", "Parâmetros salvos com sucesso no banco de dados!")
            self.tab_dashboard.append_log("Configurações atualizadas no banco de dados local.")
            # Sincronizar pastas de saída nas demais abas
            folder = data.get("download_folder")
            if folder:
                self.tab_batch.txt_output_dir.setText(folder)
                self.tab_isolated.txt_output_dir.setText(folder)
        else:
            QMessageBox.warning(self, "Configurações", "Erro ao salvar os parâmetros locais no banco.")

    @Slot(str)
    def pre_validar_planilha(self, file_path: str):
        """Lê e pré-valida a planilha Excel exibindo na UI antes de rodar."""
        self.tab_dashboard.append_log(f"Lendo e pré-validando chaves da planilha: {Path(file_path).name}...")
        
        # Inicializar leitor temporário para popular tabela
        bot_temp = SATBotIsolated(self.session_factory, {})
        
        try:
            import pandas as pd
            df = pd.read_excel(file_path)
            
            col_cnpj = [c for c in df.columns if "cnpj" in c.lower()]
            col_chave = [c for c in df.columns if "chave" in c.lower() or "cfe" in c.lower()]
            
            if not col_chave:
                self.tab_dashboard.append_log("Erro: Coluna de Chave de Acesso não encontrada na planilha.", logging.ERROR)
                return
                
            cnpj_col = col_cnpj[0] if col_cnpj else None
            chave_col = col_chave[0]
            
            rows = []
            for idx, row in df.iterrows():
                chave = "".join(filter(str.isdigit, str(row[chave_col])))
                cnpj = "".join(filter(str.isdigit, str(row[cnpj_col]))) if cnpj_col else ""
                
                valida, msg = bot_temp.validar_chave_sat(chave, cnpj)
                
                rows.append({
                    "linha": idx + 2,
                    "chave": chave,
                    "cnpj": cnpj or "N/A",
                    "status": "VALIDADO" if valida else "ERRO_VALIDACAO",
                    "mensagem": msg
                })
                
            self.tab_isolated.populate_results_table(rows)
            self.tab_dashboard.append_log(f"Planilha carregada. {len(rows)} linhas mapeadas na tabela da aba 'Busca Isolada'.")
        except Exception as e:
            self.tab_dashboard.append_log(f"Erro ao analisar planilha: {e}", logging.ERROR)

    def obter_configs_totais(self) -> dict:
        """Coleta configurações globais consolidadas do Banco de Dados e formulários.
        
        O cert_name é lido preferencialmente da UI atual para evitar a necessidade
        de salvar as configurações antes de rodar o robô.
        """
        config_consolidada = {}
        with self.session_factory() as session:
            cfg = StateManager.get_or_create_config(session)
            config_consolidada = {
                "threads_count": cfg.threads_count,
                "request_delay": float(cfg.request_delay),
                "max_retries": cfg.max_retries,
                "timeout_seconds": cfg.timeout_seconds,
                "proxy_url": cfg.proxy_url,
                "headless_mode": cfg.headless_mode,
                "download_folder": cfg.download_folder,
                "cert_name": cfg.cert_name
            }
        
        # Priorizar a seleção ATUAL da UI de certificado sobre o valor salvo no banco.
        # Isso garante que o certificado escolhido seja usado mesmo sem "Salvar Configurações".
        ui_cert = self.tab_settings.combo_certs.currentText()
        if ui_cert and ui_cert.strip():
            config_consolidada["cert_name"] = ui_cert
            
        # Priorizar modo de execução da UI atual também
        config_consolidada["headless_mode"] = (self.tab_settings.combo_headless.currentIndex() == 1)
        
        return config_consolidada

    def iniciar_busca_lote(self):
        """Despacha a busca em lote na thread de background QThread."""
        if not self.session_factory:
            QMessageBox.warning(self, "Conexão", "Configure e salve a conexão com o banco SQL Server primeiro.")
            return
            
        form_data = self.tab_batch.get_form_data()
        
        if not form_data["cnpjs"]:
            QMessageBox.warning(self, "Entrada Inválida", "Informe ao menos um CNPJ válido na lista.")
            return
            
        self.tab_dashboard.clear_logs()
        self.tab_dashboard.append_log("Iniciando fluxo de Busca em Lote...")
        
        # 1. Popular Fila no Banco de Dados
        with self.session_factory() as session:
            StateManager.populate_queue(
                session, 
                form_data["cnpjs"], 
                form_data["start_date"], 
                form_data["end_date"]
            )
            
            # Recuperar itens para exibir na Grid da aba de Lotes
            queue_items = session.query(QueueProgress).filter(
                QueueProgress.status != "CONCLUIDO"
            ).all()
            self.tab_batch.update_queue_table(queue_items)
            
        # 2. Criar instância do Robô Lote e Worker Thread
        cfg_bot = self.obter_configs_totais()
        if form_data["download_folder"]:
            cfg_bot["download_folder"] = form_data["download_folder"]
            
        self.bot_instance = SATBot(self.session_factory, cfg_bot)
        
        self.worker = BotWorker(self.bot_instance, run_type="batch")
        self.worker.log_received.connect(self.tab_dashboard.append_log)
        self.worker.finished_signal.connect(self.execucao_finalizada)
        
        # Configurar UI
        self.tab_dashboard.set_running_state(True)
        self.tab_dashboard.update_kpi("status", "Ativo (Lote)")
        self.tabs.setCurrentIndex(0) # Joga o usuário no dashboard para ver rodar
        
        self.worker.start()

    def iniciar_busca_isolada(self):
        """Despacha a busca isolada por chaves da planilha na thread de background QThread."""
        if not self.session_factory:
            QMessageBox.warning(self, "Conexão", "Configure e salve a conexão com o banco SQL Server primeiro.")
            return
            
        form_data = self.tab_isolated.get_form_data()
        
        if not form_data["file_path"] or not os.path.exists(form_data["file_path"]):
            QMessageBox.warning(self, "Entrada Inválida", "Selecione uma planilha XLSX válida (.xlsx) primeiro.")
            return
            
        self.tab_dashboard.clear_logs()
        self.tab_dashboard.append_log("Iniciando busca isolada por Planilha...")
        
        # Configurações do Robô Isolado
        cfg_bot = self.obter_configs_totais()
        if form_data["download_folder"]:
            cfg_bot["download_folder"] = form_data["download_folder"]
            
        self.bot_instance = SATBotIsolated(self.session_factory, cfg_bot)
        
        # Despachar Worker
        self.worker = BotWorker(
            self.bot_instance, 
            run_type="isolated", 
            xlsx_path=form_data["file_path"],
            output_folder=cfg_bot["download_folder"]
        )
        self.worker.log_received.connect(self.tab_dashboard.append_log)
        self.worker.progress_received.connect(self.tab_isolated.update_key_status)
        self.worker.finished_signal.connect(self.execucao_finalizada)
        
        # Configurar UI
        self.tab_dashboard.set_running_state(True)
        self.tab_dashboard.update_kpi("status", "Ativo (Isolado)")
        self.tabs.setCurrentIndex(0)
        
        self.worker.start()

    def parar_execucao(self):
        """Solicita a interrupção segura da thread ativa do robô."""
        if self.bot_instance:
            self.tab_dashboard.append_log("Parando robô de automação...", logging.WARNING)
            self.bot_instance.stop()

    @Slot(str)
    def execucao_finalizada(self, msg: str):
        """Slot acionado quando a thread de background conclui com sucesso ou erro."""
        self.tab_dashboard.append_log(f"Thread finalizada: {msg}")
        self.tab_dashboard.set_running_state(False)
        self.tab_dashboard.update_kpi("status", "Parado")
        
        # Atualizar tabelas para consolidar visualmente
        if self.session_factory:
            with self.session_factory() as session:
                queue_items = session.query(QueueProgress).all()
                self.tab_batch.update_queue_table(queue_items)
                
        QMessageBox.information(self, "Automação SAT", f"Processamento concluído!\n{msg}")
