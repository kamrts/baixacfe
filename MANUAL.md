# Manual do Usuário — SAT/SP XML Downloader

Bem-vindo ao **SAT/SP XML Downloader**, uma aplicação desktop completa e automatizada de alta estabilidade projetada especificamente para efetuar buscas e downloads em lote de cupons fiscais eletrônicos (CF-e) diretamente do portal SAT da SEFAZ/SP.

---

## 📋 1. Requisitos de Sistema

*   **Sistema Operacional:** Windows 10 ou 11 (64-bits).
*   **Banco de Dados:** Microsoft SQL Server (2016 ou superior).
*   **Certificado Digital:** Certificado Digital e-CNPJ (A1 em arquivo ou A3 em token físico/smartcard).
*   **Dependências Locais:** Google Chrome / Chromium instalado (o próprio instalador do robô pode baixar de forma embutida e isolada).

---

## 🛠️ 2. Instalação e Configuração Inicial

### PASSO 1: Configuração do Banco de Dados SQL Server
Antes de abrir a aplicação, você deve possuir uma base de dados no SQL Server.
1. Abra o **SQL Server Management Studio (SSMS)** ou ferramenta de preferência.
2. Crie um banco de dados de sua escolha (ex: `sat_xml_db`).
3. Execute as queries DDL contidas no arquivo [create_tables.sql](file:///d:/TRAMPOS/baixaDeXmls/database/create_tables.sql) para criar a estrutura relacional de tabelas de cabeçalho, itens e filas do robô.
   *(Nota: A aplicação também é capaz de criar estas tabelas de forma 100% automatizada no primeiro boot caso as credenciais estejam corretas)*.

### PASSO 2: Preparação do Ambiente Python e Dependências
Se estiver rodando a partir do código fonte:
1. Abra o terminal na pasta do projeto.
2. Crie o ambiente virtual e instale as dependências:
   ```bash
   python -m venv .venv
   .\.venv\Scripts\pip.exe install -r requirements.txt
   ```
3. Instale os navegadores de automação isolados do Playwright:
   ```bash
   .\.venv\Scripts\playwright.exe install chromium
   ```

### PASSO 3: Arquivo de Variáveis de Ambiente (.env)
Copie o arquivo `.env.example` para `.env` no diretório raiz e configure os parâmetros de conexão do banco:
```env
DB_SERVER=127.0.0.1
DB_DATABASE=sat_xml_db
DB_USER=sa
DB_PASSWORD=Mrts@2025
DB_PORT=1433
```

---

## 💻 3. Guia de Operação da Interface Desktop

Para iniciar a aplicação, execute:
```bash
.\.venv\Scripts\python.exe app.py
```

A interface abrirá em um **Dark Mode Premium** moderno e responsivo, dividido em 4 abas principais:

### 1. Painel de Controle (Dashboard)
*   **Cards de Status:** Exibe em tempo real o estado ativo/inativo do robô, quantidade de XMLs salvos, contagem de erros no lote e tempo estimado.
*   **Barra de Progresso:** Indica a evolução percentual da fila de trabalho.
*   **Console de Logs:** Área de terminal dedicada que imprime todas as ações internas do robô em tempo real (autenticações, alternância de CNPJs, andamento de downloads e retentativas).
*   **Controles de Execução:** Botões para iniciar, pausar ou parar a automação com segurança.

### 2. Busca em Lote
Aba utilizada para downloads massivos por CNPJ e período.
1. **Lista de CNPJs:** Cole ou digite os CNPJs que deseja buscar (um por linha). A aplicação limpa automaticamente pontuações.
2. **Data Inicial e Data Final:** Defina o período total da busca.
   *(Nota: O portal SAT aceita períodos muito curtos. O robô fatiará de forma automática o seu período longo em blocos consecutivos de no máximo 2 dias, tratando a fila de forma resiliente).*
3. **Pasta de Destino:** Selecione a pasta onde os XMLs validados serão salvos (padrão é `/downloads`).
4. **Tabela de Fila:** Exibe o progresso individual e status (Pendente, Em andamento, Concluído, Erro) de cada fatia de 2 dias por CNPJ.

### 3. Busca Isolada (XLSX)
Aba para buscar cupons SAT específicos a partir de uma planilha Excel.
1. **Planilha XLSX:** Selecione a planilha. Ela deve conter ao menos as colunas **Chave** (Chave de acesso CF-e de 44 dígitos) e **CNPJ** (opcional, para dupla validação).
2. O sistema pré-validará matematicamente as chaves (validando o tamanho, máscara e algoritmo de Dígito Verificador Módulo 11) antes de acionar a automação.
3. **Grade de Resultados:** Lista as chaves, status de validação inicial e o resultado da raspagem. O robô acessará a nota sem erros, abrirá as abas de produtos e extrairá todas as alíquotas de impostos, NCM, CFOP, CEST e detalhes salvando-os de forma relacional no SQL Server.

### 4. Configurações Técnicas
Formulário técnico para parametrizar o robô localmente:
*   **Banco de Dados:** Host, nome do banco, usuário, senha e porta do SQL Server. A senha é salva localmente sob criptografia AES de alta segurança.
*   **Certificado Digital:** O sistema consulta nativamente a CryptoAPI do Windows e exibe os certificados e-CNPJ instalados. Escolha o seu ou utilize a autoseleção recomendada do portal.
*   **Modo de Execução:**
    *   *Visível (Recomendado):* Abre a janela do navegador Playwright visível durante a etapa de login para que você possa digitar o PIN do certificado A3 físico ou resolver CAPTCHAs eventuais da SEFAZ. Uma vez logado, a automação prossegue sozinha.
    *   *Oculto (Headless):* Execução silenciosa em background (indicado para certificados A1).
*   **Delays e Tentativas:** Configure segundos de espera entre requisições (comportamento humano) e limites de retentativas.

---

## 🛡️ 4. Resiliência e Recuperação Automática de Falhas

O portal SAT da SEFAZ/SP é notoriamente instável e costuma deslogar usuários ou ejetá-los de volta para a tela inicial durante processamentos em lote. 

Nosso robô possui **mecanismos de auto-recuperação integrados**:
1. **Detecção Dinâmica de Desvio:** Antes de clicar em qualquer download ou paginação, o robô valida se a URL ativa pertence à área de cupons.
2. **Recuperação e Reposicionamento:** Se detectar ejeção para a Home, o robô captura um screenshot e HTML de evidência (salvos em `/logs/evidencias/`), restabelece o login por certificado digital, re-seleciona o CNPJ, insere novamente os filtros originais de busca e avança até a página e index onde o download havia parado.
3. **Validação Física do Arquivo:** O robô não assume sucesso pelo clique. Ele monitora a pasta temporária de downloads, aguarda o fim do download de rede, valida se o arquivo no disco possui tamanho maior que zero bytes e valida a tag raiz `<CFe>` no arquivo para garantir que a SEFAZ não entregou uma página HTML de erro envelopada.
4. **Fila Persistente:** Se a aplicação for fechada inesperadamente ou ocorrer queda total de energia, ao reabrir, o State Manager lerá o progresso do banco SQL Server e reiniciará os downloads pendentes exatamente do bloco e página onde ocorreu a interrupção.

---

## 📦 5. Compilação do Executável (.EXE)

Para empacotar a aplicação em um arquivo `.EXE` instalável autônomo (Single-File GUI) contendo todas as dependências em Python e PySide6:

Execute o script compilador:
```bash
.\.venv\Scripts\python.exe build_exe.py
`` em a

O PyInstaller efetuará a análise estrutural da base de código e gerará o executável final em:
`dist/SAT_XML_Downloader.exe`

Este executável é portátil e pode ser distribuído para máquinas Windows sem a necessidade de possuir o Python ou bibliotecas previamente instalados.
