import streamlit as st

class FileUploaderComponent:
    @staticmethod
    def render_ofx_uploader():
        return st.file_uploader(
            "Envie arquivos OFX",
            type=['ofx'],
            accept_multiple_files=True,
            key="ofx_uploader"
        )
    
    @staticmethod
    def render_excel_uploader():
        return st.file_uploader(
            "Envie arquivos Excel",
            type=['xls', 'xlsx'],
            accept_multiple_files=True,
            key="excel_uploader"
        ) 