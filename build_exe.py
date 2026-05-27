# build_exe.py
import sys
import subprocess
from pathlib import Path

def run_command(cmd: str, cwd: Path):
    """Executa um comando no prompt e exibe a saída em tempo real."""
    print(f"Executando: {cmd}")
    process = subprocess.Popen(
        cmd,
        shell=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        cwd=str(cwd),
        encoding='utf-8',
        errors='replace'
    )
    while True:
        output = process.stdout.readline()
        if output == '' and process.poll() is not None:
            break
        if output:
            print(output.strip())
    rc = process.poll()
    return rc

def main():
    root_dir = Path(__file__).resolve().parent
    venv_pip = root_dir / ".venv" / "Scripts" / "pip.exe"
    venv_pyinstaller = root_dir / ".venv" / "Scripts" / "pyinstaller.exe"
    
    if not venv_pip.exists():
        print("Erro: Ambiente virtual .venv não encontrado. Crie o ambiente primeiro.")
        sys.exit(1)
        
    print("--- 1. Garantindo instalação do PyInstaller no .venv ---")
    rc = run_command(f'"{venv_pip}" install pyinstaller', root_dir)
    if rc != 0:
        print("Erro ao instalar PyInstaller.")
        sys.exit(1)
        
    print("\n--- 2. Compilando aplicação Desktop via PyInstaller ---")
    
    # Parâmetros de compilação
    # - --noconsole: Esconde a tela preta do CMD ao rodar (modo GUI nativo)
    # - --onefile: Junta tudo em um único executável .EXE
    # - --add-data: Copia o styles.css para dentro do bundle executável
    # - --hidden-import: Garante que os drivers dinâmicos do pyodbc e ORM sqlalchemy sejam empacotados
    pyinstaller_cmd = (
        f'"{venv_pyinstaller}" '
        f'--noconsole '
        f'--onefile '
        f'--name "SAT_XML_Downloader" '
        f'--add-data "frontend/styles.css;frontend" '
        f'--hidden-import "pyodbc" '
        f'--hidden-import "cryptography" '
        f'--hidden-import "openpyxl" '
        f'--hidden-import "pandas" '
        f'--hidden-import "playwright" '
        f'--hidden-import "sqlalchemy.sql.default_comparator" '
        f'app.py'
    )
    
    rc = run_command(pyinstaller_cmd, root_dir)
    if rc == 0:
        print("\n=======================================================")
        print("✅ Executável compilado com sucesso!")
        print(f"O arquivo final está localizado em: {root_dir / 'dist' / 'SAT_XML_Downloader.exe'}")
        print("=======================================================")
    else:
        print("\n❌ Ocorreu um erro durante a compilação do executável.")
        sys.exit(1)

if __name__ == "__main__":
    main()
