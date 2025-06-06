class FileValidator:
    def validate_ofx(self, arquivo):
        # Adicione validações reais conforme necessário
        if not arquivo.name.lower().endswith('.ofx'):
            raise ValueError('Arquivo não é OFX')
    
    def validate_excel(self, arquivo):
        if not (arquivo.name.lower().endswith('.xls') or arquivo.name.lower().endswith('.xlsx')):
            raise ValueError('Arquivo não é Excel') 