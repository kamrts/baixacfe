# Prompt Completo para Agente de IA — Sistema de Busca e Download de XML SAT em Lote

Crie uma aplicação desktop completa (Back-end + Front-end + empacotamento em `.EXE`) para automação de consultas e downloads de XML SAT no portal da SEFAZ/SP.

---

# Objetivo do Sistema

O sistema será um robô automatizado responsável por:

1. Acessar o portal SAT da SEFAZ/SP
2. Autenticar via certificado digital e-CNPJ
3. Alternar entre múltiplos CNPJs
4. Buscar XMLs SAT em lote
5. Baixar arquivos automaticamente
6. Fazer buscas isoladas por chave CF-e
7. Armazenar informações em banco SQL Server
8. Possuir interface amigável para operação manual
9. Gerar logs detalhados
10. Entregar aplicação final compilada em `.EXE`

---

# Portal Utilizado

Site oficial:

https://satsp.fazenda.sp.gov.br/COMSAT/Account/LoginSSL.aspx?ReturnUrl=%2fCOMSAT%2f

---

# Tecnologias Obrigatórias

## Back-end

Utilizar:

- Python 3.11+
- Playwright (preferencial) ou Selenium
- FastAPI ou Flask
- SQLAlchemy
- PyODBC
- Pandas
- OpenPyXL
- AsyncIO
- Logging estruturado

---

## Front-end Desktop

Utilizar:

- Electron + React
OU
- PySide6 / PyQt6

A interface deve ser moderna, responsiva e amigável.

---

## Banco de Dados

SQL Server

Conexão:

```env
DB_SERVER=127.0.0.1
DB_DATABASE={informado pelo usuário}
DB_USER=sa
DB_PASSWORD=Mrts@2025
DB_PORT=1433
```

---

## Empacotamento Final

Gerar executável `.EXE` instalável contendo:

- Front-end
- Back-end
- Navegador automatizado
- Dependências
- Configurações

Utilizar:

- PyInstaller
OU
- Electron Builder

---

# Funcionalidades Obrigatórias

# 1. Tela Inicial

Criar dashboard contendo:

- Status do robô
- Quantidade de XMLs baixados
- Quantidade de erros
- Última execução
- Tempo estimado
- Logs em tempo real

Botões:

- Iniciar busca em lote
- Iniciar busca isolada
- Parar execução
- Continuar execução
- Configurações

---

# 2. Configurações

Tela para:

- Informar banco SQL Server
- Selecionar certificado digital
- Pasta de download
- Quantidade de threads
- Tempo entre requisições
- Quantidade de tentativas
- Proxy opcional
- Timeout
- Headless ON/OFF

Salvar configurações localmente.

---

# 3. Fluxo — Busca em Lote de XML SAT

## Entrada

O usuário informará:

- Lista de CNPJs
- Data inicial
- Data final

IMPORTANTE:

O portal SAT não aceita períodos longos.

O sistema deve automaticamente quebrar o período em intervalos de 2 dias.

Exemplo:

```text
01/01 → 02/01
03/01 → 04/01
05/01 → 06/01
```

---

# Fluxo Completo

## PASSO 1 — Certificado

- Detectar certificados digitais instalados
- Permitir seleção do certificado
- Abrir navegador já autenticado

---

## PASSO 2 — Login

Acessar:

https://satsp.fazenda.sp.gov.br/COMSAT/Account/LoginSSL.aspx?ReturnUrl=%2fCOMSAT%2f

Executar:

- Entrar como contribuinte
- Acesso via e-CNPJ
- Selecionar certificado

Tratar:

- Timeout
- Sessão expirada
- Erro de certificado
- CAPTCHA eventual

---

## PASSO 3 — Alternar CNPJ

O sistema deverá:

- Receber lista de CNPJs
- Alternar automaticamente entre eles
- Confirmar troca antes de continuar

---

## PASSO 4 — Capturar Números de Série SAT

Navegação:

```text
Parametrização
→ Equipamento
→ Consultar Parâmetros Equipamento SAT
```

O sistema deverá:

- Percorrer todas as páginas
- Capturar TODOS os números de série SAT
- Armazenar temporariamente

---

## PASSO 5 — Buscar XMLs SAT

Navegação:

```text
Cupons
→ Consulta Lotes Enviados
```

Para cada número de série:

### Preencher:

- Número de Série
- Data Inicial
- Data Final

Horários fixos:

```text
Inicial: 00:00
Final: 23:59
```

---

## PASSO 6 — Download dos XMLs

O sistema deverá:

- Baixar TODOS os XMLs disponíveis
- Navegar automaticamente entre páginas
- Detectar fim das páginas
- Validar downloads
- Renomear arquivos automaticamente

Estrutura:

```text
/CNPJ/ANO/MES/DIA/
```

Nome do arquivo:

```text
CHAVE.xml
```

---

# TRATAMENTO ESPECIAL DE FALHAS DO PORTAL SAT

IMPORTANTE:

O portal SAT frequentemente retorna sozinho para a tela inicial durante o processo de download dos XMLs.

O sistema DEVE implementar um mecanismo robusto de recuperação automática.

## Regras obrigatórias:

### 1. Detectar retorno inesperado à tela inicial

O robô deverá identificar automaticamente quando:

- Saiu da tela de download
- Retornou ao dashboard inicial
- Perdeu contexto da busca
- Sessão foi parcialmente resetada
- O download não ocorreu

---

### 2. Validar se o XML foi realmente baixado

O sistema NÃO pode assumir sucesso apenas porque clicou no botão de download.

Deverá validar:

- Existência física do arquivo
- Tamanho do arquivo maior que zero
- XML válido
- Nome esperado
- Tempo de criação

---

### 3. Retomar automaticamente a operação

Caso detecte falha:

O robô deverá:

1. Voltar automaticamente ao menu correto
2. Reabrir:
   ```text
   Cupons → Consulta Lotes Enviados
   ```
3. Refazer os filtros
4. Reposicionar na página correta
5. Continuar do XML pendente
6. Repetir tentativa de download

---

### 4. Controle de itens pendentes

Criar fila interna contendo:

- XMLs pendentes
- XMLs baixados
- XMLs com erro
- Tentativas realizadas

---

### 5. Retry inteligente

Implementar:

- Retry automático
- Backoff exponencial
- Limite configurável de tentativas

Exemplo:

```text
Tentativa 1 → aguarda 3s
Tentativa 2 → aguarda 6s
Tentativa 3 → aguarda 12s
```

---

### 6. Persistência de execução

Se o sistema fechar inesperadamente:

Ao abrir novamente deverá:

- Ler progresso salvo
- Identificar último XML baixado
- Continuar exatamente do ponto anterior

---

### 7. Captura de evidências

Ao ocorrer erro:

Salvar automaticamente:

- Screenshot
- HTML da página
- Log detalhado
- URL atual
- CNPJ atual
- Série atual
- Página atual

---

### 8. Anti-loop infinito

Implementar proteção contra:

- Loop de redirecionamento
- Repetição infinita
- Sessão inválida
- Downloads travados

---

# 4. Fluxo — Busca Isolada de CF-e

## Entrada

Arquivo XLSX contendo:

- CNPJ
- Chave de acesso CF-e

Estrutura da chave:

| Campo | Tamanho |
|---|---|
| UF | 2 |
| AAMM Emissão | 4 |
| CNPJ | 14 |
| Modelo | 2 |
| Número Série | 9 |
| Número CFe | 6 |
| Código Aleatório | 6 |
| DV | 1 |

---

# Validações Obrigatórias

A aplicação deverá validar:

- Tamanho da chave
- Dígito verificador
- Duplicidade
- Formatação inválida
- CNPJ compatível com chave

---

# Fluxo Busca Isolada

## PASSO 1 — Login

Mesmo processo anterior.

---

## PASSO 2 — Consultar CF-e

Navegação:

```text
Cupons
→ Consultar CFe Sem Erros
```

---

## PASSO 3 — Buscar Chave

Adicionar:

- Chave de acesso

Clicar:

- Buscar

---

## PASSO 4 — Abrir Nota

Clicar sobre a chave encontrada.

---

## PASSO 5 — Extrair Dados

Na aba “CF-e”, salvar:

- Número
- Valor Total
- Data/Hora
- Chave
- Emitente
- Destinatário

---

## PASSO 6 — Produtos/Serviços

Extrair TODAS as informações exibidas:

- Código
- Descrição
- Quantidade
- Unidade
- Valor Unitário
- Valor Total
- CFOP
- CST
- NCM
- Impostos
- Descontos

Salvar no banco.

---

# 5. Banco de Dados

Criar automaticamente as tabelas.
Número do CF-e:
Valor Total do CF-e:
CNPJ:
Nome / Razão Social:
Inscrição Estadual:
UF:

Destinatario 
CPF / CNPJ
Nome / Razão Social:

Núm
Descrição
Qtd. Comercial
Unid. Comercial
Valor Líquido do Item
Cód. Produto
Cód. GTIN
Cód. NCM
Código Especificador da Substituição Tributária	
CFOP
Valor Unit.
Valor Bruto
Valor do Desconto
Observações Fisco
Origem da Mercadoria
Tributação do ICMS 
Cód. de Situação da Operação - Simples Nacional
Valor do ICMS

---

# 6. Logs

Criar logs completos:

```text
/logs/
```

Separados por:

- Data
- Execução
- Erros
- Downloads

Registrar:

- Tempo
- URL
- CNPJ
- Número Série
- Chave
- Erro completo

---

# 7. Segurança

Implementar:

- Criptografia local das configurações
- Proteção contra perda de sessão
- Sanitização de entradas
- Controle de concorrência

---

# 8. Performance

O sistema deverá:

- Trabalhar com filas
- Suportar milhares de XMLs
- Trabalhar em background
- Não travar interface

---

# 9. Interface

A interface deverá conter:

## Tela de Busca em Lote

Campos:

- Lista de CNPJs
- Data inicial
- Data final
- Pasta de saída

Tabela em tempo real:

- CNPJ atual
- Série atual
- XMLs baixados
- Status
- Tempo restante

---

## Tela Busca Isolada

Campos:

- Upload XLSX
- Pasta destino

Tabela:

- Chave
- Status
- Dados encontrados
- Erro

---

# 10. Tratamento de Erros

Implementar:

- Retry automático
- Timeout inteligente
- Reconexão
- Continuação após falhas
- Ignorar itens inválidos
- Relatório final

---

# 11. Relatórios

Gerar:

- Relatório Excel
- Relatório PDF
- Estatísticas da execução

---

# 12. Requisitos Técnicos Obrigatórios

O código deverá:

- Ser modular
- Ter arquitetura limpa
- Utilizar SOLID

Separar:

- automação
- banco
- interface
- serviços
- logs
- utilitários

Estrutura esperada:

```text
/app
/backend
/frontend
/database
/logs
/downloads
/config
```

---

# 13. Entrega Esperada

Entregar:

✅ Código fonte completo  
✅ Front-end completo  
✅ Back-end completo  
✅ Banco configurado  
✅ Script de criação das tabelas  
✅ Executável `.EXE`  
✅ Instalador  
✅ Manual de uso  
✅ Arquivo `.env.example`  
✅ Logs funcionando  
✅ Sistema pronto para produção  

---

# Regras Importantes

- O robô deve simular comportamento humano
- Deve respeitar tempos randômicos
- Não pode perder sessão facilmente
- Deve conseguir continuar execução após falha
- Toda automação deve ser resiliente
- Não utilizar seletores frágeis
- Implementar captura de screenshots em erro
- Implementar modo headless opcional

---

# Diferenciais Desejados

Se possível implementar:

- OCR para CAPTCHA
- Agendamento automático
- Multi-thread
- Atualização automática
- Painel administrativo
- API REST
- Docker opcional

---

# Resultado Esperado

Desejo um sistema profissional completo para automação de consultas SAT/SP com:

- Alta estabilidade
- Excelente performance
- Interface moderna
- Banco integrado
- Automação robusta
- Executável pronto para uso