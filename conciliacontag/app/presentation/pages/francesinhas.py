import streamlit as st
from app.presentation.components.file_uploader import FileUploaderComponent
from app.presentation.components.data_viewer import DataViewerComponent

class FrancesinhasPage:
    def __init__(self, processar_xls_uc):
        self._processar_xls_uc = processar_xls_uc
    
    def render(self):
        st.subheader("📋 Francesinhas XLS")
        arquivos = FileUploaderComponent.render_excel_uploader()
        if arquivos and st.button("Processar Francesinhas"):
            francesinhas = self._processar_xls_uc.execute(arquivos)
            DataViewerComponent.render_francesinha_table(francesinhas) 