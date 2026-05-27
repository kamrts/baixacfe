# backend/sat_bot_isolated.py
import re
import asyncio
import logging
import pandas as pd
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Callable, Tuple, Optional
from playwright.async_api import async_playwright, Page

from backend.state_manager import StateManager
from backend.sat_bot import SATBot

logger = logging.getLogger("SAT_Downloader")

class SATBotIsolated:
    """
    Robô responsável pela Busca Isolada de CF-e por Chaves de Acesso (Via XLSX).
    Efetua validação matemática de chaves e raspagem avançada de dados de produtos/tributos.
    """
    
    def __init__(self, db_session_factory: Callable[[], Any], config: Dict[str, Any]):
        self.session_factory = db_session_factory
        self.config = config
        self.bot_core = SATBot(db_session_factory, config) # Compartilha lógica básica
        self.is_running = False
        
        # Callbacks
        self.on_log: Optional[Callable[[str], None]] = None
        self.on_progress: Optional[Callable[[Dict[str, Any]], None]] = None

    def log(self, message: str, level: int = logging.INFO):
        logger.log(level, message)
        if self.on_log:
            prefix = "[INFO]"
            if level == logging.WARNING:
                prefix = "[AVISO]"
            elif level == logging.ERROR:
                prefix = "[ERRO]"
            self.on_log(f"{datetime.now().strftime('%H:%M:%S')} {prefix} {message}")

    @staticmethod
    def validar_chave_sat(chave: str, cnpj_esperado: Optional[str] = None) -> Tuple[bool, str]:
        """
        Valida matematicamente a Chave de Acesso do SAT:
        - Verifica se possui exatamente 44 dígitos numéricos.
        - Valida se o CNPJ embutido na chave corresponde ao CNPJ esperado (se fornecido).
        - Executa o cálculo de validação do Dígito Verificador (Módulo 11).
        """
        chave = re.sub(r"\D", "", chave)
        if len(chave) != 44:
            return False, "Chave de acesso deve conter exatamente 44 dígitos numéricos."
            
        # Validar CNPJ embutido (Posições 7 a 20 da chave)
        cnpj_chave = chave[6:20]
        if cnpj_esperado:
            cnpj_clean = "".join(filter(str.isdigit, cnpj_esperado))
            if cnpj_clean and cnpj_chave != cnpj_clean:
                return False, f"CNPJ da chave ({cnpj_chave}) difere do CNPJ informado ({cnpj_clean})."
                
        # Modelo do SAT deve ser 59 (NF-e é 55, SAT é 59)
        modelo = chave[20:22]
        if modelo != "59":
            return False, f"Modelo de documento inválido para SAT ({modelo}). Deve ser '59'."
            
        # Validação do Dígito Verificador (Mod 11)
        # Multiplicadores da direita para a esquerda: 2, 3, 4, 5, 6, 7, 8, 9, depois repete 2...
        soma = 0
        peso = 2
        for i in range(42, -1, -1):
            soma += int(chave[i]) * peso
            peso = 2 if peso == 9 else peso + 1
            
        resto = soma % 11
        dv_calculado = 0 if resto in (0, 1) else 11 - resto
        
        dv_original = int(chave[43])
        if dv_calculado != dv_original:
            return False, f"Dígito verificador inválido. Calculado: {dv_calculado}, Original: {dv_original}"
            
        return True, "Chave de acesso válida."

    URL_CONSULTA_CFE = "https://satsp.fazenda.sp.gov.br/COMSAT/Private/ConsultaCfeSemErros/ConsultarCfeSemErro.aspx"

    async def navegar_para_consulta_individual(self, page: Page) -> bool:
        """Acessa diretamente a página de consulta CF-e por URL, com fallback via menu."""
        try:
            # Acesso direto por URL — mais confiável que navegação por menu hover
            if page.url != self.URL_CONSULTA_CFE:
                self.log("Navegando para Consulta CF-e Sem Erros...")
                await page.goto(self.URL_CONSULTA_CFE)
                await page.wait_for_load_state("networkidle")

            # Verificar se chegou na página correta
            if "ConsultarCfeSemErro" in page.url:
                self.log("Página de consulta CF-e carregada com sucesso.")
                return True

            # Fallback: navegação via menu hover caso a URL redirecione
            self.log("URL direta redirecionada. Tentando navegação via menu...", logging.WARNING)
            await page.locator("a:has-text('Cupons')").hover()
            await asyncio.sleep(0.5)
            await page.locator("a:has-text('Consultar CFe Sem Erros')").click()
            await page.wait_for_load_state("networkidle")
            return True
        except Exception as e:
            self.log(f"Erro ao navegar para consulta individual de CF-e: {e}", logging.ERROR)
            return False

    async def consultar_chave(self, page: Page, chave: str) -> bool:
        """Digita a chave de acesso, realiza a pesquisa e abre a nota detalhada."""
        try:
            txt_chave = page.locator("input[id*='txtChaveAcesso'], input[id*='txtChave']")
            await txt_chave.first.fill(chave)
            
            btn_pesquisar = page.locator("input[id*='btnPesquisar'], input[id*='btnConsultar']")
            await btn_pesquisar.click()
            await page.wait_for_load_state("networkidle")
            await asyncio.sleep(1)
            
            # Verificar se encontrou erro de "Nenhum registro"
            if await page.locator("text=Nenhum registro encontrado, Nenhum documento").count() > 0:
                self.log(f"Chave {chave} não encontrada no portal SAT/SP.", logging.WARNING)
                return False
                
            # Clicar na chave encontrada (geralmente é o primeiro link na gridview contendo o texto da chave)
            link_nota = page.locator(f"a:has-text('{chave}'), a[id*='lnkChaveAcesso']").first
            if await link_nota.count() > 0:
                await link_nota.click()
                await page.wait_for_load_state("networkidle")
                await asyncio.sleep(2)
                return True
            else:
                self.log(f"Link da nota com chave {chave} não encontrado na listagem.", logging.ERROR)
                return False
        except Exception as e:
            self.log(f"Erro ao consultar chave {chave}: {e}", logging.ERROR)
            return False

    async def _extrair_texto_seguro(self, page: Page, seletor: str, chave: str, campo_nome: str) -> Optional[str]:
        """
        Extrai texto de um elemento de forma segura, validando existência antes de usar inner_text().
        Utiliza wait_for_selector com timeout de 60000ms e captura evidências em caso de erro.
        """
        try:
            await page.wait_for_selector(seletor, timeout=60000)
            locator = page.locator(seletor).first
            if await locator.count() > 0:
                return await locator.inner_text(timeout=60000)
            else:
                self.log(f"{campo_nome} não encontrado para chave {chave}", logging.WARNING)
                return None
        except Exception as e:
            self.log(f"Timeout/Erro ao extrair {campo_nome} para chave {chave}: {e}", logging.WARNING)
            return None

    async def raspar_dados_detalhados(self, page: Page, chave: str) -> Tuple[Optional[Dict[str, Any]], List[Dict[str, Any]]]:
        """
        Efetua a raspagem completa de dados do cupom fiscal.
        Navega pelas abas internas (CF-e e Produtos/Serviços) e coleta cabeçalho e todos os itens.
        """
        cfe_data = {}
        itens_data = []
        
        try:
            # 1. PASSO 5 — Extração de Dados da Aba "CF-e" (Cabeçalho)
            # Garantir clique na aba de cabeçalho (geralmente a aba selecionada por padrão)
            tab_cfe = page.locator("a:has-text('CF-e'), a[id*='tabCFe']").first
            if await tab_cfe.count() > 0:
                await tab_cfe.click()
                await asyncio.sleep(0.5)
                
            # Mapear e extrair dados usando seletores semânticos resilientes
            cfe_data["chave"] = chave
            
            # CORREÇÃO 1 — Número do CF-e com validação e timeout aumentado
            seletor_numero = "span[id*='lblNumeroCFe'], td:has-text('Número do CF-e') + td"
            try:
                await page.wait_for_selector(seletor_numero, timeout=60000)
                locator_numero = page.locator(seletor_numero).first
                if await locator_numero.count() > 0:
                    num_text = await locator_numero.inner_text(timeout=60000)
                    cfe_data["numero_cfe"] = int(re.sub(r"\D", "", num_text)) if num_text else 0
                else:
                    self.log(f"Número CF-e não encontrado: {chave}", logging.WARNING)
                    cfe_data["numero_cfe"] = 0
            except Exception as e:
                self.log(f"Timeout ao extrair Número CF-e para {chave}: {e}", logging.WARNING)
                # Capturar evidências de erro
                evidences_dir = Path(__file__).resolve().parent.parent / "logs" / "evidencias"
                evidences_dir.mkdir(parents=True, exist_ok=True)
                await page.screenshot(path=str(evidences_dir / f"erro_{chave}.png"))
                html = await page.content()
                with open(str(evidences_dir / f"erro_{chave}.html"), "w", encoding="utf-8") as f:
                    f.write(html)
                cfe_data["numero_cfe"] = 0
            
            # CORREÇÃO 2 — Captura dos campos principais com validação
            # Valor Total do CF-e
            val_text = await self._extrair_texto_seguro(
                page, 
                "span[id*='lblValorTotalCFe'], td:has-text('Valor Total do CF-e') + td", 
                chave, 
                "Valor Total do CF-e"
            )
            if val_text:
                val_clean = val_text.replace("R$", "").replace(".", "").replace(",", ".").strip()
                cfe_data["valor_total"] = float(val_clean) if val_clean else 0.00
            else:
                cfe_data["valor_total"] = 0.00
            
            # Data/Hora Emissão (ex: 27/05/2026 15:30:22)
            datetime_text = await self._extrair_texto_seguro(
                page,
                "span[id*='lblDataHoraEmissao'], td:has-text('Data/Hora de Emissão') + td",
                chave,
                "Data/Hora de Emissão"
            )
            if datetime_text:
                try:
                    cfe_data["data_hora_emissao"] = datetime.strptime(datetime_text.strip(), "%d/%m/%Y %H:%M:%S")
                except ValueError:
                    cfe_data["data_hora_emissao"] = datetime.now()
            else:
                cfe_data["data_hora_emissao"] = datetime.now()
                
            # Emitente CNPJ
            emit_cnpj_text = await self._extrair_texto_seguro(
                page,
                "span[id*='lblCnpjEmitente'], span[id*='lblCnpj'], td:has-text('CNPJ') + td",
                chave,
                "CNPJ"
            )
            cfe_data["cnpj_emitente"] = re.sub(r"\D", "", emit_cnpj_text) if emit_cnpj_text else chave[6:20]
            
            # Nome / Razão Social do Emitente
            emit_nome_text = await self._extrair_texto_seguro(
                page,
                "span[id*='lblRazaoSocialEmitente'], span[id*='lblRazaoSocial'], td:has-text('Nome / Razão Social') + td, td:has-text('Razão Social') + td",
                chave,
                "Nome / Razão Social"
            )
            cfe_data["nome_emitente"] = emit_nome_text.strip() if emit_nome_text else "Emitente Desconhecido"
            
            # Inscrição Estadual
            emit_ie_text = await self._extrair_texto_seguro(
                page,
                "span[id*='lblIeEmitente'], span[id*='lblInscricaoEstadual'], td:has-text('Inscrição Estadual') + td",
                chave,
                "Inscrição Estadual"
            )
            cfe_data["inscricao_estadual"] = re.sub(r"\D", "", emit_ie_text) if emit_ie_text else None
            
            # UF
            uf_text = await self._extrair_texto_seguro(
                page,
                "span[id*='lblUf'], span[id*='lblUF'], td:has-text('UF') + td",
                chave,
                "UF"
            )
            cfe_data["uf_emitente"] = uf_text.strip() if uf_text else "SP"
            
            # Destinatário CPF / CNPJ
            dest_doc_text = await self._extrair_texto_seguro(
                page,
                "span[id*='lblCnpjCpfDestinatario'], span[id*='lblCpfCnpjDestinatario'], td:has-text('CPF / CNPJ') + td",
                chave,
                "CPF / CNPJ Destinatário"
            )
            cfe_data["destinatario_documento"] = re.sub(r"\D", "", dest_doc_text) if dest_doc_text else None
            
            # Destinatário Nome / Razão Social
            dest_nome_text = await self._extrair_texto_seguro(
                page,
                "span[id*='lblRazaoSocialDestinatario'], span[id*='lblNomeDestinatario'], td:has-text('Destinatário') + td",
                chave,
                "Nome / Razão Social Destinatário"
            )
            cfe_data["destinatario_nome"] = dest_nome_text.strip() if dest_nome_text else None
            
            # CORREÇÃO 3 — Clicar obrigatoriamente na aba Produtos/Serviços
            # Usar seletor específico do input type="submit" conforme HTML fornecido
            seletor_aba_produtos = "#conteudo_tabProdutoServico, input[id*='tabProdutoServico'], input[value*='Produtos'], a:has-text('Produtos'), a[id*='tabProdutos'], a:has-text('Serviços')"
            
            try:
                await page.wait_for_selector(seletor_aba_produtos, timeout=60000)
                tab_produtos = page.locator(seletor_aba_produtos).first
                if await tab_produtos.count() > 0:
                    await tab_produtos.click()
                    self.log(f"Aba Produtos/Serviços clicada com sucesso para chave {chave}")
                    # Aguardar carregamento após clique
                    await page.wait_for_timeout(3000)
                    await page.wait_for_load_state("networkidle")
                else:
                    self.log(f"Aba Produtos/Serviços não encontrada para chave {chave}", logging.WARNING)
            except Exception as e:
                self.log(f"Erro ao clicar na aba Produtos/Serviços para {chave}: {e}", logging.WARNING)
                # Capturar evidências
                evidences_dir = Path(__file__).resolve().parent.parent / "logs" / "evidencias"
                evidences_dir.mkdir(parents=True, exist_ok=True)
                await page.screenshot(path=str(evidences_dir / f"erro_aba_produtos_{chave}.png"))
                html = await page.content()
                with open(str(evidences_dir / f"erro_aba_produtos_{chave}.html"), "w", encoding="utf-8") as f:
                    f.write(html)
                
            # Localizar tabela de produtos (geralmente uma tabela de id grvProdutos ou table)
            linhas_prod = await page.locator("table[id*='grvProdutos'] tr, table[id*='gridProdutos'] tr, table[id*='Produtos'] tr").all()
            
            if not linhas_prod:
                self.log(f"Tabela de produtos vazia ou não encontrada para a chave {chave}.", logging.WARNING)
                return cfe_data, []
            
            # CORREÇÃO 4 — Capturar TODOS os campos de produtos/serviços
            # Obter cabeçalhos da tabela para mapeamento dinâmico
            header_row = await page.locator("table[id*='grvProdutos'] tr:first-child th, table[id*='gridProdutos'] tr:first-child th, table[id*='Produtos'] tr:first-child th").all_inner_texts()
            
            # Mapeamento de nomes de colunas para índices
            col_map = {}
            for idx_h, header in enumerate(header_row):
                header_lower = header.strip().lower()
                if "núm" in header_lower or "num" in header_lower:
                    col_map["numero_item"] = idx_h
                elif "descrição" in header_lower or "descricao" in header_lower:
                    col_map["descricao"] = idx_h
                elif "qtd" in header_lower and "comercial" in header_lower:
                    col_map["quantidade_comercial"] = idx_h
                elif "unid" in header_lower and "comercial" in header_lower:
                    col_map["unidade_comercial"] = idx_h
                elif "valor líquido" in header_lower or "valor liquido" in header_lower:
                    col_map["valor_liquido"] = idx_h
                elif "cód. produto" in header_lower or "cod. produto" in header_lower or "código produto" in header_lower:
                    col_map["codigo_produto"] = idx_h
                elif "gtin" in header_lower:
                    col_map["gtin"] = idx_h
                elif "ncm" in header_lower:
                    col_map["ncm"] = idx_h
                elif "cest" in header_lower or "especificador" in header_lower:
                    col_map["cest"] = idx_h
                elif "cfop" in header_lower:
                    col_map["cfop"] = idx_h
                elif "valor unit" in header_lower:
                    col_map["valor_unitario"] = idx_h
                elif "valor bruto" in header_lower:
                    col_map["valor_bruto"] = idx_h
                elif "desconto" in header_lower:
                    col_map["valor_desconto"] = idx_h
                elif "observ" in header_lower and "fisco" in header_lower:
                    col_map["observacoes_fisco"] = idx_h
                elif "origem" in header_lower and "mercadoria" in header_lower:
                    col_map["origem_mercadoria"] = idx_h
                elif "tributação" in header_lower or "tributacao" in header_lower:
                    col_map["tributacao_icms"] = idx_h
                elif "simples nacional" in header_lower or "situação" in header_lower:
                    col_map["situacao_simples_nacional"] = idx_h
                elif "valor" in header_lower and "icms" in header_lower:
                    col_map["valor_icms"] = idx_h
                
            # Processar linhas da tabela (Ignorando cabeçalho)
            for idx, linha in enumerate(linhas_prod[1:]):
                colunas = await linha.locator("td").all_inner_texts()
                if len(colunas) < 4:
                    continue
                
                # Função auxiliar para extrair valor de coluna de forma segura
                def get_col(nome_col: str, default: any = None) -> any:
                    if nome_col in col_map and col_map[nome_col] < len(colunas):
                        return colunas[col_map[nome_col]].strip()
                    return default
                
                def parse_float(valor: str) -> float:
                    if not valor:
                        return 0.00
                    try:
                        return float(valor.replace(".", "").replace(",", ".").strip())
                    except ValueError:
                        return 0.00
                
                def parse_int(valor: str) -> int:
                    if not valor:
                        return 0
                    try:
                        return int(re.sub(r"\D", "", valor))
                    except ValueError:
                        return 0
                    
                # Extração posicional ou baseada em cabeçalhos (Mapeamento de colunas do SAT SP)
                # CORREÇÃO 4 — Capturar TODOS os campos solicitados
                item = {
                    # Campos obrigatórios
                    "numero_item": parse_int(get_col("numero_item")) or idx + 1,
                    "descricao": get_col("descricao", colunas[1] if len(colunas) > 1 else ""),
                    "quantidade_comercial": parse_float(get_col("quantidade_comercial", colunas[2] if len(colunas) > 2 else "0")),
                    "unidade_comercial": get_col("unidade_comercial", colunas[3] if len(colunas) > 3 else "UN"),
                    "valor_liquido": parse_float(get_col("valor_liquido", colunas[4] if len(colunas) > 4 else "0")),
                    "codigo_produto": get_col("codigo_produto", colunas[5] if len(colunas) > 5 else ""),
                    # Campos adicionais solicitados na CORREÇÃO 4
                    "gtin": get_col("gtin", None),
                    "ncm": get_col("ncm", None),
                    "cest": get_col("cest", None),
                    "cfop": get_col("cfop", "5929"),
                    "valor_unitario": parse_float(get_col("valor_unitario", colunas[6] if len(colunas) > 6 else "0")),
                    "valor_bruto": parse_float(get_col("valor_bruto", colunas[7] if len(colunas) > 7 else "0")),
                    "valor_desconto": parse_float(get_col("valor_desconto", "0")),
                    "observacoes_fisco": get_col("observacoes_fisco", None),
                    "origem_mercadoria": parse_int(get_col("origem_mercadoria", "0")),
                    "tributacao_icms": get_col("tributacao_icms", "102"),
                    "situacao_simples_nacional": get_col("situacao_simples_nacional", "102"),
                    "valor_icms": parse_float(get_col("valor_icms", "0")),
                }
                
                # Fallback para extração posicional se mapeamento dinâmico não encontrou todos os campos
                if len(colunas) >= 12 and not item["cfop"]:
                    item["cfop"] = colunas[8].strip() if colunas[8] else "5929"
                    item["ncm"] = colunas[9].strip() if len(colunas) > 9 and colunas[9] else None
                    item["cest"] = colunas[10].strip() if len(colunas) > 10 and colunas[10] else None
                    item["gtin"] = colunas[11].strip() if len(colunas) > 11 and colunas[11] else None
                if len(colunas) >= 15 and item["valor_icms"] == 0.00:
                    item["valor_icms"] = parse_float(colunas[14]) if colunas[14] else 0.00
                    
                itens_data.append(item)
                
            self.log(f"Chave {chave} raspada com sucesso. Encontrados {len(itens_data)} itens de produto.")
            return cfe_data, itens_data
            
        except Exception as e:
            self.log(f"Erro ao raspar dados da nota {chave}: {e}", logging.ERROR)
            # Capturar evidências em caso de erro geral
            try:
                evidences_dir = Path(__file__).resolve().parent.parent / "logs" / "evidencias"
                evidences_dir.mkdir(parents=True, exist_ok=True)
                await page.screenshot(path=str(evidences_dir / f"erro_{chave}.png"))
                html = await page.content()
                with open(str(evidences_dir / f"erro_{chave}.html"), "w", encoding="utf-8") as f:
                    f.write(html)
            except Exception:
                pass
            return None, []

    async def processar_planilha_xlsx(self, file_path: Path, output_folder: Path) -> List[Dict[str, Any]]:
        """
        Lê a planilha Excel com chaves, valida todas as linhas e inicia a automação.
        Gera uma lista de resultados contendo status de cada chave processada.
        """
        self.is_running = True
        self.bot_core.is_running = True
        self.bot_core.on_log = self.on_log
        self.bot_core.on_progress = self.on_progress
        resultados = []
        
        if not file_path.exists():
            self.log(f"Arquivo de entrada não encontrado: {file_path}", logging.ERROR)
            return []
            
        try:
            # 1. Carregar planilha
            df = pd.read_excel(file_path)
            
            # Sanitizar colunas (Procurar chaves como 'CNPJ' e 'Chave' / 'Chave de Acesso')
            col_cnpj = [c for c in df.columns if "cnpj" in c.lower()]
            col_chave = [c for c in df.columns if "chave" in c.lower() or "cfe" in c.lower()]
            
            if not col_chave:
                self.log("Não foi possível localizar a coluna de Chaves de Acesso no Excel.", logging.ERROR)
                return []
                
            cnpj_col_name = col_cnpj[0] if col_cnpj else None
            chave_col_name = col_chave[0]
            
            # Pré-Validação de todos os itens da lista
            jobs_validos = []
            for idx, row in df.iterrows():
                chave_raw = str(row[chave_col_name]).strip()
                cnpj_raw = str(row[cnpj_col_name]).strip() if cnpj_col_name else None
                
                # Limpar caracteres
                chave = re.sub(r"\D", "", chave_raw)
                cnpj = re.sub(r"\D", "", cnpj_raw) if cnpj_raw else None
                
                # Executar validação rigorosa
                valida, msg = self.validar_chave_sat(chave, cnpj)
                
                job_res = {
                    "linha": idx + 2, # Planilhas 1-indexed com cabeçalho
                    "chave": chave,
                    "cnpj": cnpj or "N/A",
                    "status": "VALIDADO" if valida else "ERRO_VALIDACAO",
                    "mensagem": msg
                }
                
                if valida:
                    jobs_validos.append((chave, cnpj))
                else:
                    self.log(f"Linha {job_res['linha']} rejeitada: {msg}", logging.WARNING)
                    
                resultados.append(job_res)
                
            if not jobs_validos:
                self.log("Nenhuma chave válida encontrada na planilha para busca.", logging.WARNING)
                return resultados
                
            self.log(f"Total de {len(jobs_validos)} chaves válidas prontas para pesquisa no portal SAT.")
            
            # 2. Iniciar Automação Playwright
            async with async_playwright() as p:
                self.bot_core.browser, self.bot_core.context = await self.bot_core.init_browser(p)
                page = await self.bot_core.context.new_page()
                
                # Auto-confirmar popups nativos do navegador de forma ágil
                async def handle_dialog(dialog):
                    self.log(f"Popup JS detectado: '{dialog.message}'. Confirmando automaticamente...")
                    await dialog.accept()
                page.on("dialog", lambda d: asyncio.create_task(handle_dialog(d)))
                
                # Efetuar Login SSL
                if not await self.bot_core.realizar_login(page):
                    self.log("Falha no login do portal SAT. Cancelando processamento.", logging.ERROR)
                    for r in resultados:
                        if r["status"] == "VALIDADO":
                            r["status"] = "ERRO_LOGIN"
                            r["mensagem"] = "Não foi possível efetuar login por certificado digital."
                    return resultados

                # Determinar CNPJ inicial a partir da primeira chave válida
                cnpj_inicial = jobs_validos[0][1] or jobs_validos[0][0][6:20] if jobs_validos else None
                if cnpj_inicial:
                    self.log(f"Selecionando CNPJ inicial: {cnpj_inicial}")
                    await self.bot_core.alternar_cnpj(page, cnpj_inicial)

                # Navegar para "Consultar CFe Sem Erros" após CNPJ selecionado
                await self.navegar_para_consulta_individual(page)
                
                # 3. Processar Chaves Válidas
                for idx, (chave, cnpj) in enumerate(jobs_validos):
                    if not self.is_running:
                        break
                        
                    # Procurar resultado correspondente na lista para atualizar status
                    res_item = next(r for r in resultados if r["chave"] == chave)
                    res_item["status"] = "PROCESSANDO"
                    
                    # Evitar buscas duplicadas se a chave já existe no banco
                    with self.session_factory() as session:
                        if StateManager.check_cfe_exists(session, chave):
                            self.log(f"Chave {chave} já existe no banco de dados. Pulando download.")
                            res_item["status"] = "CONCLUIDO"
                            res_item["mensagem"] = "Chave já cadastrada no banco de dados."
                            continue
                            
                    # Resiliência de sessão antes de pesquisar
                    recuperou = await self.bot_core.verificar_e_recuperar_sessao(page, cnpj or chave[6:20], "")
                    if recuperou:
                        await self.navegar_para_consulta_individual(page)
                        
                    self.log(f"Pesquisando chave ({idx+1}/{len(jobs_validos)}): {chave}...")
                    
                    # Buscar chave
                    encontrou = await self.consultar_chave(page, chave)
                    if encontrou:
                        # Raspar dados
                        cfe, itens = await self.raspar_dados_detalhados(page, chave)
                        if cfe and itens:
                            # Salvar no banco relacionamente
                            with self.session_factory() as session:
                                salvo = StateManager.save_cfe_to_db(session, cfe, itens)
                                
                            if salvo:
                                res_item["status"] = "CONCLUIDO"
                                res_item["mensagem"] = f"Nota baixada e salva com sucesso ({len(itens)} itens)."
                            else:
                                res_item["status"] = "ERRO_BANCO"
                                res_item["mensagem"] = "Erro ao persistir dados da nota no banco SQL Server."
                        else:
                            res_item["status"] = "ERRO_RASPAGEM"
                            res_item["mensagem"] = "Falha ao ler os dados internos das abas da nota."
                            
                        # Fechar tela de detalhes e voltar à tela de busca sem erros
                        btn_voltar = page.locator("input[id*='btnVoltar']").first
                        if await btn_voltar.count() > 0:
                            await btn_voltar.click()
                        else:
                            await self.navegar_para_consulta_individual(page)
                            
                        await page.wait_for_load_state("networkidle")
                    else:
                        res_item["status"] = "NAO_ENCONTRADO"
                        res_item["mensagem"] = "Nota fiscal não retornou resultados na pesquisa do portal SAT."
                        
                    # Emitir progresso para a UI
                    if self.on_progress:
                        self.on_progress({
                            "total": len(jobs_validos),
                            "atual": idx + 1,
                            "chave": chave,
                            "status": res_item["status"],
                            "mensagem": res_item["mensagem"]
                        })
                        
                    await asyncio.sleep(self.bot_core.request_delay)
                    
        except Exception as e:
            self.log(f"Erro fatal ao processar planilha XLSX: {e}", logging.ERROR)
        finally:
            self.is_running = False
            try:
                if self.bot_core.context:
                    await self.bot_core.context.close()
            except Exception:
                pass
            try:
                if self.bot_core.browser:
                    await self.bot_core.browser.close()
            except Exception:
                pass
            self.bot_core.cleanup()
            self.log("Navegador de busca isolada finalizado.")
            
        return resultados

    def stop(self):
        self.is_running = False
        self.bot_core.stop()
