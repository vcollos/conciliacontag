import streamlit as st

class ContabilidadePage:
    def __init__(self, gerar_contabilidade_uc):
        self._gerar_contabilidade_uc = gerar_contabilidade_uc
    
    def render(self):
        st.subheader("📊 Gerar Arquivo Contabilidade")
        # Aqui entraria a lógica de upload e geração do contabilidade.csv 