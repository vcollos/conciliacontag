from app.infrastructure.parsers.excel_parser import ExcelParser
from app.core.entities.francesinha import RegistroFrancesinha
from app.core.services.file_validator import FileValidator
from typing import List

class ProcessarXLSUseCase:
    def __init__(self, excel_parser: ExcelParser, file_validator: FileValidator):
        self._parser = excel_parser
        self._validator = file_validator
    
    def execute(self, arquivos_xls: list) -> List[RegistroFrancesinha]:
        registros = []
        for arquivo in arquivos_xls:
            self._validator.validate_excel(arquivo)
            registros.extend(self._parser.parse(arquivo))
        return registros 