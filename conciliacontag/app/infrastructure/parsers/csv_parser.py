import pandas as pd

class CSVParser:
    def parse(self, arquivo):
        return pd.read_csv(arquivo, sep=';', encoding='utf-8-sig') 