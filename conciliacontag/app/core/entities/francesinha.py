from dataclasses import dataclass
from datetime import datetime
from typing import Optional
from decimal import Decimal

@dataclass
class RegistroFrancesinha:
    sacado: str
    nosso_numero: str
    seu_numero: str
    dt_previsao_credito: datetime
    vencimento: datetime
    dt_limite_pgto: datetime
    valor_rs: Decimal
    vlr_mora: Decimal
    vlr_desc: Decimal
    vlr_outros_acresc: Decimal
    dt_liquid: Optional[datetime]
    vlr_cobrado: Decimal
    arquivo_origem: str
    
    def tem_juros_mora(self) -> bool:
        return self.vlr_mora > 0
    
    def gerar_linha_mora(self) -> 'RegistroFrancesinha':
        pass 