# database/models.py
from datetime import datetime
from sqlalchemy import Column, Integer, String, Numeric, DateTime, ForeignKey, Text, Boolean, UniqueConstraint
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()

class AppConfig(Base):
    """
    Tabela de configurações locais persistentes do sistema,
    incluindo conexões SQL Server, limites e parâmetros do Playwright.
    """
    __tablename__ = 'SAT_Config'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    db_server = Column(String(100), default="127.0.0.1")
    db_database = Column(String(100), default="")
    db_user = Column(String(100), default="sa")
    db_password_encrypted = Column(Text, default="")
    db_port = Column(Integer, default=1433)
    download_folder = Column(String(255), default="")
    threads_count = Column(Integer, default=1)
    request_delay = Column(Numeric(5, 2), default=3.00)
    max_retries = Column(Integer, default=3)
    proxy_url = Column(String(255), nullable=True)
    timeout_seconds = Column(Integer, default=30)
    headless_mode = Column(Boolean, default=False)
    cert_name = Column(String(255), default="")  # Nome amigável do certificado selecionado

class Cfe(Base):
    """
    Cabeçalho principal do Cupom Fiscal Eletrônico (CF-e).
    Representa as informações gerais do documento.
    """
    __tablename__ = 'SAT_Cfe'
    
    chave = Column(String(44), primary_key=True)
    numero_cfe = Column(Integer, nullable=False, default=0)
    valor_total = Column(Numeric(10, 2), nullable=False, default=0.00)
    data_hora_emissao = Column(DateTime, nullable=False, default=datetime.utcnow)
    cnpj_emitente = Column(String(14), nullable=False, default="00000000000000")
    nome_emitente = Column(String(150), nullable=False, default="Emitente Desconhecido")
    inscricao_estadual = Column(String(20), nullable=True)
    uf_emitente = Column(String(2), default="SP")
    
    destinatario_documento = Column(String(14), nullable=True)  # CPF ou CNPJ
    destinatario_nome = Column(String(150), nullable=True)
    
    data_importacao = Column(DateTime, default=datetime.utcnow)
    caminho_xml = Column(String(255), nullable=True)
    
    # Relação um-para-muitos com os itens do cupom
    itens = relationship("CfeItem", back_populates="cfe", cascade="all, delete-orphan")

class CfeItem(Base):
    """
    Itens e produtos contidos no Cupom Fiscal Eletrônico (CF-e).
    Engloba todos os dados tributários e comerciais de cada produto.
    """
    __tablename__ = 'SAT_CfeItem'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    chave_cfe = Column(String(44), ForeignKey('SAT_Cfe.chave', ondelete='CASCADE'), nullable=False)
    numero_item = Column(Integer, nullable=False, default=0)
    codigo_produto = Column(String(255), nullable=False, default="N/A")
    descricao = Column(String(255), nullable=False, default="Produto não identificado")
    quantidade_comercial = Column(Numeric(12, 4), nullable=False, default=0.0)
    unidade_comercial = Column(String(255), nullable=False, default="UN")
    valor_unitario = Column(Numeric(12, 4), nullable=False, default=0.0)
    valor_bruto = Column(Numeric(12, 2), nullable=False, default=0.0)
    valor_liquido = Column(Numeric(12, 2), nullable=False, default=0.0)
    valor_desconto = Column(Numeric(12, 2), default=0.00)
    cfop = Column(String(255), nullable=False, default="0000")
    ncm = Column(String(255), nullable=True)
    cest = Column(String(255), nullable=True)
    gtin = Column(String(255), nullable=True)
    origem_mercadoria = Column(String(255), nullable=True)  # Texto descritivo da origem
    tributacao_icms = Column(String(255), nullable=True)  # CST ou CSOSN com descrição
    situacao_simples_nacional = Column(String(255), nullable=True)
    valor_icms = Column(Numeric(12, 2), default=0.00)
    observacoes_fisco = Column(Text, nullable=True)
    
    # Campos adicionais extraídos do portal SAT
    info_adicional = Column(Text, nullable=True)
    regra_calculo = Column(String(255), nullable=True)
    outras_despesas = Column(Numeric(12, 2), default=0.00)
    rateio_desconto = Column(Numeric(12, 2), default=0.00)
    rateio_acrescimo = Column(Numeric(12, 2), default=0.00)
    aliquota_efetiva = Column(Numeric(8, 4), default=0.00)
    
    # PIS
    pis_cst = Column(String(255), nullable=True)
    pis_base_calculo = Column(Numeric(12, 2), default=0.00)
    pis_aliquota = Column(Numeric(8, 4), default=0.00)
    pis_valor = Column(Numeric(12, 2), default=0.00)
    
    # COFINS
    cofins_cst = Column(String(255), nullable=True)
    cofins_base_calculo = Column(Numeric(12, 2), default=0.00)
    cofins_aliquota = Column(Numeric(8, 4), default=0.00)
    cofins_valor = Column(Numeric(12, 2), default=0.00)
    
    # Tributos aproximados
    valor_aproximado_tributos = Column(Numeric(12, 2), default=0.00)

    cfe = relationship("Cfe", back_populates="itens")
    
    # CORREÇÃO: Constraint UNIQUE para evitar duplicidade de itens
    __table_args__ = (
        UniqueConstraint('chave_cfe', 'numero_item', 'codigo_produto', name='uq_cfe_item_unique'),
    )

class QueueProgress(Base):
    """
    Mesa de controle e persistência de progresso para a fila do robô.
    Permite retomar a execução de onde ela parou caso o sistema feche ou caia.
    """
    __tablename__ = 'SAT_QueueProgress'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    cnpj = Column(String(14), nullable=False)
    periodo_inicio = Column(DateTime, nullable=False)
    periodo_fim = Column(DateTime, nullable=False)
    numero_serie_sat = Column(String(30), nullable=True)
    pagina_atual = Column(Integer, default=1)
    status = Column(String(20), default="PENDENTE")  # PENDENTE, EM_ANDAMENTO, CONCLUIDO, ERRO
    tentativas = Column(Integer, default=0)
    ultimo_erro = Column(Text, nullable=True)
    xmls_baixados = Column(Integer, default=0)
    data_atualizacao = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
