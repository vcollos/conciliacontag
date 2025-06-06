import streamlit as st

class ProgressBarComponent:
    @staticmethod
    def render(progress: float, text: str = ""):
        bar = st.progress(progress)
        if text:
            st.text(text)
        return bar 