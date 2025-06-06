from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

@dataclass
class RegistroContabilidade:
    debito: str
    credito: str
    historico: str
    data: datetime
    valor: Decimal
    complemento: str

@dataclass
class Contabilidade:
    registros: list[RegistroContabilidade] 