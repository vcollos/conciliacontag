import streamlit as st
from app.presentation.components.file_uploader import FileUploaderComponent
from app.presentation.components.data_viewer import DataViewerComponent

class ExtratosPage:
    def __init__(self, processar_ofx_uc):
        self._processar_ofx_uc = processar_ofx_uc
    
    def render(self):
        st.subheader("📊 Extratos OFX")
        arquivos = FileUploaderComponent.render_ofx_uploader()
        if arquivos and st.button("Processar OFX"):
            extratos = self._processar_ofx_uc.execute(arquivos)
            DataViewerComponent.render_extrato_table(extratos) 