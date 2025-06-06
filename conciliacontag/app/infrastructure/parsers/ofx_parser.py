from ofxparse import OfxParser
from app.core.entities.extrato import Extrato, Transacao
from datetime import datetime
from decimal import Decimal

class OFXParser:
    def parse(self, arquivo) -> Extrato:
        ofx = OfxParser.parse(arquivo)
        transacoes = []
        for conta in ofx.accounts:
            for t in conta.statement.transactions:
                transacoes.append(Transacao(
                    data=t.date,
                    valor=Decimal(str(t.amount)),
                    tipo=t.type,
                    id=t.id,
                    memo=t.memo,
                    payee=t.payee,
                    checknum=t.checknum
                ))
        return Extrato(transacoes=transacoes, arquivo_origem=getattr(arquivo, 'name', '')) 