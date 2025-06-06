from dataclasses import dataclass
from datetime import datetime
from typing import Optional
from decimal import Decimal

@dataclass
class Transacao:
    data: datetime
    valor: Decimal
    tipo: str
    id: str
    memo: Optional[str] = None
    payee: Optional[str] = None
    checknum: Optional[str] = None

@dataclass
class Extrato:
    transacoes: list[Transacao]
    arquivo_origem: str
    
    def adicionar_transacao(self, transacao: Transacao) -> None:
        pass
    
    def total_creditos(self) -> Decimal:
        pass
    
    def total_debitos(self) -> Decimal:
        pass 