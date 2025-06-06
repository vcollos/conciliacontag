import pandas as pd
from app.core.entities.francesinha import RegistroFrancesinha
from datetime import datetime
from decimal import Decimal
from typing import List

class ExcelParser:
    COLUMN_MAPPING = {
        1: 'sacado',
        5: 'nosso_numero',
        11: 'seu_numero',
        13: 'dt_previsao_credito',
        18: 'vencimento',
        21: 'dt_limite_pgto',
        25: 'valor_rs',
        28: 'vlr_mora',
        29: 'vlr_desc',
        31: 'vlr_outros_acresc',
        34: 'dt_liquid',
        35: 'vlr_cobrado'
    }

    def parse(self, arquivo) -> List[RegistroFrancesinha]:
        df = pd.read_excel(arquivo, header=None)
        registros = []
        for _, row in df.iterrows():
            if self._is_valid_row(row):
                registro = self._create_registro(row, getattr(arquivo, 'name', ''))
                registros.append(registro)
        return registros

    def _is_valid_row(self, row) -> bool:
        sacado = str(row.iloc[1]).strip() if pd.notna(row.iloc[1]) else ''
        nosso_numero = str(row.iloc[5]).strip() if pd.notna(row.iloc[5]) else ''
        return (
            sacado != '' and len(sacado) > 3 and not sacado.startswith('Sacado') and nosso_numero != ''
        )

    def _create_registro(self, row, arquivo_origem) -> RegistroFrancesinha:
        def get_val(idx, typ=str):
            val = row.iloc[idx] if idx < len(row) else None
            if pd.isna(val):
                return '' if typ is str else None
            if typ is Decimal:
                try:
                    return Decimal(str(val))
                except:
                    return Decimal('0')
            if typ is datetime:
                if isinstance(val, datetime):
                    return val
                try:
                    return pd.to_datetime(val, errors='coerce')
                except:
                    return None
            return str(val).strip()
        return RegistroFrancesinha(
            sacado=get_val(1),
            nosso_numero=get_val(5),
            seu_numero=get_val(11),
            dt_previsao_credito=get_val(13, datetime),
            vencimento=get_val(18, datetime),
            dt_limite_pgto=get_val(21, datetime),
            valor_rs=get_val(25, Decimal),
            vlr_mora=get_val(28, Decimal),
            vlr_desc=get_val(29, Decimal),
            vlr_outros_acresc=get_val(31, Decimal),
            dt_liquid=get_val(34, datetime),
            vlr_cobrado=get_val(35, Decimal),
            arquivo_origem=arquivo_origem
        ) 