# app.py
import sys
import os
import logging
from datetime import datetime
from pathlib import Path

# Ajustar o caminho de busca do navegador Playwright ao rodar compilado no PyInstaller
if getattr(sys, 'frozen', False):
    user_appdata = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~/AppData/Local")
    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = os.path.join(user_appdata, "ms-playwright")
from PySide6.QtWidgets import QApplication
from frontend.main_window import MainWindow

def setup_logging():
    """
    Configura o logging estruturado por datas no diretório /logs/.
    Gera streams para arquivos de log físicos e console.
    """
    logs_dir = Path(__file__).resolve().parent / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    
    today_str = datetime.now().strftime("%Y-%m-%d")
    log_file_path = logs_dir / f"sat_bot_{today_str}.log"
    
    # Criar logger principal
    logger = logging.getLogger("SAT_Downloader")
    logger.setLevel(logging.DEBUG)
    
    # Limpar handlers anteriores para evitar duplicações
    logger.handlers.clear()
    
    # Formato estruturado
    formatter = logging.Formatter(
        '%(asctime)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s',
        datefmt='%d/%m/%Y %H:%M:%S'
    )
    
    # Handler para Arquivo Físico
    file_handler = logging.FileHandler(log_file_path, encoding='utf-8')
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    
    # Handler para o console padrão (Stdout)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.DEBUG)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
    
    logger.info("Sistema de Logs Estruturados inicializado com sucesso!")
    return logger

def main():
    # 1. Inicializar Logs
    setup_logging()
    
    # 2. Inicializar Aplicação Qt Desktop
    # Configurações para alto DPI no Windows
    os.environ["QT_AUTO_SCREEN_SCALE_FACTOR"] = "1"
    
    app = QApplication(sys.argv)
    app.setStyle("Fusion") # Fusion é o melhor motor base para estilização QSS escura
    
    # 3. Inicializar Janela Principal
    window = MainWindow()
    window.show()
    
    # Executar loop de eventos principal do Qt
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
