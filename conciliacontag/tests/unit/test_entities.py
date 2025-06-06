import pytest
from decimal import Decimal
from app.core.entities.francesinha import RegistroFrancesinha

def test_tem_juros_mora_quando_valor_maior_zero():
    registro = RegistroFrancesinha(
        sacado='Teste', nosso_numero='1', seu_numero='2',
        dt_previsao_credito=None, vencimento=None, dt_limite_pgto=None,
        valor_rs=Decimal('100'), vlr_mora=Decimal('10.50'), vlr_desc=Decimal('0'),
        vlr_outros_acresc=Decimal('0'), dt_liquid=None, vlr_cobrado=Decimal('110.50'),
        arquivo_origem='Teste'
    )
    assert registro.tem_juros_mora() is True 