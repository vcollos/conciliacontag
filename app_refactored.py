"""
Aplicação Streamlit Refatorada - Processador de Extratos Financeiros
"""
import streamlit as st
import pandas as pd
from typing import List, Dict, Optional
import logging

# Importações dos módulos refatorados
from config import UI_CONFIG, validate_environment, logger
from database import CompanyRepository, TransactionRepository, ReconciliationRepository
from processors import OFXProcessor, FrancesinhaProcessor, DataExporter
from business_logic import ReconciliationProcessor, RuleManager
from components import (
    StateManager, CompanySelector, CompanyForm, FileUploader, 
    DataTable, FilterableDataTable, BatchEditor, DownloadButton, 
    SaveButton, ProgressIndicator, NotificationManager
)
from validation import ValidationManager

# Configuração da página
st.set_page_config(
    page_title=UI_CONFIG['page_title'],
    page_icon=UI_CONFIG['page_icon'],
    layout=UI_CONFIG['layout'],
    initial_sidebar_state=UI_CONFIG['initial_sidebar_state']
)

class AppController:
    """Controlador principal da aplicação"""
    
    def __init__(self):
        self.state_manager = StateManager()
        self.notification_manager = NotificationManager()
        self.reconciliation_processor = ReconciliationProcessor()
        
        # Inicializa estado da sessão
        self.state_manager.initialize_session_state()
        
        # Valida ambiente
        if not validate_environment():
            st.error("Configuração de ambiente inválida. Verifique o arquivo .env")
            st.stop()
    
    def run(self):
        """Executa a aplicação"""
        try:
            # Renderiza sidebar
            self._render_sidebar()
            
            # Renderiza conteúdo principal
            self._render_main_content()
            
        except Exception as e:
            logger.error(f"Erro na execução da aplicação: {e}")
            self.notification_manager.show_error("Erro inesperado na aplicação. Verifique os logs.")
    
    def _render_sidebar(self):
        """Renderiza a barra lateral"""
        with st.sidebar:
            st.title("Gestão de Empresas")
            
            # Carrega empresas
            companies = CompanyRepository.get_all_companies()
            
            if st.session_state.modo_sidebar == 'selecionar':
                self._render_company_selector(companies)
            elif st.session_state.modo_sidebar == 'cadastrar':
                self._render_company_form()
    
    def _render_company_selector(self, companies: List[Dict]):
        """Renderiza seletor de empresas"""
        def on_company_change():
            # Callback para mudança de empresa
            pass
        
        company_selector = CompanySelector(companies, on_company_change)
        selected_company = company_selector.render()
        
        if st.button("Cadastrar"):
            st.session_state.modo_sidebar = 'cadastrar'
            st.rerun()
    
    def _render_company_form(self):
        """Renderiza formulário de cadastro"""
        def on_save(nome: str, razao_social: str, cnpj: str) -> bool:
            # Valida dados
            is_valid, errors = ValidationManager.validate_company_registration(nome, razao_social, cnpj)
            if not is_valid:
                for error in errors:
                    self.notification_manager.show_error(error)
                return False
            
            # Salva empresa
            success = CompanyRepository.create_company(nome, razao_social, cnpj)
            if success:
                self.notification_manager.show_success(f"Empresa '{nome}' cadastrada!")
                return True
            return False
        
        def on_cancel():
            st.session_state.modo_sidebar = 'selecionar'
            st.rerun()
        
        company_form = CompanyForm(on_save, on_cancel)
        if company_form.render():
            st.session_state.modo_sidebar = 'selecionar'
            st.rerun()
    
    def _render_main_content(self):
        """Renderiza conteúdo principal"""
        # Verifica se empresa está selecionada
        if not st.session_state.get('empresa_ativa'):
            st.header("🏢 Nenhuma empresa selecionada")
            st.info("Por favor, selecione ou cadastre uma empresa na barra lateral para começar.")
            st.stop()
        
        # Exibe empresa ativa
        st.header(f"🏢 Empresa Ativa: {st.session_state['empresa_ativa']['nome']}")
        
        # Define abas
        tab_processamento, tab_historico = st.tabs(["Processamento de Arquivos", "Histórico de Dados"])
        
        with tab_processamento:
            self._render_processing_tab()
        
        with tab_historico:
            self._render_history_tab()
    
    def _render_processing_tab(self):
        """Renderiza aba de processamento"""
        st.title("💰 Processador de Extratos Financeiros")
        st.markdown("### Converte arquivos OFX (extratos) e XLS (francesinhas) para CSV")
        st.markdown("---")
        
        # Layout em colunas
        col1, col2 = st.columns(2)
        
        with col1:
            self._render_ofx_section()
        
        with col2:
            self._render_francesinha_section()
        
        # Seção de conciliação
        st.markdown("---")
        self._render_reconciliation_section()
    
    def _render_ofx_section(self):
        """Renderiza seção de processamento OFX"""
        st.subheader("📊 Extratos OFX")
        
        # Upload de arquivos
        ofx_uploader = FileUploader(['ofx'], "Envie arquivos OFX", "ofx_uploader")
        ofx_files = ofx_uploader.render()
        
        if ofx_files:
            self.notification_manager.show_success(f"{len(ofx_files)} arquivo(s) OFX carregado(s)")
            
            if st.button("Processar OFX", type="primary"):
                self._process_ofx_files(ofx_files)
        
        # Exibe resultados
        if st.session_state.get('df_extratos_final') is not None:
            self._display_ofx_results()
    
    def _process_ofx_files(self, files: List):
        """Processa arquivos OFX"""
        with ProgressIndicator("Processando arquivos OFX..."):
            df_result = OFXProcessor.process_multiple_ofx_files(files)
            
            if not df_result.empty:
                # Valida resultado
                is_valid, errors = ValidationManager.validate_processing_result(df_result, 'OFX')
                if not is_valid:
                    for error in errors:
                        self.notification_manager.show_error(error)
                    return
                
                st.session_state['df_extratos_final'] = df_result
                self.notification_manager.show_success(f"✅ {len(df_result)} transações processadas no total.")
            else:
                self.notification_manager.show_warning("Nenhum arquivo OFX foi processado com sucesso.")
    
    def _display_ofx_results(self):
        """Exibe resultados do processamento OFX"""
        df_extratos = st.session_state['df_extratos_final']
        
        st.markdown("#### Visualização dos Dados OFX")
        
        # Filtro por arquivo
        arquivos_processados = ['Todos'] + df_extratos['arquivo_origem'].unique().tolist()
        arquivo_selecionado = st.selectbox("Mostrar transações do arquivo:", arquivos_processados, key="ofx_select")
        
        if arquivo_selecionado == 'Todos':
            df_para_mostrar = df_extratos
        else:
            df_para_mostrar = df_extratos[df_extratos['arquivo_origem'] == arquivo_selecionado]
        
        # Tabela de dados
        data_table = DataTable(df_para_mostrar)
        data_table.render()
        
        # Botões de ação
        col_down_ofx, col_save_ofx = st.columns(2)
        
        with col_down_ofx:
            download_btn = DownloadButton(
                df_extratos, 
                "extratos_consolidados.csv", 
                "⬇️ Download CSV (Todos os Arquivos)"
            )
            download_btn.render()
        
        with col_save_ofx:
            self._render_ofx_save_button(df_extratos)
    
    def _render_ofx_save_button(self, df_extratos: pd.DataFrame):
        """Renderiza botão de salvamento OFX"""
        empresa_id = st.session_state.get('empresa_ativa', {}).get('id')
        
        def save_ofx_data(df: pd.DataFrame, empresa_id: int) -> bool:
            with ProgressIndicator("Salvando transações OFX..."):
                registros_salvos = TransactionRepository.save_imported_data(
                    df, 'OFX', empresa_id, 1  # TODO: contar arquivos corretamente
                )
                if registros_salvos > 0:
                    self.notification_manager.show_success(f"💾 Dados salvos! {registros_salvos} transações OFX registradas.")
                    return True
                return False
        
        save_btn = SaveButton(
            "💾 Salvar Extratos OFX no Banco de Dados",
            save_ofx_data,
            TransactionRepository.check_existing_files
        )
        
        if save_btn.render(df_extratos, empresa_id, 'ofx_overwrite_confirmed'):
            st.session_state.ofx_overwrite_confirmed = False
    
    def _render_francesinha_section(self):
        """Renderiza seção de processamento Francesinha"""
        st.subheader("📋 Gerar Francesinha Completa")
        
        # Upload de arquivos
        francesinha_uploader = FileUploader(['xls', 'xlsx'], "Envie arquivos de francesinha (XLS)", "xls_uploader")
        francesinha_files = francesinha_uploader.render()
        
        if francesinha_files:
            self.notification_manager.show_success(f"{len(francesinha_files)} arquivo(s) de francesinha carregado(s)")
            
            if st.button("Gerar Francesinha Completa", type="primary"):
                self._process_francesinha_files(francesinha_files)
        
        # Exibe resultados
        if st.session_state.get('df_francesinhas_final') is not None:
            self._display_francesinha_results()
    
    def _process_francesinha_files(self, files: List):
        """Processa arquivos de Francesinha"""
        with ProgressIndicator("Processando arquivos de francesinha..."):
            df_result, interest_count = FrancesinhaProcessor.process_multiple_francesinha_files(files)
            
            if not df_result.empty:
                # Valida resultado
                is_valid, errors = ValidationManager.validate_processing_result(df_result, 'Francesinha')
                if not is_valid:
                    for error in errors:
                        self.notification_manager.show_error(error)
                    return
                
                st.session_state['df_francesinhas_final'] = df_result
                st.session_state['linhas_mora_count'] = interest_count
                self.notification_manager.show_success(f"✅ {len(df_result)} registros processados (incluindo {interest_count} de juros).")
            else:
                self.notification_manager.show_warning("Nenhum arquivo de Francesinha foi processado com sucesso.")
    
    def _display_francesinha_results(self):
        """Exibe resultados do processamento Francesinha"""
        df_francesinhas = st.session_state['df_francesinhas_final']
        linhas_mora_count = st.session_state.get('linhas_mora_count', 0)
        
        st.markdown("#### Visualização dos Dados da Francesinha")
        
        # Tabela de dados
        data_table = DataTable(df_francesinhas)
        data_table.render()
        
        # Botões de ação
        col_down_fran, col_save_fran = st.columns(2)
        
        with col_down_fran:
            download_btn = DownloadButton(
                df_francesinhas, 
                "francesinha_completa.csv", 
                "⬇️ Download Francesinha Completa"
            )
            download_btn.render()
        
        with col_save_fran:
            self._render_francesinha_save_button(df_francesinhas)
    
    def _render_francesinha_save_button(self, df_francesinhas: pd.DataFrame):
        """Renderiza botão de salvamento Francesinha"""
        empresa_id = st.session_state.get('empresa_ativa', {}).get('id')
        
        def save_francesinha_data(df: pd.DataFrame, empresa_id: int) -> bool:
            with ProgressIndicator("Salvando dados da francesinha..."):
                registros_salvos = TransactionRepository.save_imported_data(
                    df, 'Francesinha', empresa_id, 1  # TODO: contar arquivos corretamente
                )
                if registros_salvos > 0:
                    self.notification_manager.show_success(f"💾 Dados salvos! {registros_salvos} registros de francesinha salvos.")
                    return True
                return False
        
        save_btn = SaveButton(
            "💾 Salvar Francesinhas no Banco de Dados",
            save_francesinha_data,
            TransactionRepository.check_existing_files
        )
        
        if save_btn.render(df_francesinhas, empresa_id, 'fran_overwrite_confirmed'):
            st.session_state.fran_overwrite_confirmed = False
    
    def _render_reconciliation_section(self):
        """Renderiza seção de conciliação"""
        st.subheader("🚀 Conciliação Contábil")
        
        # Verifica se há dados para conciliação
        df_ofx = st.session_state.get('df_extratos_final')
        df_francesinha = st.session_state.get('df_francesinhas_final', pd.DataFrame())
        
        if df_ofx is not None:
            if st.button("Iniciar Conciliação", type="primary"):
                self._process_reconciliation(df_ofx, df_francesinha)
        elif df_francesinha is not None and not df_francesinha.empty and df_ofx is None:
            st.warning("É necessário processar o arquivo OFX para habilitar a conciliação.")
        else:
            st.warning("É necessário processar os arquivos OFX e de Francesinha para habilitar a conciliação.")
        
        # Exibe resultados da conciliação
        if st.session_state.get('df_conciliacao') is not None:
            self._display_reconciliation_results()
    
    def _process_reconciliation(self, df_ofx: pd.DataFrame, df_francesinha: pd.DataFrame):
        """Processa conciliação"""
        with ProgressIndicator("Processando conciliação..."):
            # Cria dataset de conciliação
            df_conciliacao = self.reconciliation_processor.create_reconciliation_dataset(df_ofx, df_francesinha)
            
            if not df_conciliacao.empty:
                # Aplica regras salvas
                empresa_id = st.session_state.get('empresa_ativa', {}).get('id')
                if empresa_id:
                    # TODO: Implementar carregamento de regras salvas
                    pass
                
                st.session_state['df_conciliacao'] = df_conciliacao
                self.notification_manager.show_success("✅ Dataset de conciliação gerado!")
            else:
                self.notification_manager.show_warning("Nenhum dado foi processado para conciliação.")
    
    def _display_reconciliation_results(self):
        """Exibe resultados da conciliação"""
        st.header("2. Revise e Edite sua Conciliação")
        
        df_conciliacao = st.session_state['df_conciliacao']
        
        # Tabela com filtro
        filterable_table = FilterableDataTable(df_conciliacao)
        edited_df, filtered_df, filter_text = filterable_table.render_with_filter({
            "débito": st.column_config.TextColumn(),
            "crédito": st.column_config.TextColumn(),
            "histórico": st.column_config.TextColumn(),
            "data": st.column_config.TextColumn(),
            "valor": st.column_config.TextColumn(disabled=True),
            "complemento": st.column_config.TextColumn(disabled=True),
            "origem": st.column_config.TextColumn(disabled=True),
        })
        
        # Atualiza DataFrame com edições
        if 'df_conciliacao' in st.session_state:
            st.session_state['df_conciliacao'].update(edited_df)
        
        # Editor em lote
        st.markdown("---")
        st.subheader("🖋️ Edição em Lote")
        
        batch_editor = BatchEditor(st.session_state['df_conciliacao'])
        batch_editor.render()
        
        # Botões de ação
        st.markdown("---")
        df_para_salvar = st.session_state['df_conciliacao'].drop(columns=['selecionar'])
        
        col_down, col_save = st.columns(2)
        
        with col_down:
            download_btn = DownloadButton(
                df_para_salvar, 
                "conciliacao_contabil.csv", 
                "⬇️ Download CSV de Conciliação",
                remove_columns=['origem']
            )
            download_btn.render()
        
        with col_save:
            self._render_reconciliation_save_button(df_para_salvar)
    
    def _render_reconciliation_save_button(self, df_conciliacao: pd.DataFrame):
        """Renderiza botão de salvamento da conciliação"""
        empresa_id = st.session_state.get('empresa_ativa', {}).get('id')
        
        def save_reconciliation_data(df: pd.DataFrame, empresa_id: int) -> bool:
            # Valida dados
            is_valid, errors = ValidationManager.validate_reconciliation_result(df)
            if not is_valid:
                for error in errors:
                    self.notification_manager.show_error(error)
                return False
            
            with ProgressIndicator("Salvando conciliação final..."):
                registros_salvos = ReconciliationRepository.save_reconciliation(df, empresa_id)
                if registros_salvos > 0:
                    self.notification_manager.show_success(f"💾 Conciliação salva! {registros_salvos} lançamentos registrados no banco de dados.")
                    return True
                return False
        
        save_btn = SaveButton(
            "💾 Salvar Conciliação Final no DB",
            save_reconciliation_data,
            ReconciliationRepository.check_existing_reconciliation
        )
        
        save_btn.render(df_conciliacao, empresa_id, 'reconciliation_overwrite_confirmed')
    
    def _render_history_tab(self):
        """Renderiza aba de histórico"""
        st.title("📚 Histórico de Dados Salvos")
        
        empresa_id = st.session_state.get('empresa_ativa', {}).get('id')
        
        if empresa_id:
            st.info("Abaixo estão os dados previamente salvos no banco de dados para a empresa ativa.")
            
            # Histórico de transações OFX
            with st.expander("Histórico de Transações (OFX)", expanded=True):
                df_hist_transacoes = ReconciliationRepository.load_historical_data(empresa_id, "transacoes")
                if not df_hist_transacoes.empty:
                    data_table = DataTable(df_hist_transacoes)
                    data_table.render()
                    
                    download_btn = DownloadButton(
                        df_hist_transacoes,
                        f"historico_transacoes_{st.session_state['empresa_ativa']['nome']}.csv",
                        "⬇️ Download Histórico de Transações"
                    )
                    download_btn.render()
                else:
                    st.write("Nenhuma transação encontrada no histórico.")
            
            # Histórico de conciliações
            with st.expander("Histórico de Conciliações Salvas", expanded=True):
                df_hist_conciliacoes = ReconciliationRepository.load_historical_data(empresa_id, "lancamentos_conciliacao")
                if not df_hist_conciliacoes.empty:
                    data_table = DataTable(df_hist_conciliacoes)
                    data_table.render()
                    
                    download_btn = DownloadButton(
                        df_hist_conciliacoes,
                        f"historico_conciliacoes_{st.session_state['empresa_ativa']['nome']}.csv",
                        "⬇️ Download Histórico de Conciliações"
                    )
                    download_btn.render()
                else:
                    st.write("Nenhuma conciliação encontrada no histórico.")
        else:
            st.warning("Selecione uma empresa para ver o histórico.")

def main():
    """Função principal da aplicação"""
    # Configuração de cache
    @st.cache_data(ttl=300)
    def load_companies():
        return CompanyRepository.get_all_companies()
    
    # Executa aplicação
    app = AppController()
    app.run()
    
    # Rodapé
    st.markdown("---")
    st.markdown("**Collos Ltda** - Processador de Extratos Financeiros")

if __name__ == "__main__":
    main() 