# backend/sat_bot.py
import os
import json
import asyncio
import logging
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Callable, Tuple, Optional
from playwright.async_api import async_playwright, Page, Browser, BrowserContext

from database.models import QueueProgress
from backend.state_manager import StateManager

logger = logging.getLogger("SAT_Downloader")

class SATBot:
    """
    Robô principal de Automação do Portal SAT/SP.
    Utiliza Playwright Assíncrono com resiliência de falha e recuperação automática.
    """
    
    def __init__(self, db_session_factory: Callable[[], Any], config: Dict[str, Any]):
        self.session_factory = db_session_factory
        self.config = config
        self.browser: Optional[Browser] = None
        self.context: Optional[BrowserContext] = None
        self.is_running = False
        self.current_job_id = None
        
        # Callbacks para comunicação com a UI
        self.on_log: Optional[Callable[[str], None]] = None
        self.on_progress: Optional[Callable[[Dict[str, Any]], None]] = None
        
        # Configurações do robô
        self.download_folder = Path(config.get("download_folder") or (Path(__file__).resolve().parent.parent / "downloads"))
        self.request_delay = float(config.get("request_delay", 3.00))
        self.max_retries = int(config.get("max_retries", 3))
        self.timeout = int(config.get("timeout_seconds", 30)) * 1000  # Playwright usa ms
        self.headless = bool(config.get("headless_mode", False))
        
    def log(self, message: str, level: int = logging.INFO):
        """Registra log no logger do Python e envia para a interface gráfica."""
        logger.log(level, message)
        if self.on_log:
            prefix = "[INFO]"
            if level == logging.WARNING:
                prefix = "[AVISO]"
            elif level == logging.ERROR:
                prefix = "[ERRO]"
            self.on_log(f"{datetime.now().strftime('%H:%M:%S')} {prefix} {message}")

    def _prepare_chrome_profile(self, cert_name: Optional[str]) -> Optional[str]:
        """
        Cria um perfil temporário do Chrome com o arquivo Preferences configurado
        para autoseleção de certificado mTLS via profile.managed_auto_select_certificate_for_urls.
        Esta é a única abordagem confiável para evitar o popup de seleção de certificado
        no Chrome quando usando Playwright (equivalente ao add_experimental_option no Selenium).
        Retorna o caminho do diretório de perfil.
        """
        profile_dir = Path(__file__).resolve().parent.parent / "logs" / "_chrome_profile"
        default_dir = profile_dir / "Default"
        default_dir.mkdir(parents=True, exist_ok=True)
        
        pref_file = default_dir / "Preferences"
        
        prefs: dict = {}
        if cert_name and cert_name.strip() and cert_name != "Autoseleção do Portal (Recomendado)":
            # A chave profile.managed_auto_select_certificate_for_urls aceita uma lista
            # de objetos JSON stringificados contendo pattern + filter.
            # Padrão de filtro por SUBJECT.CN (nome do certificado selecionado pelo usuário).
            policy_entries = [
                json.dumps({
                    "pattern": "https://satsp.fazenda.sp.gov.br",
                    "filter": {"SUBJECT": {"CN": cert_name}}
                }),
                json.dumps({
                    "pattern": "https://[*.]fazenda.sp.gov.br",
                    "filter": {"SUBJECT": {"CN": cert_name}}
                }),
            ]
            prefs = {
                "profile": {
                    "managed_auto_select_certificate_for_urls": policy_entries
                }
            }
            self.log(f"Perfil Chrome configurado para autoseleção: {cert_name}")
        else:
            # Sem filtro: Chrome vai selecionar automaticamente o único cert disponível
            # ou exibir popup se houver mais de um.
            prefs = {}
            self.log("Nenhum certificado específico configurado — Chrome usará seleção padrão.")
        
        # Escrever o arquivo de preferências
        pref_file.write_text(json.dumps(prefs, ensure_ascii=False, indent=2), encoding="utf-8")
        return str(profile_dir)

    async def init_browser(self, playwright) -> Tuple[Browser, BrowserContext]:
        """
        Inicializa o Chrome via launch_persistent_context com perfil temporário
        que já contém as preferências de autoseleção de certificado configuradas.
        Esta é a única abordagem confiável para auto-seleção de certificado mTLS no Playwright.
        """
        launch_args = [
            "--ignore-certificate-errors",
            "--disable-gpu",
            "--no-first-run",
            "--no-default-browser-check",
        ]
        
        cert_name = self.config.get("cert_name")
        profile_dir = self._prepare_chrome_profile(cert_name)
        
        proxy_config = None
        if self.config.get("proxy_url"):
            proxy_config = {"server": self.config["proxy_url"]}
            self.log(f"Utilizando proxy: {self.config['proxy_url']}")
        
        downloads_dir = self.download_folder / "temp"
        downloads_dir.mkdir(parents=True, exist_ok=True)
        
        self.log(f"Iniciando Chrome com perfil de autoseleção (Headless: {self.headless})...")
        
        context = None
        # Tentar com Chrome instalado primeiro (único que lê o cert store do Windows)
        for attempt, kwargs in enumerate([
            {  # 1: Chrome instalado no caminho padrão
                "executable_path": r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            },
            {  # 2: Chrome via channel (busca no PATH)
                "channel": "chrome",
            },
            {  # 3: Chromium embutido do Playwright (fallback)
            }
        ]):
            try:
                context = await playwright.chromium.launch_persistent_context(
                    user_data_dir=profile_dir,
                    headless=self.headless,
                    args=launch_args,
                    slow_mo=0,
                    accept_downloads=True,
                    proxy=proxy_config,
                    viewport={"width": 1280, "height": 800},
                    **kwargs
                )
                self.log(f"Chrome iniciado com sucesso (tentativa {attempt + 1}).")
                break
            except Exception as e:
                self.log(f"Tentativa {attempt + 1} falhou: {e}", logging.WARNING)
                if attempt == 2:
                    raise RuntimeError(f"Não foi possível iniciar nenhum navegador: {e}")
        
        # launch_persistent_context retorna um BrowserContext, não um Browser.
        # Guardamos None em self.browser para a limpeza no finally.
        context.set_default_timeout(self.timeout)
        return None, context


    async def realizar_login(self, page: Page) -> bool:
        """
        Navega para a tela de Login SSL da SEFAZ e aguarda a autenticação do usuário.
        Trata timeout, CAPTCHAs e detecta sucesso.
        """
        url = "https://satsp.fazenda.sp.gov.br/COMSAT/Account/LoginSSL.aspx?ReturnUrl=%2fCOMSAT%2f"
        self.log(f"Acessando portal de login: {url}")
        
        try:
            await page.goto(url)
            
            # Clicar na opção "Contribuinte" se houver a seleção (comum no fluxo)
            contribuinte_option = page.locator("input[id*='rbtContribuinte']")
            if await contribuinte_option.count() > 0:
                await contribuinte_option.click()
                await asyncio.sleep(1)
            
            # Clicar no botão Acesso via Certificado Digital
            btn_certificado = page.locator("a[id*='imgCertificado'], a[id*='lnkLoginCertificado'], a.eCNPJ, input[id*='btnCertificado']")
            if await btn_certificado.count() > 0:
                self.log("Identificado botão de login por certificado. Acionando...")
                await btn_certificado.first.click()
            
            # Como a seleção do certificado A3 exige interação do usuário (popup do Windows),
            # nós aguardamos até 60 segundos monitorando a URL.
            self.log("Aguardando autenticação via Certificado Digital... (Selecione o certificado e insira o PIN se solicitado)")
            
            logged_in = False
            for i in range(300):  # 300 * 0.2s = 60s max
                if not self.is_running:
                    return False
                current_url = page.url
                # Verificação ultra-rápida local por URL para agilizar em autoseleção
                if ("Default.aspx" in current_url or 
                    "Home.aspx" in current_url or 
                    ("COMSAT" in current_url and "Login" not in current_url)):
                    logged_in = True
                    break
                # Verificação complementar de elementos a cada 1 segundo (5 iterações)
                if i % 5 == 0:
                    if (await page.locator("a:has-text('Menu')").count() > 0 or 
                        await page.locator("text=Sair").count() > 0 or
                        await page.locator("div.ui-dialog, div[role='dialog']").count() > 0 or
                        await page.locator("select[id*='ddlRepresentacao'], select[id*='ddlContribuinte']").count() > 0):
                        logged_in = True
                        break
                await asyncio.sleep(0.2)
                
            if logged_in:
                self.log("Autenticação efetuada com sucesso!")
                # Tentar fechar popups/comunicados que surgem de imediato após o login
                await self.fechar_dialogos_alerta(page)
                return True
            else:
                self.log("Timeout de autenticação expirado ou cancelado.", logging.ERROR)
                await self.capturar_evidencia(page, "erro_login")
                return False
                
        except Exception as e:
            self.log(f"Erro durante login: {e}", logging.ERROR)
            await self.capturar_evidencia(page, "falha_login")
            return False

    async def fechar_dialogos_alerta(self, page: Page) -> bool:
        """
        Detecta e fecha qualquer caixa de diálogo ou modal de alerta visível na página.
        """
        try:
            # Seletores para diálogos jQuery UI ou caixas de diálogo genéricas (com role="dialog")
            seletor_dialogo = "div.ui-dialog, div[role='dialog'], .modal-dialog"
            dialogo = page.locator(seletor_dialogo).first
            
            if await dialogo.count() > 0:
                # Pequena pausa para garantir a renderização e transição do modal
                await asyncio.sleep(0.5)
                if await dialogo.is_visible():
                    self.log("Caixa de diálogo/alerta detectada. Fechando automaticamente...")
                    
                    # Seletores resilientes para botões comuns de fechamento
                    btn_ok = dialogo.locator("button:has-text('Ok'), button:has-text('OK'), button:has-text('Fechar'), button:has-text('Confirmar'), input[value='Ok'], input[value='OK']")
                    btn_close_icon = dialogo.locator(".ui-dialog-titlebar-close, button[title='Close']")
                    
                    if await btn_ok.count() > 0 and await btn_ok.first.is_visible():
                        await btn_ok.first.click()
                        self.log("Alerta fechado via botão 'Ok/Fechar'.")
                    elif await btn_close_icon.count() > 0 and await btn_close_icon.first.is_visible():
                        await btn_close_icon.first.click()
                        self.log("Alerta fechado via ícone de fechar (X).")
                    else:
                        btn_qualquer = dialogo.locator(".ui-dialog-buttonset button, button").first
                        if await btn_qualquer.count() > 0 and await btn_qualquer.is_visible():
                            await btn_qualquer.click()
                            self.log("Alerta fechado via botão genérico.")
                    
                    # Pequeno intervalo para o fechamento do elemento no DOM
                    await asyncio.sleep(0.5)
                    return True
            return False
        except Exception as e:
            self.log(f"Aviso ao tentar fechar diálogo de alerta: {e}", logging.WARNING)
            return False

    async def alternar_cnpj(self, page: Page, cnpj: str) -> bool:
        """
        Alterna a representação do CNPJ ativo no portal.
        Normalmente, existe um Dropdown na barra superior ou menu esquerdo para selecionar a filial.
        """
        self.log(f"Selecionando CNPJ ativo: {cnpj}")
        try:
            # Tenta fechar qualquer diálogo pendente antes de alternar
            await self.fechar_dialogos_alerta(page)
            
            # 1. Procurar dropdown de empresas/representações
            # Geralmente é um select de id ddlRepresentações ou semelhante no topo
            ddl_representacao = page.locator("select[id*='ddlRepresentacao'], select[id*='ddlContribuinte']")
            
            if await ddl_representacao.count() > 0:
                # Obter opções e procurar a que casa com o CNPJ
                options = await ddl_representacao.locator("option").all_inner_texts()
                target_value = None
                
                # Procurar valor da option contendo o CNPJ limpo
                cnpj_clean = "".join(filter(str.isdigit, cnpj))
                for i in range(len(options)):
                    option_text = "".join(filter(str.isdigit, options[i]))
                    if cnpj_clean in option_text:
                        # Obter o atributo 'value' da option correspondente
                        target_value = await ddl_representacao.locator("option").nth(i).get_attribute("value")
                        break
                        
                if target_value:
                    await ddl_representacao.select_option(value=target_value)
                    
                    # Trata popup de confirmação HTML (se houver) de forma ágil
                    await asyncio.sleep(0.5)
                    btn_confirm = page.locator("input[value='OK'], input[value='Fechar'], button:has-text('OK'), button:has-text('Fechar'), a:has-text('Fechar'), a[id*='btnOk'], a[id*='btnFechar'], input[id*='btnOk']").first
                    if await btn_confirm.count() > 0 and await btn_confirm.is_visible():
                        self.log("Popup HTML detectado na alternância de CNPJ. Confirmando automaticamente...")
                        await btn_confirm.click()
                    
                    # Também checa caixas de diálogo jQuery UI residuais após alternância
                    await self.fechar_dialogos_alerta(page)
                        
                    # Aguardar recarga da página
                    await page.wait_for_load_state("networkidle")
                    
                    # Checa novamente após a recarga completa da página
                    await self.fechar_dialogos_alerta(page)
                    
                    self.log(f"CNPJ {cnpj} selecionado com sucesso!")
                    await asyncio.sleep(self.request_delay)
                    return True
                else:
                    self.log(f"CNPJ {cnpj} não encontrado na lista de representações.", logging.WARNING)
                    return False
            else:
                # Caso não haja dropdown de alternância, assume que o login já cai no CNPJ correto
                self.log("Dropdown de alternância de CNPJ não detectado. Prosseguindo...")
                return True
        except Exception as e:
            self.log(f"Erro ao alternar CNPJ: {e}", logging.ERROR)
            return False

    async def capturar_series_sat(self, page: Page) -> List[str]:
        """Navega em Parametrização -> Equipamento e extrai os números de série SAT ativos."""
        self.log("Iniciando captura de números de série SAT...")
        series = []
        try:
            # Navegação no menu superior dinâmico (Hover -> Click)
            # Parametrização -> Equipamento -> Consultar Parâmetros Equipamento SAT
            await page.locator("a:has-text('Parametrização')").hover()
            await asyncio.sleep(0.5)
            await page.locator("a:has-text('Equipamento')").hover()
            await asyncio.sleep(0.5)
            await page.locator("a:has-text('Consultar Parâmetros')").click()
            await page.wait_for_load_state("networkidle")
            
            # Clicar em Pesquisar para trazer todos
            btn_pesquisar = page.locator("input[id*='btnPesquisar']")
            if await btn_pesquisar.count() > 0:
                await btn_pesquisar.click()
                await page.wait_for_load_state("networkidle")
                
            # Ler tabela de resultados
            # Geralmente é uma GridView de id grvEquipamento ou table
            linhas = await page.locator("table[id*='grvEquipamento'] tr, table[id*='grid'] tr").all()
            for linha in linhas[1:]:  # Ignorar cabeçalho
                colunas = await linha.locator("td").all_inner_texts()
                if len(colunas) > 1:
                    # O número de série costuma ser a primeira ou segunda coluna de texto numérico com 9 dígitos
                    for col in colunas:
                        col_clean = col.strip()
                        if col_clean.isdigit() and len(col_clean) == 9:
                            series.append(col_clean)
                            
            # Remover duplicados
            series = list(set(series))
            self.log(f"Encontrados {len(series)} equipamentos SAT ativos: {series}")
            return series
        except Exception as e:
            self.log(f"Erro ao capturar números de série: {e}", logging.ERROR)
            return []

    async def navegar_para_consulta_lotes(self, page: Page) -> bool:
        """Navega no menu superior dinâmico: Cupons -> Consulta Lotes Enviados."""
        try:
            await page.locator("a:has-text('Cupons')").hover()
            await asyncio.sleep(0.5)
            await page.locator("a:has-text('Consulta Lotes')").click()
            await page.wait_for_load_state("networkidle")
            return True
        except Exception as e:
            self.log(f"Erro ao navegar para consulta de lotes: {e}", logging.ERROR)
            return False

    async def preencher_filtros_lote(self, page: Page, serie: str, start_date: datetime, end_date: datetime) -> bool:
        """Preenche o formulário de filtros para a busca de lotes SAT."""
        try:
            # Preencher Número de Série
            txt_serie = page.locator("input[id*='txtNumeroSerie'], select[id*='ddlEquipamento']")
            if await txt_serie.count() > 0:
                if await txt_serie.first.evaluate("node => node.tagName") == "SELECT":
                    await txt_serie.first.select_option(label=serie)
                else:
                    await txt_serie.first.fill(serie)
                    
            # Preencher Datas
            txt_data_ini = page.locator("input[id*='txtDataInicio'], input[id*='txtDataIni']")
            txt_data_fim = page.locator("input[id*='txtDataFim']")
            
            if await txt_data_ini.count() > 0:
                await txt_data_ini.first.fill(start_date.strftime("%d/%m/%Y"))
            if await txt_data_fim.count() > 0:
                await txt_data_fim.first.fill(end_date.strftime("%d/%m/%Y"))
                
            # Preencher Horas Fixas
            txt_hora_ini = page.locator("input[id*='txtHoraInicio'], input[id*='txtHoraIni']")
            txt_hora_fim = page.locator("input[id*='txtHoraFim']")
            
            if await txt_hora_ini.count() > 0:
                await txt_hora_ini.first.fill("00:00")
            if await txt_hora_fim.count() > 0:
                await txt_hora_fim.first.fill("23:59")
                
            # Clicar em Pesquisar
            btn_pesquisar = page.locator("input[id*='btnPesquisar'], input[id*='btnConsultar']")
            await btn_pesquisar.click()
            await page.wait_for_load_state("networkidle")
            await asyncio.sleep(self.request_delay)
            return True
            
        except Exception as e:
            self.log(f"Erro ao preencher filtros: {e}", logging.ERROR)
            return False

    async def processar_pagina_downloads(self, page: Page, cnpj: str, serie: str, pagina_atual: int) -> int:
        """
        Varre todos os links de download de XML na página ativa da GridView,
        valida os arquivos fisicamente e os organiza em pastas.
        """
        downloaded_count = 0
        
        # Selecionar botões ou links que acionam downloads
        # Normalmente são links com ícones de disquete, seta ou texto "Download"
        download_links = await page.locator("a[id*='lnkDownload'], input[value='Download'], a:has-text('Download')").all()
        
        if not download_links:
            self.log("Nenhum cupom disponível para download nesta página.")
            return 0
            
        self.log(f"Processando {len(download_links)} possíveis downloads na página {pagina_atual}...")
        
        for idx in range(len(download_links)):
            if not self.is_running:
                break
                
            # Executar verificação especial de recuperação automática de sessão antes de cada download
            # Se fomos deslogados ou ejetaods para a Home, recuperamos!
            recuperou = await self.verificar_e_recuperar_sessao(page, cnpj, serie)
            if recuperou:
                # Se reiniciou, re-busca as referências e re-posiciona
                download_links = await page.locator("a[id*='lnkDownload'], input[value='Download'], a:has-text('Download')").all()
                if idx >= len(download_links):
                    break
                    
            try:
                # 1. Configurar escuta do evento de download no Playwright
                link = download_links[idx]
                
                async with page.expect_download(timeout=15000) as download_info:
                    await link.click()
                    
                download = await download_info.value
                
                # 2. Salvar em pasta temporária
                temp_filename = f"temp_{idx}_{int(datetime.now().timestamp())}.xml"
                temp_path = self.download_folder / "temp" / temp_filename
                await download.save_as(temp_path)
                
                # 3. Validar integridade do XML e extrair Chave de Acesso
                chave = self.validar_e_extrair_chave(temp_path)
                
                if chave:
                    # 4. Estruturar diretório final: /downloads/CNPJ/ANO/MES/DIA/
                    ano = chave[2:4]
                    mes = chave[4:6]
                    dia = datetime.now().strftime("%d") # SAT não tem o dia explícito na chave, usamos o dia do download ou parseamos do XML
                    
                    # Parsear data de emissão real do XML para organizar com perfeição
                    data_emissao = self.extrair_data_emissao_xml(temp_path)
                    if data_emissao:
                        ano = data_emissao.strftime("%Y")
                        mes = data_emissao.strftime("%m")
                        dia = data_emissao.strftime("%d")
                    else:
                        ano = f"20{ano}"
                        
                    final_dir = self.download_folder / cnpj / ano / mes / dia
                    final_dir.mkdir(parents=True, exist_ok=True)
                    
                    final_path = final_dir / f"{chave}.xml"
                    
                    # Se arquivo já existe, deleta o temporário e pula para evitar reprocessamento
                    if final_path.exists():
                        temp_path.unlink(missing_ok=True)
                    else:
                        os.replace(temp_path, final_path)
                        self.log(f"XML baixado e validado com sucesso: {chave}.xml")
                        downloaded_count += 1
                else:
                    self.log("Download rejeitado: Arquivo corrompido ou formato XML inválido.", logging.WARNING)
                    temp_path.unlink(missing_ok=True)
                    
                await asyncio.sleep(self.request_delay)
                
            except Exception as e:
                self.log(f"Falha na tentativa de download do item {idx + 1}: {e}", logging.ERROR)
                
        return downloaded_count

    async def verificar_e_recuperar_sessao(self, page: Page, cnpj: str, serie: str) -> bool:
        """
        Verifica se a sessão expirou ou redirecionou de volta para a Home.
        Caso ocorra desvio, re-loga, troca o CNPJ, navega para a tela de lotes e retorna.
        """
        current_url = page.url
        # Padrões indicadores de desconexão ou ejeção
        if "Home.aspx" in current_url or "Account/Login" in current_url or await page.locator("text=Acesso Expirado").count() > 0:
            self.log("⚠️ Redirecionamento inesperado detectado! Iniciando recuperação automática de sessão...", logging.WARNING)
            await self.capturar_evidencia(page, "ejeção_sessao")
            
            # Recomeçar
            logged = await self.realizar_login(page)
            if logged:
                await self.alternar_cnpj(page, cnpj)
                await self.navegar_para_consulta_lotes(page)
                # O preenchimento do filtro e navegação das páginas será retomado pelo loop principal
                return True
        return False

    def validar_e_extrair_chave(self, file_path: Path) -> Optional[str]:
        """
        Abre o arquivo baixado, checa se possui tamanho > 0 bytes e
        extrai o atributo 'Id' da tag CFe (ex: Id="CFe352605...").
        """
        if not file_path.exists() or file_path.stat().st_size == 0:
            return None
            
        try:
            tree = ET.parse(file_path)
            root = tree.getroot()
            
            # O elemento raiz deve ser infCFe ou CFe
            tag_name = root.tag.split('}')[-1] # Remove namespaces eventuais
            
            if tag_name == "CFe":
                infCfe = root.find(".//{*}infCFe")
                if infCfe is not None and "Id" in infCfe.attrib:
                    # Remove o prefixo "CFe" para obter apenas a chave numérica de 44 dígitos
                    chave = infCfe.attrib["Id"].replace("CFe", "")
                    if len(chave) == 44 and chave.isdigit():
                        return chave
            return None
        except Exception:
            return None

    def extrair_data_emissao_xml(self, file_path: Path) -> Optional[datetime]:
        """Extrai a data de emissão (dEmi) do XML do SAT."""
        try:
            tree = ET.parse(file_path)
            root = tree.getroot()
            dEmi_el = root.find(".//{*}dEmi")
            if dEmi_el is not None and dEmi_el.text:
                # Formato yyyymmdd
                return datetime.strptime(dEmi_el.text, "%Y%m%d")
        except Exception:
            pass
        return None

    async def capturar_evidencia(self, page: Page, name_prefix: str):
        """Tira screenshot e salva o HTML da página em caso de erro."""
        try:
            evidences_dir = Path(__file__).resolve().parent.parent / "logs" / "evidencias"
            evidences_dir.mkdir(parents=True, exist_ok=True)
            
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            screenshot_path = evidences_dir / f"{name_prefix}_{timestamp}.png"
            html_path = evidences_dir / f"{name_prefix}_{timestamp}.html"
            
            await page.screenshot(path=screenshot_path)
            html_content = await page.content()
            html_path.write_text(html_content, encoding='utf-8')
            
            self.log(f"Evidência de falha capturada: {screenshot_path.name}")
        except Exception as e:
            logger.error(f"Erro ao capturar evidência: {e}")

    async def run(self):
        """Inicia a execução da fila de automação assíncrona do robô."""
        self.is_running = True
        
        async with async_playwright() as p:
            try:
                self.browser, self.context = await self.init_browser(p)
                page = await self.context.new_page()
                
                # Auto-confirmar popups nativos do navegador de forma ágil
                async def handle_dialog(dialog):
                    self.log(f"Popup JS detectado: '{dialog.message}'. Confirmando automaticamente...")
                    await dialog.accept()
                page.on("dialog", lambda d: asyncio.create_task(handle_dialog(d)))
                
                # 1. Realizar Login Inicial
                if not await self.realizar_login(page):
                    self.log("Falha na autenticação inicial. Parando robô.", logging.ERROR)
                    self.is_running = False
                    return
                    
                # Loop infinito de processamento da fila persistente
                while self.is_running:
                    # Obter próxima atividade no banco
                    with self.session_factory() as session:
                        job = StateManager.get_next_job(session)
                        if not job:
                            self.log("Fila de processamento vazia! Todos os lotes foram concluídos.")
                            break
                        
                        self.current_job_id = job.id
                        cnpj = job.cnpj
                        serie = job.numero_serie_sat
                        data_ini = job.periodo_inicio
                        data_fim = job.periodo_fim
                        pagina_alvo = job.pagina_atual
                        
                    self.log(f"Iniciando Trabalho ID {self.current_job_id} | CNPJ: {cnpj} | Série: {serie or 'A capturar'} | Período: {data_ini.strftime('%d/%m')} a {data_fim.strftime('%d/%m')}")
                    
                    try:
                        # 2. Alternar CNPJ
                        if not await self.alternar_cnpj(page, cnpj):
                            raise Exception(f"Não foi possível selecionar o CNPJ {cnpj}.")
                            
                        # 3. Se número de série do SAT estiver vazio, capturá-los do portal
                        if not serie:
                            series = await self.capturar_series_sat(page)
                            if not series:
                                raise Exception(f"Nenhum equipamento SAT ativo encontrado para o CNPJ {cnpj}.")
                            
                            # Se encontrou séries, duplicar/ramificar os trabalhos na fila para cada número de série!
                            # E marcar o trabalho genérico inicial como CONCLUIDO
                            with self.session_factory() as session:
                                for s in series:
                                    # Cria um trabalho idêntico porém focado na série exata
                                    new_job = QueueProgress(
                                        cnpj=cnpj,
                                        periodo_inicio=data_ini,
                                        periodo_fim=data_fim,
                                        numero_serie_sat=s,
                                        status="PENDENTE"
                                    )
                                    session.add(new_job)
                                StateManager.update_job_status(session, self.current_job_id, "CONCLUIDO", xmls_count=0)
                            self.log(f"Trabalho ID {self.current_job_id} ramificado em {len(series)} séries SAT individuais. Concluindo ramificação.")
                            continue
                        
                        # 4. Navegar para o menu de consulta de lotes
                        await self.navegar_para_consulta_lotes(page)
                        
                        # 5. Aplicar filtros
                        await self.preencher_filtros_lote(page, serie, data_ini, data_fim)
                        
                        # Verificar se gerou erro "Nenhum registro encontrado"
                        if await page.locator("text=Nenhum registro encontrado, Nenhum registro").count() > 0 or await page.locator("text=Nenhum documento encontrado").count() > 0:
                            self.log("Nenhum cupom SAT emitido neste período de 2 dias. Pulando bloco.", logging.WARNING)
                            with self.session_factory() as session:
                                StateManager.update_job_status(session, self.current_job_id, "CONCLUIDO", xmls_count=0)
                            continue
                            
                        # 6. Navegar até a página correta caso tenha caído a sessão e recuperado
                        if pagina_alvo > 1:
                            self.log(f"Avançando até a página salva de progresso: {pagina_alvo}...")
                            # Lógica para clicar nas páginas da gridview
                            # Geralmente um link de texto contendo o número da página ou imagem 'next'
                            # Implementamos busca dinâmica pelo número da página na paginação
                            btn_pag = page.locator(f"a:has-text('{pagina_alvo}')")
                            if await btn_pag.count() > 0:
                                await btn_pag.first.click()
                                await page.wait_for_load_state("networkidle")
                                
                        # 7. Iniciar loop de download de XMLs da GridView
                        total_baixados = 0
                        while self.is_running:
                            xmls_da_pagina = await self.processar_pagina_downloads(page, cnpj, serie, pagina_alvo)
                            total_baixados += xmls_da_pagina
                            
                            # Atualizar progresso parcial de página no banco para segurança extrema
                            with self.session_factory() as session:
                                job_db = session.query(QueueProgress).filter(QueueProgress.id == self.current_job_id).first()
                                if job_db:
                                    job_db.pagina_atual = pagina_alvo
                                    job_db.xmls_baixados = total_baixados
                                    session.commit()
                                    
                            # Tentar avançar página
                            # Geralmente a paginação tem botões numéricos ou um link de texto 'Próximo' ou '>'
                            btn_proximo = page.locator("a:has-text('Próxima'), a:has-text('Proxima'), a:has-text('>'), a:has-text('...')").last
                            
                            # Verificar se existe uma página posterior ativa na gridview
                            # (Evitar clicar em próximo se estivermos na última)
                            tem_proxima = False
                            if await btn_proximo.count() > 0:
                                # Garantir que o link do botão Próximo está ativo e visível
                                if await btn_proximo.is_visible() and "disabled" not in (await btn_proximo.get_attribute("class") or ""):
                                    tem_proxima = True
                                    
                            if tem_proxima:
                                pagina_alvo += 1
                                self.log(f"Avançando para a página {pagina_alvo} de cupons...")
                                await btn_proximo.click()
                                await page.wait_for_load_state("networkidle")
                                await asyncio.sleep(self.request_delay)
                            else:
                                self.log(f"Fim das páginas de download para Série {serie} no período.")
                                break
                                
                        # Finalizar trabalho com sucesso
                        with self.session_factory() as session:
                            StateManager.update_job_status(session, self.current_job_id, "CONCLUIDO", xmls_count=total_baixados)
                            
                    except Exception as e:
                        self.log(f"Erro ao processar lote ID {self.current_job_id}: {e}", logging.ERROR)
                        await self.capturar_evidencia(page, f"erro_lote_{self.current_job_id}")
                        with self.session_factory() as session:
                            StateManager.update_job_status(session, self.current_job_id, "ERRO", error_msg=str(e))
                            
            except Exception as outer_e:
                self.log(f"Erro fatal no motor de automação SAT: {outer_e}", logging.ERROR)
            finally:
                self.is_running = False
                try:
                    if self.context:
                        await self.context.close()
                except Exception:
                    pass
                # browser é None quando usamos launch_persistent_context
                try:
                    if self.browser:
                        await self.browser.close()
                except Exception:
                    pass
                self.cleanup()
                self.log("Navegador de automação finalizado.")

    def stop(self):
        """Solicita a interrupção segura do robô."""
        if self.is_running:
            self.log("Parada solicitada pelo usuário. Concluindo operações pendentes...")
            self.is_running = False

    def cleanup(self):
        """
        Limpa o perfil temporário do Chrome criado para a sessão de automação.
        O arquivo Preferences é deletado para que não persista configurações entre sessões.
        """
        try:
            profile_dir = Path(__file__).resolve().parent.parent / "logs" / "_chrome_profile"
            pref_file = profile_dir / "Default" / "Preferences"
            if pref_file.exists():
                pref_file.unlink()
            self.log("Perfil temporário do Chrome limpo com sucesso.")
        except Exception as e:
            self.log(f"Aviso: Não foi possível limpar o perfil temporário ({e}).", logging.WARNING)

