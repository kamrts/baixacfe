-- =========================================================================
-- SCRIPT DE CRIAÇÃO DAS TABELAS DO SAT XML DOWNLOADER (SQL SERVER)
-- =========================================================================

-- 1. Tabela de Configurações Técnicas
CREATE TABLE SAT_Config (
    id INT IDENTITY(1,1) PRIMARY KEY,
    db_server VARCHAR(100) DEFAULT '127.0.0.1',
    db_database VARCHAR(100) NOT NULL,
    db_user VARCHAR(100) DEFAULT 'sa',
    db_password_encrypted VARCHAR(MAX) NOT NULL,
    db_port INT DEFAULT 1433,
    download_folder VARCHAR(255) NULL,
    threads_count INT DEFAULT 1,
    request_delay NUMERIC(5,2) DEFAULT 3.00,
    max_retries INT DEFAULT 3,
    proxy_url VARCHAR(255) NULL,
    timeout_seconds INT DEFAULT 30,
    headless_mode BIT DEFAULT 0,
    cert_name VARCHAR(255) DEFAULT ''
);

-- 2. Tabela de Cabeçalho do CF-e (Cupom Fiscal Eletrônico)
CREATE TABLE SAT_Cfe (
    chave VARCHAR(44) PRIMARY KEY,
    numero_cfe INT NOT NULL,
    valor_total NUMERIC(12,2) NOT NULL,
    data_hora_emissao DATETIME NOT NULL,
    cnpj_emitente VARCHAR(14) NOT NULL,
    nome_emitente VARCHAR(150) NOT NULL,
    inscricao_estadual VARCHAR(20) NULL,
    uf_emitente VARCHAR(2) DEFAULT 'SP',
    destinatario_documento VARCHAR(14) NULL,
    destinatario_nome VARCHAR(150) NULL,
    data_importacao DATETIME DEFAULT GETDATE(),
    caminho_xml VARCHAR(255) NULL
);

-- 3. Tabela de Itens e Detalhes de Produtos do CF-e
CREATE TABLE SAT_CfeItem (
    id INT IDENTITY(1,1) PRIMARY KEY,
    chave_cfe VARCHAR(44) NOT NULL,
    numero_item INT NOT NULL,
    codigo_produto VARCHAR(60) NOT NULL,
    descricao VARCHAR(120) NOT NULL,
    quantidade_comercial NUMERIC(12,4) NOT NULL,
    unidade_comercial VARCHAR(10) NOT NULL,
    valor_unitario NUMERIC(12,4) NOT NULL,
    valor_bruto NUMERIC(12,2) NOT NULL,
    valor_liquido NUMERIC(12,2) NOT NULL,
    valor_desconto NUMERIC(12,2) DEFAULT 0.00,
    cfop VARCHAR(4) NOT NULL,
    ncm VARCHAR(8) NULL,
    cest VARCHAR(7) NULL,
    gtin VARCHAR(14) NULL,
    origem_mercadoria INT NULL,
    tributacao_icms VARCHAR(10) NULL,
    situacao_simples_nacional VARCHAR(10) NULL,
    valor_icms NUMERIC(12,2) DEFAULT 0.00,
    observacoes_fisco VARCHAR(MAX) NULL,
    CONSTRAINT FK_CfeItem_Cfe FOREIGN KEY (chave_cfe) 
        REFERENCES SAT_Cfe(chave) ON DELETE CASCADE
);

-- 4. Tabela de Fila e Progresso de Automação em Lote
CREATE TABLE SAT_QueueProgress (
    id INT IDENTITY(1,1) PRIMARY KEY,
    cnpj VARCHAR(14) NOT NULL,
    periodo_inicio DATETIME NOT NULL,
    periodo_fim DATETIME NOT NULL,
    numero_serie_sat VARCHAR(30) NULL,
    pagina_atual INT DEFAULT 1,
    status VARCHAR(20) DEFAULT 'PENDENTE', -- PENDENTE, EM_ANDAMENTO, CONCLUIDO, ERRO
    tentativas INT DEFAULT 0,
    ultimo_erro VARCHAR(MAX) NULL,
    xmls_baixados INT DEFAULT 0,
    data_atualizacao DATETIME DEFAULT GETDATE()
);
GO
