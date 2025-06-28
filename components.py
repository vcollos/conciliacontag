"""
Componentes reutilizáveis para a interface Streamlit
"""
import streamlit as st
import pandas as pd
from typing import List, Dict, Optional, Callable, Any
import logging

from config import logger

class StateManager:
    """Gerenciador de estado da aplicação"""
    
    @staticmethod
    def initialize_session_state():
        """Inicializa variáveis de estado da sessão"""
        if 'empresa_ativa' not in st.session_state:
            st.session_state.empresa_ativa = None
        
        if 'modo_sidebar' not in st.session_state:
            st.session_state.modo_sidebar = 'selecionar'
        
        if 'df_extratos_final' not in st.session_state:
            st.session_state.df_extratos_final = None
        
        if 'df_francesinhas_final' not in st.session_state:
            st.session_state.df_francesinhas_final = None
        
        if 'df_conciliacao' not in st.session_state:
            st.session_state.df_conciliacao = None
        
        if 'editing_enabled' not in st.session_state:
            st.session_state.editing_enabled = False
        
        if 'ofx_overwrite_confirmed' not in st.session_state:
            st.session_state.ofx_overwrite_confirmed = False
        
        if 'fran_overwrite_confirmed' not in st.session_state:
            st.session_state.fran_overwrite_confirmed = False
    
    @staticmethod
    def clear_processing_data():
        """Limpa dados de processamento da sessão"""
        keys_to_clear = [
            'df_extratos_final', 'df_francesinhas_final', 'df_conciliacao',
            'editing_enabled', 'ofx_overwrite_confirmed', 'fran_overwrite_confirmed'
        ]
        
        for key in keys_to_clear:
            if key in st.session_state:
                del st.session_state[key]

class CompanySelector:
    """Componente de seleção de empresa"""
    
    def __init__(self, companies: List[Dict], on_company_change: Callable):
        self.companies = companies
        self.on_company_change = on_company_change
    
    def render(self):
        """Renderiza o seletor de empresas"""
        company_names = [company['nome'] for company in self.companies]
        company_map = {company['nome']: company for company in self.companies}
        
        # Define índice padrão
        default_index = 0
        if (st.session_state.get('empresa_ativa') and 
            st.session_state['empresa_ativa']['nome'] in company_names):
            default_index = company_names.index(st.session_state['empresa_ativa']['nome'])
        
        selected_company_name = st.selectbox(
            "Selecione a Empresa",
            options=company_names,
            index=default_index,
            on_change=self._handle_company_change,
            key='empresa_selectbox'
        )
        
        return company_map.get(selected_company_name)
    
    def _handle_company_change(self):
        """Callback para mudança de empresa"""
        selected_company_name = st.session_state.empresa_selectbox
        if selected_company_name:
            company_map = {company['nome']: company for company in self.companies}
            st.session_state['empresa_ativa'] = company_map[selected_company_name]
            self.on_company_change()

class CompanyForm:
    """Componente de formulário de cadastro de empresa"""
    
    def __init__(self, on_save: Callable, on_cancel: Callable):
        self.on_save = on_save
        self.on_cancel = on_cancel
    
    def render(self):
        """Renderiza o formulário de cadastro"""
        with st.form("cadastro_empresa_form"):
            st.subheader("Cadastro de Nova Empresa")
            
            cnpj = st.text_input("CNPJ (apenas números)")
            razao_social = st.text_input("Razão Social")
            nome = st.text_input("Nome")
            
            if st.form_submit_button("Salvar"):
                if self._validate_form(cnpj, razao_social, nome):
                    success = self.on_save(nome, razao_social, cnpj)
                    if success:
                        st.success(f"Empresa '{nome}' cadastrada!")
                        return True
                else:
                    st.warning("Por favor, preencha todos os campos.")
        
        if st.button("Cancelar"):
            self.on_cancel()
            return True
        
        return False
    
    def _validate_form(self, cnpj: str, razao_social: str, nome: str) -> bool:
        """Valida os campos do formulário"""
        return bool(cnpj and razao_social and nome)

class FileUploader:
    """Componente de upload de arquivos"""
    
    def __init__(self, file_types: List[str], label: str, key: str, multiple: bool = True):
        self.file_types = file_types
        self.label = label
        self.key = key
        self.multiple = multiple
    
    def render(self):
        """Renderiza o componente de upload"""
        return st.file_uploader(
            self.label,
            type=self.file_types,
            accept_multiple_files=self.multiple,
            key=self.key
        )

class DataTable:
    """Componente de tabela de dados"""
    
    def __init__(self, df: pd.DataFrame, height: int = 300, hide_index: bool = True):
        self.df = df
        self.height = height
        self.hide_index = hide_index
    
    def render(self, column_config: Optional[Dict] = None):
        """Renderiza a tabela de dados"""
        return st.dataframe(
            self.df,
            use_container_width=True,
            height=self.height,
            hide_index=self.hide_index,
            column_config=column_config or {}
        )

class FilterableDataTable(DataTable):
    """Tabela de dados com filtro universal"""
    
    def __init__(self, df: pd.DataFrame, height: int = 300, hide_index: bool = True):
        super().__init__(df, height, hide_index)
    
    def render_with_filter(self, column_config: Optional[Dict] = None):
        """Renderiza tabela com filtro universal"""
        # Filtro universal
        filter_text = st.text_input(
            "🔍 Filtrar em todas as colunas:", 
            help="Digite para filtrar a tabela em tempo real."
        )
        
        # Aplica filtro
        if filter_text:
            df_str = self.df.astype(str).apply(lambda s: s.str.lower())
            filtered_indices = df_str[
                df_str.apply(lambda row: row.str.contains(filter_text.lower(), na=False).any(), axis=1)
            ].index
            filtered_df = self.df.loc[filtered_indices]
        else:
            filtered_df = self.df
        
        # Renderiza tabela filtrada
        return self.render(column_config), filtered_df, filter_text

class BatchEditor:
    """Componente de edição em lote"""
    
    def __init__(self, df: pd.DataFrame):
        self.df = df
    
    def render(self):
        """Renderiza o editor em lote"""
        selected_rows = self.df[self.df['selecionar']]
        
        if selected_rows.empty:
            st.info("Selecione uma ou mais linhas na tabela para habilitar a edição.")
            st.session_state.editing_enabled = False
            return False
        
        if not st.session_state.editing_enabled:
            if st.button("Habilitar Edição em Lote", type="secondary"):
                st.session_state.editing_enabled = True
            return False
        
        st.success(f"{len(selected_rows)} linha(s) selecionada(s). Preencha os campos abaixo e clique em 'Aplicar'.")
        
        col1, col2, col3, col4 = st.columns([2, 2, 2, 3])
        
        with col1:
            new_debit = st.text_input("Débito")
        with col2:
            new_credit = st.text_input("Crédito")
        with col3:
            new_history = st.text_input("Histórico")
        
        with col4:
            st.write("")  # Espaço para alinhamento
            col_btn1, col_btn2 = st.columns(2)
            
            with col_btn1:
                if st.button("Aplicar aos Selecionados", type="primary", use_container_width=True):
                    return self._apply_changes(selected_rows, new_debit, new_credit, new_history)
            
            with col_btn2:
                if st.button("Cancelar", use_container_width=True):
                    st.session_state.editing_enabled = False
        
        return False
    
    def _apply_changes(self, selected_rows: pd.DataFrame, debit: str, credit: str, history: str) -> bool:
        """Aplica mudanças aos registros selecionados"""
        indices_to_update = selected_rows.index
        
        if debit:
            st.session_state['df_conciliacao'].loc[indices_to_update, 'débito'] = debit
        if credit:
            st.session_state['df_conciliacao'].loc[indices_to_update, 'crédito'] = credit
        if history:
            st.session_state['df_conciliacao'].loc[indices_to_update, 'histórico'] = history
        
        st.session_state['df_conciliacao']['selecionar'] = False
        st.session_state.editing_enabled = False
        st.toast("Valores aplicados com sucesso!")
        
        return True

class DownloadButton:
    """Componente de botão de download"""
    
    def __init__(self, df: pd.DataFrame, filename: str, label: str, remove_columns: List[str] = None):
        self.df = df
        self.filename = filename
        self.label = label
        self.remove_columns = remove_columns or []
    
    def render(self):
        """Renderiza o botão de download"""
        from processors import DataExporter
        
        # Prepara dados para download
        df_for_download = DataExporter.prepare_for_download(self.df, self.remove_columns)
        csv_data = DataExporter.to_csv(df_for_download)
        
        return st.download_button(
            label=self.label,
            data=csv_data,
            file_name=self.filename,
            mime="text/csv",
            use_container_width=True
        )

class SaveButton:
    """Componente de botão de salvamento"""
    
    def __init__(self, label: str, on_save: Callable, check_existing: Callable = None):
        self.label = label
        self.on_save = on_save
        self.check_existing = check_existing
    
    def render(self, df: pd.DataFrame, empresa_id: int, overwrite_key: str):
        """Renderiza o botão de salvamento"""
        if self.check_existing:
            existing_files = self.check_existing(empresa_id, df)
            
            if existing_files and not st.session_state.get(overwrite_key, False):
                st.warning(f"Atenção: Os arquivos a seguir já existem e serão sobrescritos: **{', '.join(existing_files)}**")
                if st.button(f"Confirmar e Sobrescrever", use_container_width=True, type="primary"):
                    st.session_state[overwrite_key] = True
                    st.rerun()
                return False
        
        if st.button(self.label, use_container_width=True):
            result = self.on_save(df, empresa_id)
            if result:
                st.session_state[overwrite_key] = False  # Reset state
                return True
        
        return False

class ProgressIndicator:
    """Componente de indicador de progresso"""
    
    def __init__(self, message: str):
        self.message = message
    
    def __enter__(self):
        self.spinner = st.spinner(self.message)
        self.spinner.__enter__()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.spinner.__exit__(exc_type, exc_val, exc_tb)

class NotificationManager:
    """Gerenciador de notificações"""
    
    @staticmethod
    def show_success(message: str):
        """Mostra notificação de sucesso"""
        st.success(message)
        logger.info(message)
    
    @staticmethod
    def show_warning(message: str):
        """Mostra notificação de aviso"""
        st.warning(message)
        logger.warning(message)
    
    @staticmethod
    def show_error(message: str):
        """Mostra notificação de erro"""
        st.error(message)
        logger.error(message)
    
    @staticmethod
    def show_info(message: str):
        """Mostra notificação informativa"""
        st.info(message)
        logger.info(message)
    
    @staticmethod
    def show_toast(message: str):
        """Mostra toast notification"""
        st.toast(message)
        logger.info(message) 