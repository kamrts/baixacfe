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

    async def _extrair_campo_por_titulo(self, page: Page, titulo: str, chave: str) -> Optional[str]:
        """
        Extrai valor de um campo baseado na estrutura HTML real do SAT SP.
        Estrutura real do portal:
        <div class="alinhamentoLinha">
            <div class="TituloLinhaCampo">
                <span class="TituloCampo">Label: </span>
            </div>
            <span id="conteudo_lblXxx" class="ValorCampo">Valor</span>
        </div>
        """
        try:
            # Estratégia 1 (PRINCIPAL): Usar div.alinhamentoLinha conforme estrutura real do portal
            seletor_alinhamento = f"div.alinhamentoLinha:has(span.TituloCampo:has-text('{titulo}')) span.ValorCampo"
            locator_alinhamento = page.locator(seletor_alinhamento).first
            if await locator_alinhamento.count() > 0:
                valor = await locator_alinhamento.inner_text(timeout=10000)
                if valor and valor.strip():
                    return valor.strip()
            
            # Estratégia 2: Procurar dentro da mesma div.LinhaCampo (fallback)
            seletor_linha = f"div.LinhaCampo:has(span.TituloCampo:has-text('{titulo}')) span.ValorCampo"
            locator_linha = page.locator(seletor_linha).first
            if await locator_linha.count() > 0:
                valor = await locator_linha.inner_text(timeout=10000)
                if valor and valor.strip():
                    return valor.strip()
            
            # Estratégia 3: Procurar irmão direto do TituloLinhaCampo
            seletor_titulo_irmao = f"div.TituloLinhaCampo:has(span.TituloCampo:has-text('{titulo}')) ~ span.ValorCampo"
            locator_titulo_irmao = page.locator(seletor_titulo_irmao).first
            if await locator_titulo_irmao.count() > 0:
                valor = await locator_titulo_irmao.inner_text(timeout=10000)
                if valor and valor.strip():
                    return valor.strip()
            
            # Estratégia 4: Procurar irmão direto do TituloCampo
            seletor_irmao = f"span.TituloCampo:has-text('{titulo}') + span.ValorCampo"
            locator_irmao = page.locator(seletor_irmao).first
            if await locator_irmao.count() > 0:
                valor = await locator_irmao.inner_text(timeout=10000)
                if valor and valor.strip():
                    return valor.strip()
            
            # Estratégia 5: Procurar no contexto de TituloLinhaCampo seguido de ValorLinhaCampo
            seletor_titulo_linha = f"div.TituloLinhaCampo:has(span.TituloCampo:has-text('{titulo}')) + div.ValorLinhaCampo span.ValorCampo"
            locator_titulo_linha = page.locator(seletor_titulo_linha).first
            if await locator_titulo_linha.count() > 0:
                valor = await locator_titulo_linha.inner_text(timeout=10000)
                if valor and valor.strip():
                    return valor.strip()
                    
            # Estratégia 6: XPath mais abrangente - encontrar o span TituloCampo e subir ao container pai
            try:
                elementos = await page.locator(f"span.TituloCampo:text-is('{titulo}:'), span.TituloCampo:text-is('{titulo}'), span.TituloCampo:has-text('{titulo}')").all()
                for elem in elementos:
                    # Subir dois níveis (span -> div.TituloLinhaCampo -> div.alinhamentoLinha)
                    parent = elem.locator("xpath=ancestor::div[contains(@class, 'alinhamentoLinha') or contains(@class, 'LinhaCampo')]")
                    valor_elem = parent.locator("span.ValorCampo").first
                    if await valor_elem.count() > 0:
                        valor = await valor_elem.inner_text(timeout=5000)
                        if valor and valor.strip():
                            return valor.strip()
            except Exception:
                pass
                
            return None
        except Exception as e:
            self.log(f"Erro ao extrair campo '{titulo}' para {chave}: {e}", logging.WARNING)
            return None

    async def raspar_dados_detalhados(self, page: Page, chave: str) -> Tuple[Optional[Dict[str, Any]], List[Dict[str, Any]]]:
        """
        Efetua a raspagem completa de dados do cupom fiscal.
        Na aba CF-e já estão todas as informações de emitente e destinatário.
        Depois navega para aba Produtos/Serviços para coletar os itens.
        """
        cfe_data = {}
        itens_data = []
        
        try:
            # Aguardar página carregar completamente
            await page.wait_for_load_state("networkidle")
            await page.wait_for_timeout(2000)
            
            # Capturar screenshot inicial para debug
            evidences_dir = Path(__file__).resolve().parent.parent / "logs" / "evidencias"
            evidences_dir.mkdir(parents=True, exist_ok=True)
            await page.screenshot(path=str(evidences_dir / f"debug_inicial_{chave[:20]}.png"))
            
            # Mapear e extrair dados - todas as informações estão na aba inicial CF-e
            cfe_data["chave"] = chave
            
            # Número do CF-e - PRIMEIRO tentar pelo ID específico
            num_text = None
            try:
                locator_num = page.locator("#conteudo_lblCfeNumero")
                if await locator_num.count() > 0:
                    num_text = await locator_num.inner_text(timeout=10000)
            except Exception:
                pass
            
            # Fallback para extração por título
            if not num_text or not num_text.strip():
                num_text = await self._extrair_campo_por_titulo(page, "Número do CF-e", chave)
            self.log(f"[DEBUG] Campo 'Número do CF-e' extraído: {num_text}")
            if num_text:
                num_clean = re.sub(r"\D", "", num_text)
                # Validar que não é a chave completa (44 dígitos)
                if len(num_clean) < 20:
                    cfe_data["numero_cfe"] = int(num_clean) if num_clean else 0
                else:
                    self.log(f"Número CF-e parece ser chave completa, ignorando: {num_text}", logging.WARNING)
                    cfe_data["numero_cfe"] = 0
            else:
                cfe_data["numero_cfe"] = 0
            
            # Valor Total do CF-e - PRIMEIRO tentar pelo ID específico
            val_text = None
            try:
                locator_val = page.locator("#conteudo_lblCfeValorTotal")
                if await locator_val.count() > 0:
                    val_text = await locator_val.inner_text(timeout=10000)
            except Exception:
                pass
            
            # Fallback para extração por título
            if not val_text or not val_text.strip():
                val_text = await self._extrair_campo_por_titulo(page, "Valor Total do CF-e", chave)
            self.log(f"[DEBUG] Campo 'Valor Total do CF-e' extraído: {val_text}")
            if not val_text:
                val_text = await self._extrair_campo_por_titulo(page, "Valor Total", chave)
                self.log(f"[DEBUG] Campo 'Valor Total' (fallback) extraído: {val_text}")
            if val_text:
                val_clean = val_text.replace("R$", "").replace(".", "").replace(",", ".").strip()
                if val_clean and len(val_clean) < 20:
                    try:
                        cfe_data["valor_total"] = float(val_clean)
                    except ValueError:
                        cfe_data["valor_total"] = 0.00
                else:
                    cfe_data["valor_total"] = 0.00
            else:
                cfe_data["valor_total"] = 0.00
            
            # Data/Hora Emissão - PRIMEIRO tentar pelo ID específico
            datetime_text = None
            try:
                locator_dt = page.locator("#conteudo_lblCfeDataHoraEmissao, #conteudo_lblDataHoraEmissao")
                if await locator_dt.count() > 0:
                    datetime_text = await locator_dt.inner_text(timeout=10000)
            except Exception:
                pass
            
            # Fallback para extração por título
            if not datetime_text or not datetime_text.strip():
                datetime_text = await self._extrair_campo_por_titulo(page, "Data/Hora de Emissão", chave)
            self.log(f"[DEBUG] Campo 'Data/Hora de Emissão' extraído: {datetime_text}")
            if not datetime_text:
                datetime_text = await self._extrair_campo_por_titulo(page, "Data de Emissão", chave)
            if datetime_text:
                try:
                    cfe_data["data_hora_emissao"] = datetime.strptime(datetime_text.strip(), "%d/%m/%Y %H:%M:%S")
                except ValueError:
                    try:
                        cfe_data["data_hora_emissao"] = datetime.strptime(datetime_text.strip(), "%d/%m/%Y")
                    except ValueError:
                        cfe_data["data_hora_emissao"] = datetime.now()
            else:
                cfe_data["data_hora_emissao"] = datetime.now()
            
            # EMITENTE - já está na aba inicial CF-e
            # CNPJ - PRIMEIRO tentar pelo ID específico
            emit_cnpj_text = None
            try:
                locator_cnpj = page.locator("#conteudo_lblEmitenteCnpj")
                if await locator_cnpj.count() > 0:
                    emit_cnpj_text = await locator_cnpj.inner_text(timeout=10000)
            except Exception:
                pass
            
            # Fallback para extração por título
            if not emit_cnpj_text or not emit_cnpj_text.strip():
                emit_cnpj_text = await self._extrair_campo_por_titulo(page, "CNPJ", chave)
            self.log(f"[DEBUG] Campo 'CNPJ' extraído: {emit_cnpj_text}")
            if emit_cnpj_text:
                cnpj_limpo = re.sub(r"\D", "", emit_cnpj_text)
                cfe_data["cnpj_emitente"] = cnpj_limpo if cnpj_limpo else chave[6:20]
            else:
                cfe_data["cnpj_emitente"] = chave[6:20]
            
            # Nome / Razão Social - PRIMEIRO tentar pelo ID específico
            emit_nome_text = None
            try:
                locator_nome = page.locator("#conteudo_lblEmitenteNome")
                if await locator_nome.count() > 0:
                    emit_nome_text = await locator_nome.inner_text(timeout=10000)
            except Exception:
                pass
            
            # Fallback para extração por título
            if not emit_nome_text or not emit_nome_text.strip():
                emit_nome_text = await self._extrair_campo_por_titulo(page, "Nome / Razão Social", chave)
            self.log(f"[DEBUG] Campo 'Nome / Razão Social' extraído: {emit_nome_text}")
            if not emit_nome_text:
                emit_nome_text = await self._extrair_campo_por_titulo(page, "Razão Social", chave)
            cfe_data["nome_emitente"] = emit_nome_text.strip() if emit_nome_text else "Emitente Desconhecido"
            
            # Inscrição Estadual - PRIMEIRO tentar pelo ID específico
            emit_ie_text = None
            try:
                locator_ie = page.locator("#conteudo_lblEmitenteInscricaoEstatual")
                if await locator_ie.count() > 0:
                    emit_ie_text = await locator_ie.inner_text(timeout=10000)
            except Exception:
                pass
            
            # Fallback para extração por título
            if not emit_ie_text or not emit_ie_text.strip():
                emit_ie_text = await self._extrair_campo_por_titulo(page, "Inscrição Estadual", chave)
            self.log(f"[DEBUG] Campo 'Inscrição Estadual' extraído: {emit_ie_text}")
            if emit_ie_text:
                ie_limpo = re.sub(r"\D", "", emit_ie_text)
                cfe_data["inscricao_estadual"] = ie_limpo if ie_limpo else None
            else:
                cfe_data["inscricao_estadual"] = None
            
            # UF - PRIMEIRO tentar pelo ID específico
            uf_text = None
            try:
                locator_uf = page.locator("#conteudo_lblEmitenteUf")
                if await locator_uf.count() > 0:
                    uf_text = await locator_uf.inner_text(timeout=10000)
            except Exception:
                pass
            
            # Fallback para extração por título
            if not uf_text or not uf_text.strip():
                uf_text = await self._extrair_campo_por_titulo(page, "UF", chave)
            self.log(f"[DEBUG] Campo 'UF' extraído: {uf_text}")
            cfe_data["uf_emitente"] = uf_text.strip() if uf_text else "SP"
            
            # DESTINATÁRIO - também está na aba inicial CF-e
            # CPF / CNPJ - PRIMEIRO tentar pelo ID específico
            dest_doc_text = None
            try:
                locator_dest_doc = page.locator("#conteudo_lblDestinatarioCnpj")
                if await locator_dest_doc.count() > 0:
                    dest_doc_text = await locator_dest_doc.inner_text(timeout=10000)
            except Exception:
                pass
            
            # Fallback para extração por título
            if not dest_doc_text or not dest_doc_text.strip():
                dest_doc_text = await self._extrair_campo_por_titulo(page, "CPF / CNPJ", chave)
            self.log(f"[DEBUG] Campo 'CPF / CNPJ' extraído: {dest_doc_text}")
            if not dest_doc_text:
                dest_doc_text = await self._extrair_campo_por_titulo(page, "CPF", chave)
            # Tratar "Não Informado" como nulo
            if dest_doc_text and dest_doc_text.strip().lower() != "não informado":
                doc_limpo = re.sub(r"\D", "", dest_doc_text)
                cfe_data["destinatario_documento"] = doc_limpo if doc_limpo else None
            else:
                cfe_data["destinatario_documento"] = None
            
            # Nome Destinatário - PRIMEIRO tentar pelo ID específico
            dest_nome_text = None
            try:
                locator_dest_nome = page.locator("#conteudo_lblDestinatarioNome")
                if await locator_dest_nome.count() > 0:
                    dest_nome_text = await locator_dest_nome.inner_text(timeout=10000)
            except Exception:
                pass
            
            # Fallback para extração por título
            if not dest_nome_text or not dest_nome_text.strip():
                dest_nome_text = await self._extrair_campo_por_titulo(page, "Nome", chave)
            self.log(f"[DEBUG] Campo 'Nome' (Destinatário) extraído: {dest_nome_text}")
            # Tratar "Não Informado" como nulo
            if dest_nome_text and dest_nome_text.strip().lower() != "não informado":
                cfe_data["destinatario_nome"] = dest_nome_text.strip()
            else:
                cfe_data["destinatario_nome"] = None
            
            self.log(f"Dados do cabeçalho extraídos: Número={cfe_data.get('numero_cfe')}, Valor={cfe_data.get('valor_total')}, CNPJ={cfe_data.get('cnpj_emitente')}")
            
            # CORREÇÃO 3 — Clicar obrigatoriamente na aba Produtos/Serviços
            # Usar seletor específico do input type="submit" conforme HTML fornecido
            seletor_aba_produtos = "#conteudo_tabProdutoServico, input[id='conteudo_tabProdutoServico']"
            
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
                
            # Localizar tabela de produtos usando ID correto: conteudo_grvProdutosServicos
            seletor_tabela = "#conteudo_grvProdutosServicos, table[id='conteudo_grvProdutosServicos'], table[id*='grvProdutosServicos']"
            await page.wait_for_selector(seletor_tabela, timeout=60000)
            
            linhas_prod = await page.locator(f"{seletor_tabela} tr").all()
            
            if not linhas_prod or len(linhas_prod) <= 1:
                self.log(f"Tabela de produtos vazia ou não encontrada para a chave {chave}.", logging.WARNING)
                return cfe_data, []
            
            # CORREÇÃO 4 — Capturar TODOS os campos de produtos/serviços
            # Os dados estão em spans com IDs específicos no padrão:
            # conteudo_grvProdutosServicos_lblProdutoServicoDesc_0, _1, _2, etc.
            
            # Contar número de itens pela quantidade de linhas (excluindo cabeçalho)
            num_itens = len(linhas_prod) - 1
            self.log(f"[DEBUG] Encontrados {num_itens} itens de produto para processar")
            
            def parse_float(valor: str) -> float:
                if not valor or valor.strip() == "" or valor.strip() == "Não Informado":
                    return 0.00
                try:
                    return float(valor.replace(".", "").replace(",", ".").strip())
                except ValueError:
                    return 0.00
            
            def parse_int(valor: str) -> int:
                if not valor or valor.strip() == "" or valor.strip() == "Não Informado":
                    return 0
                try:
                    return int(re.sub(r"\D", "", valor))
                except ValueError:
                    return 0
            
            def limpar_valor(valor: str) -> Optional[str]:
                if not valor or valor.strip() == "" or valor.strip() == "Não Informado":
                    return None
                return valor.strip()
            
            # Processar cada item usando os IDs dos spans
            for idx in range(num_itens):
                try:
                    # Função para extrair valor do span pelo ID
                    async def get_span_value(campo_id: str, item_idx: int = idx) -> Optional[str]:
                        try:
                            span = page.locator(f"#conteudo_grvProdutosServicos_{campo_id}_{item_idx}")
                            if await span.count() > 0:
                                return await span.inner_text(timeout=5000)
                        except Exception:
                            pass
                        return None
                    
                    # Extrair todos os campos usando os IDs corretos do HTML
                    item = {
                        "numero_item": parse_int(await get_span_value("lblProdutoServicoNum")) or idx + 1,
                        "descricao": limpar_valor(await get_span_value("lblProdutoServicoDesc")) or "",
                        "quantidade_comercial": parse_float(await get_span_value("lblProdutoServicoQtd")),
                        "unidade_comercial": limpar_valor(await get_span_value("lblProdutoServicoUnit")) or "UN",
                        "valor_liquido": parse_float(await get_span_value("lblProdutoServicoIcmsValorLiquidoItem")),
                        "info_adicional": limpar_valor(await get_span_value("lblProdutoServicoInformacaoAdicionalProduto")),
                        "codigo_produto": limpar_valor(await get_span_value("lblProdutoServicoCodigoProduto")) or "",
                        "gtin": limpar_valor(await get_span_value("lblProdutoServicoGtin")),
                        "ncm": limpar_valor(await get_span_value("lblProdutoServicoNcm")),
                        "cest": limpar_valor(await get_span_value("lblCest")),
                        "cfop": limpar_valor(await get_span_value("lblProdutoServicoCFOP")) or "5929",
                        "valor_unitario": parse_float(await get_span_value("lblProdutoServicoValorUnit")),
                        "valor_bruto": parse_float(await get_span_value("lblProdutoServicoValorBruto")),
                        "regra_calculo": limpar_valor(await get_span_value("lblProdutoServicoRegraCalculo")),
                        "valor_desconto": parse_float(await get_span_value("lblProdutoServicoValorDesconto")),
                        "outras_despesas": parse_float(await get_span_value("lblProdutoServicoOutrasDespesasAcessorias")),
                        "rateio_desconto": parse_float(await get_span_value("lblProdutoServicoRateioDescontoSubtotal")),
                        "rateio_acrescimo": parse_float(await get_span_value("lblProdutoServicoRateioAcrescimoSubtotal")),
                        "observacoes_fisco": limpar_valor(await get_span_value("lblProdutoServicoObservacaoFisco")),
                        "origem_mercadoria": limpar_valor(await get_span_value("lblProdutoServicoOrigemMercadoria")),
                        "tributacao_icms": limpar_valor(await get_span_value("lblProdutoServicoTributacaoIcms")),
                        "situacao_simples_nacional": limpar_valor(await get_span_value("lblProdutoServicoCodigoSituacaoOperacaoSimplesNacional")),
                        "aliquota_efetiva": parse_float(await get_span_value("lblProdutoServicoAliquotaEfetiva")),
                        "valor_icms": parse_float(await get_span_value("lblProdutoServicoValorIcms")),
                        # PIS
                        "pis_cst": limpar_valor(await get_span_value("lblProdutoServicoPisCodigoSitucaoTributario")),
                        "pis_base_calculo": parse_float(await get_span_value("lblProdutoServicoPisValorBaseCalculoPis")),
                        "pis_aliquota": parse_float(await get_span_value("lblProdutoServicoPisAliquotaPisPorcentagem")),
                        "pis_valor": parse_float(await get_span_value("lblProdutoServicoPisValorPis")),
                        # COFINS
                        "cofins_cst": limpar_valor(await get_span_value("lblProdutoServicoCofinsCodigoSituacaoTributarioCofins")),
                        "cofins_base_calculo": parse_float(await get_span_value("lblProdutoServicoCofinsValorBaseCalculoCofins")),
                        "cofins_aliquota": parse_float(await get_span_value("lblProdutoServicoAliquotaCofinsPorcentagem")),
                        "cofins_valor": parse_float(await get_span_value("lblProdutoServicoCofinsValorCofins")),
                        # Valor aproximado tributos (Lei 12741)
                        "valor_aproximado_tributos": parse_float(await get_span_value("lblvalorItem12741")),
                    }
                    
                    # Log do primeiro item para debug
                    if idx == 0:
                        self.log(f"[DEBUG] Primeiro item extraído: {item}")
                    
                    itens_data.append(item)
                    
                except Exception as e:
                    self.log(f"[DEBUG] Erro ao processar item {idx + 1}: {e}", logging.WARNING)
                    continue
            
            # Processar cada linha da tabela (ignorando cabeçalho - linha 0)
            for idx, linha in enumerate(linhas_prod[1:]):
                try:
                    # Extrair todas as colunas <td> da linha
                    colunas = await linha.locator("td").all_inner_texts()
                    
                    if not colunas or len(colunas) < 5:
                        self.log(f"[DEBUG] Linha {idx + 1} com poucas colunas ({len(colunas) if colunas else 0}), ignorando", logging.WARNING)
                        continue
                    
                    self.log(f"[DEBUG] Linha {idx + 1}: {len(colunas)} colunas encontradas")
                    
                    # Extrair campos por posição (baseado na estrutura do cabeçalho)
                    item = {
                        "numero_item": parse_int(colunas[0]) if len(colunas) > 0 else idx + 1,
                        "descricao": limpar_valor(colunas[1]) if len(colunas) > 1 else "",
                        "quantidade_comercial": parse_float(colunas[2]) if len(colunas) > 2 else 0.00,
                        "unidade_comercial": limpar_valor(colunas[3]) if len(colunas) > 3 else "UN",
                        "valor_liquido": parse_float(colunas[4]) if len(colunas) > 4 else 0.00,
                        "info_adicional": limpar_valor(colunas[5]) if len(colunas) > 5 else None,
                        "codigo_produto": limpar_valor(colunas[6]) if len(colunas) > 6 else "",
                        "gtin": limpar_valor(colunas[7]) if len(colunas) > 7 else None,
                        "ncm": limpar_valor(colunas[8]) if len(colunas) > 8 else None,
                        "cest": limpar_valor(colunas[9]) if len(colunas) > 9 else None,
                        "cfop": limpar_valor(colunas[10]) if len(colunas) > 10 else "5929",
                        "valor_unitario": parse_float(colunas[11]) if len(colunas) > 11 else 0.00,
                        "valor_bruto": parse_float(colunas[12]) if len(colunas) > 12 else 0.00,
                        "regra_calculo": limpar_valor(colunas[13]) if len(colunas) > 13 else None,
                        "valor_desconto": parse_float(colunas[14]) if len(colunas) > 14 else 0.00,
                        "outras_despesas": parse_float(colunas[15]) if len(colunas) > 15 else 0.00,
                        "rateio_desconto": parse_float(colunas[16]) if len(colunas) > 16 else 0.00,
                        "rateio_acrescimo": parse_float(colunas[17]) if len(colunas) > 17 else 0.00,
                        "observacoes_fisco": limpar_valor(colunas[18]) if len(colunas) > 18 else None,
                        "origem_mercadoria": limpar_valor(colunas[19]) if len(colunas) > 19 else None,
                        "tributacao_icms": limpar_valor(colunas[20]) if len(colunas) > 20 else None,
                        "situacao_simples_nacional": limpar_valor(colunas[21]) if len(colunas) > 21 else None,
                        "valor_icms": parse_float(colunas[22]) if len(colunas) > 22 else 0.00,
                    }
                    
                    # Log do primeiro item para debug
                    if idx == 0:
                        self.log(f"[DEBUG] Primeiro item extraído: {item}")
                    
                    itens_data.append(item)
                    
                except Exception as e:
                    self.log(f"[DEBUG] Erro ao processar linha {idx + 1}: {e}", logging.WARNING)
                    continue
                
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
                        
                        # Log dos dados extraídos para debug
                        self.log(f"[DEBUG] Dados CFe extraídos: {cfe}")
                        self.log(f"[DEBUG] Total de itens extraídos: {len(itens) if itens else 0}")
                        
                        # Salvar no banco mesmo se não houver itens (itens pode estar vazio)
                        if cfe:
                            with self.session_factory() as session:
                                salvo = StateManager.save_cfe_to_db(session, cfe, itens or [])
                                
                            if salvo:
                                res_item["status"] = "CONCLUIDO"
                                res_item["mensagem"] = f"Nota baixada e salva com sucesso ({len(itens) if itens else 0} itens)."
                                self.log(f"CF-e {chave} salvo no banco com sucesso!")
                            else:
                                res_item["status"] = "ERRO_BANCO"
                                res_item["mensagem"] = "Erro ao persistir dados da nota no banco SQL Server."
                                self.log(f"Erro ao salvar CF-e {chave} no banco.", logging.ERROR)
                        else:
                            res_item["status"] = "ERRO_RASPAGEM"
                            res_item["mensagem"] = "Falha ao ler os dados do cabeçalho da nota."
                            self.log(f"Dados do cabeçalho CF-e {chave} não foram extraídos.", logging.ERROR)
                            
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
