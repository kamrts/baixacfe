# backend/state_manager.py
import logging
from datetime import datetime, timedelta
from typing import List, Tuple, Optional
from sqlalchemy.orm import Session
from database.models import QueueProgress, Cfe, CfeItem, AppConfig
from config.settings import CryptoHelper

logger = logging.getLogger("SAT_Downloader")

class StateManager:
    """
    Gerenciador de Estados e Fila de Processamento do Robô.
    Lida com o fatiamento de datas, salvamento de progresso e persistência no banco.
    """
    
    @staticmethod
    def split_date_range(start_date: datetime, end_date: datetime, max_days: int = 2) -> List[Tuple[datetime, datetime]]:
        """
        Divide um período longo de datas em intervalos consecutivos de no máximo N dias.
        Garante conformidade com o limite de consultas do portal da SEFAZ/SP.
        """
        intervals = []
        current_start = start_date
        
        while current_start <= end_date:
            current_end = current_start + timedelta(days=max_days - 1)
            # Definir o horário final para 23:59:59
            current_end = current_end.replace(hour=23, minute=59, second=59, microsecond=999999)
            
            if current_end >= end_date:
                intervals.append((current_start, end_date))
                break
                
            intervals.append((current_start, current_end))
            current_start = current_end + timedelta(microseconds=1)
            # Definir o horário inicial para 00:00:00
            current_start = current_start.replace(hour=0, minute=0, second=0, microsecond=0)
            
        return intervals

    @classmethod
    def populate_queue(cls, session: Session, cnpjs: List[str], start_date: datetime, end_date: datetime) -> int:
        """
        Gera os blocos de períodos de 2 dias e popula a tabela de fila (SAT_QueueProgress)
        para todos os CNPJs fornecidos. Ignora blocos que já existam exatamente na fila.
        """
        intervals = cls.split_date_range(start_date, end_date, max_days=2)
        added_count = 0
        
        logger.info(f"[DEBUG] populate_queue chamado com {len(cnpjs)} CNPJs e {len(intervals)} intervalos de data")
        logger.info(f"[DEBUG] Período: {start_date.strftime('%d/%m/%Y')} a {end_date.strftime('%d/%m/%Y')}")
        
        for cnpj in cnpjs:
            cnpj_clean = "".join(filter(str.isdigit, cnpj))
            if not cnpj_clean:
                logger.warning(f"[DEBUG] CNPJ inválido ignorado: {cnpj}")
                continue
            
            logger.info(f"[DEBUG] Processando CNPJ: {cnpj_clean}")
            
            for start, end in intervals:
                # Verificar duplicidade exata
                exists = session.query(QueueProgress).filter(
                    QueueProgress.cnpj == cnpj_clean,
                    QueueProgress.periodo_inicio == start,
                    QueueProgress.periodo_fim == end
                ).first()
                
                if not exists:
                    job = QueueProgress(
                        cnpj=cnpj_clean,
                        periodo_inicio=start,
                        periodo_fim=end,
                        status="PENDENTE"
                    )
                    session.add(job)
                    added_count += 1
                    logger.info(f"[DEBUG] Job criado: CNPJ={cnpj_clean}, Período={start.strftime('%d/%m')} a {end.strftime('%d/%m')}")
                else:
                    logger.info(f"[DEBUG] Job já existe (status={exists.status}): CNPJ={cnpj_clean}, Período={start.strftime('%d/%m')} a {end.strftime('%d/%m')}")
                    # Se o job existente está CONCLUIDO, resetar para PENDENTE para reprocessar
                    if exists.status == "CONCLUIDO":
                        exists.status = "PENDENTE"
                        exists.tentativas = 0
                        exists.pagina_atual = 1
                        exists.xmls_baixados = 0
                        logger.info(f"[DEBUG] Job resetado para PENDENTE: ID={exists.id}")
                        added_count += 1
        
        session.commit()
        logger.info(f"Fila populada com {added_count} novos/resetados blocos de consulta SAT.")
        return added_count

    @staticmethod
    def get_next_job(session: Session) -> Optional[QueueProgress]:
        """Busca o próximo trabalho na fila (PENDENTE ou com erro com menos de 3 tentativas)."""
        # Debug: Verificar quantos jobs existem em cada status
        pendentes = session.query(QueueProgress).filter(QueueProgress.status == "PENDENTE").count()
        em_andamento = session.query(QueueProgress).filter(QueueProgress.status == "EM_ANDAMENTO").count()
        concluidos = session.query(QueueProgress).filter(QueueProgress.status == "CONCLUIDO").count()
        erros = session.query(QueueProgress).filter(QueueProgress.status == "ERRO").count()
        logger.info(f"[DEBUG] Estado da fila: PENDENTE={pendentes}, EM_ANDAMENTO={em_andamento}, CONCLUIDO={concluidos}, ERRO={erros}")
        
        # Priorizar PENDENTE, depois tentar os com ERRO que não estouraram tentativas
        job = session.query(QueueProgress).filter(
            QueueProgress.status == "PENDENTE"
        ).order_by(QueueProgress.periodo_inicio.asc()).first()
        
        if not job:
            job = session.query(QueueProgress).filter(
                QueueProgress.status == "ERRO",
                QueueProgress.tentativas < 3
            ).order_by(QueueProgress.data_atualizacao.asc()).first()
            
        if job:
            job.status = "EM_ANDAMENTO"
            job.data_atualizacao = datetime.utcnow()
            session.commit()
            
        return job

    @staticmethod
    def update_job_status(session: Session, job_id: int, status: str, error_msg: Optional[str] = None, xmls_count: int = 0):
        """Atualiza o status de um bloco na fila com logs apropriados."""
        job = session.query(QueueProgress).filter(QueueProgress.id == job_id).first()
        if job:
            job.status = status
            job.xmls_baixados = xmls_count
            if status == "ERRO":
                job.tentativas += 1
                job.ultimo_erro = error_msg
            elif status == "CONCLUIDO":
                job.ultimo_erro = None
            job.data_atualizacao = datetime.utcnow()
            session.commit()
            logger.info(f"Fila ID {job_id} ({job.cnpj}) atualizada para {status}.")

    @staticmethod
    def check_cfe_exists(session: Session, key: str) -> bool:
        """Verifica se a chave CF-e já existe no banco de dados para evitar downloads repetidos."""
        return session.query(Cfe).filter(Cfe.chave == key).count() > 0

    @staticmethod
    def save_cfe_to_db(session: Session, cfe_data: dict, items_data: List[dict]) -> bool:
        """
        Salva o cabeçalho do cupom fiscal e todos os seus itens no banco SQL Server.
        Utiliza UPSERT com base na chave principal.
        """
        try:
            # Log detalhado para debug
            logger.info(f"[DEBUG] Salvando CF-e: chave={cfe_data.get('chave')}, numero={cfe_data.get('numero_cfe')}, valor={cfe_data.get('valor_total')}")
            
            # 1. Verificar se já existe
            cfe = session.query(Cfe).filter(Cfe.chave == cfe_data["chave"]).first()
            
            if not cfe:
                # Criar nova nota
                cfe = Cfe(**cfe_data)
                session.add(cfe)
            else:
                # Atualizar dados existentes (UPSERT)
                for key, val in cfe_data.items():
                    setattr(cfe, key, val)
                # Deletar itens anteriores para recarga limpa
                session.query(CfeItem).filter(CfeItem.chave_cfe == cfe.chave).delete()
                
            session.flush() # Sincroniza estado para obter foreign key se necessário
            
            # 2. Inserir itens
            for item in items_data:
                item["chave_cfe"] = cfe.chave
                cfe_item = CfeItem(**item)
                session.add(cfe_item)
                
            session.commit()
            logger.info(f"[DEBUG] CF-e {cfe_data.get('chave')} salvo com sucesso com {len(items_data)} itens")
            return True
        except Exception as e:
            session.rollback()
            logger.error(f"Erro ao salvar CF-e {cfe_data.get('chave')} no banco: {type(e).__name__}: {e}")
            logger.error(f"[DEBUG] Dados CFe que falharam: {cfe_data}")
            return False

    @staticmethod
    def get_or_create_config(session: Session) -> AppConfig:
        """Carrega a configuração global única ou cria uma vazia caso não exista."""
        cfg = session.query(AppConfig).order_by(AppConfig.id.asc()).first()
        if not cfg:
            cfg = AppConfig()
            session.add(cfg)
            session.commit()
        return cfg

    @classmethod
    def save_config(cls, session: Session, data: dict) -> bool:
        """Salva as configurações do sistema localmente de forma criptografada."""
        try:
            cfg = cls.get_or_create_config(session)
            
            # Criptografar senha do banco caso seja fornecida
            if "db_password" in data:
                raw_pwd = data.pop("db_password")
                data["db_password_encrypted"] = CryptoHelper.encrypt(raw_pwd)
                
            for key, val in data.items():
                if hasattr(cfg, key):
                    setattr(cfg, key, val)
                    
            session.commit()
            return True
        except Exception as e:
            session.rollback()
            logger.error(f"Erro ao salvar configurações do app: {e}")
            return False

    @classmethod
    def get_decrypted_db_password(cls, session: Session) -> str:
        """Recupera a senha do banco de dados descriptografada."""
        cfg = cls.get_or_create_config(session)
        return CryptoHelper.decrypt(cfg.db_password_encrypted)
