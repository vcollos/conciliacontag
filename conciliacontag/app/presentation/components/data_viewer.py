import streamlit as st

class DataViewerComponent:
    @staticmethod
    def render_extrato_table(extratos):
        st.dataframe(extratos)
    
    @staticmethod
    def render_francesinha_table(francesinhas):
        st.dataframe(francesinhas) 