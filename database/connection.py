# database/connection.py
import urllib
import pyodbc
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from database.models import Base
import logging

logger = logging.getLogger("SAT_Downloader")

def get_available_drivers():
    """Retorna a lista de drivers ODBC de SQL Server instalados no Windows."""
    try:
        drivers = [d for d in pyodbc.drivers() if "sql" in d.lower()]
        return drivers
    except Exception as e:
        logger.error(f"Erro ao listar drivers ODBC: {e}")
        return ["SQL Server"]  # Fallback básico do Windows

def get_best_driver() -> str:
    """Detecta o melhor driver disponível, priorizando os mais recentes."""
    installed = get_available_drivers()
    # Prioridades de drivers modernos
    priorities = [
        "ODBC Driver 18 for SQL Server",
        "ODBC Driver 17 for SQL Server",
        "ODBC Driver 13 for SQL Server",
        "SQL Server Native Client 11.0",
        "SQL Server"
    ]
    for p in priorities:
        if p in installed:
            return p
    # Se nenhum bater, pega o primeiro que contiver "SQL" ou o fallback universal
    for inst in installed:
        if "sql" in inst.lower():
            return inst
    return "SQL Server"

def get_connection_string(server, database, user, password, port=1433) -> str:
    """Monta a string de conexão ODBC de forma segura."""
    driver = get_best_driver()
    logger.info(f"Utilizando driver ODBC de banco: '{driver}'")
    
    # Montar os parâmetros básicos de conexão
    conn_params = f"DRIVER={{{driver}}};SERVER={server},{port};DATABASE={database};UID={user};PWD={password};"
    
    # Tratamento especial de segurança para o ODBC Driver 18 (exige confiar no certificado autoassinado padrão)
    if "ODBC Driver 18" in driver:
        conn_params += "TrustServerCertificate=yes;"
        
    return conn_params

def create_db_engine(server, database, user, password, port=1433):
    """Cria a engine do SQLAlchemy para conexões SQL Server."""
    conn_str = get_connection_string(server, database, user, password, port)
    params = urllib.parse.quote_plus(conn_str)
    connection_url = f"mssql+pyodbc:///?odbc_connect={params}"
    
    # Criar engine com Pool de conexões estável
    engine = create_engine(
        connection_url,
        pool_size=5,
        max_overflow=10,
        pool_recycle=1800,
        pool_pre_ping=True  # Valida se a conexão ainda está viva antes de usá-la
    )
    return engine

def get_session_factory(engine):
    """Cria a fábrica de sessões do SQLAlchemy."""
    return sessionmaker(bind=engine, expire_on_commit=False)

def initialize_database(server, database, user, password, port=1433) -> bool:
    """Tenta inicializar o banco de dados e cria as tabelas caso não existam."""
    try:
        engine = create_db_engine(server, database, user, password, port)
        Base.metadata.create_all(engine)
        logger.info("Banco de dados inicializado e sincronizado com sucesso!")
        return True
    except Exception as e:
        logger.error(f"Erro ao inicializar o banco de dados: {e}")
        return False
