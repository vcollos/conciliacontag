import unicodedata

def normalizar_texto(texto: str) -> str:
    if not texto:
        return ''
    texto = str(texto)
    texto_sem_acento = unicodedata.normalize('NFD', texto)
    texto_sem_acento = ''.join(char for char in texto_sem_acento if unicodedata.category(char) != 'Mn')
    return texto_sem_acento.upper().strip() 