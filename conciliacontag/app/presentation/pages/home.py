import streamlit as st

class HomePage:
    @staticmethod
    def render():
        st.title("💰 Processador de Extratos Financeiros")
        st.markdown("### Converte arquivos OFX (extratos) e XLS (francesinhas) para CSV") 