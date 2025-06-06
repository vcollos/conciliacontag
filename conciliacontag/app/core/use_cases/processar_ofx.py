from app.infrastructure.parsers.ofx_parser import OFXParser
from app.core.entities.extrato import Extrato
from app.core.services.file_validator import FileValidator
from typing import List

class ProcessarOFXUseCase:
    def __init__(self, ofx_parser: OFXParser, file_validator: FileValidator):
        self._parser = ofx_parser
        self._validator = file_validator
    
    def execute(self, arquivos_ofx: list) -> List[Extrato]:
        extratos = []
        for arquivo in arquivos_ofx:
            self._validator.validate_ofx(arquivo)
            extrato = self._parser.parse(arquivo)
            extratos.append(extrato)
        return extratos 