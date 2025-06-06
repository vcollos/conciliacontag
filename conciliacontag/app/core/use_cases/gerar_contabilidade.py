from app.core.entities.francesinha import RegistroFrancesinha
from app.core.entities.plano_contas import PlanoContas
from app.core.entities.contabilidade import RegistroContabilidade
from app.core.services.similarity_matcher import SimilarityMatcher
from app.core.services.text_normalizer import TextNormalizer
from app.config.settings import settings
from typing import List

class GerarContabilidadeUseCase:
    def __init__(self, similarity_matcher: SimilarityMatcher, text_normalizer: TextNormalizer):
        self._matcher = similarity_matcher
        self._normalizer = text_normalizer
    
    def execute(self, francesinhas: List[RegistroFrancesinha], plano_contas: PlanoContas, conta_debito: str) -> List[RegistroContabilidade]:
        # Lógica de correspondência e regras contábeis
        pass 