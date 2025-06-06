from dataclasses import dataclass
from typing import List

@dataclass
class PlanoConta:
    seq: str
    auxiliar: str
    contabil: str
    descricao: str

@dataclass
class PlanoContas:
    contas: List[PlanoConta] 