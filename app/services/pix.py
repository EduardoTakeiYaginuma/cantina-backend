"""
Pix estático com valor (BR Code / "copia e cola"), gerado aqui mesmo, sem banco nem internet.

O código segue o padrão EMV do Banco Central: chave, nome e cidade do recebedor, valor e um
identificador (txid). O pagamento NÃO é confirmado automaticamente: alguém confere no app do
banco e confirma no sistema.
"""
import re
import unicodedata
import uuid
from typing import Optional

TIPOS_CHAVE = ("cpf", "cnpj", "telefone", "email", "aleatoria")


class PixConfigError(ValueError):
    pass


def _ascii(text: str) -> str:
    text = unicodedata.normalize("NFKD", text or "")
    return "".join(ch for ch in text if not unicodedata.combining(ch))


def normalize_key(tipo: str, chave: str) -> str:
    """Deixa a chave no formato que o Pix espera; erro se não for válida."""
    chave = (chave or "").strip()
    digits = re.sub(r"\D", "", chave)
    if tipo == "cpf":
        if len(digits) != 11:
            raise PixConfigError("CPF deve ter 11 números")
        return digits
    if tipo == "cnpj":
        if len(digits) != 14:
            raise PixConfigError("CNPJ deve ter 14 números")
        return digits
    if tipo == "telefone":
        if len(digits) in (10, 11):
            digits = "55" + digits
        if not (digits.startswith("55") and len(digits) in (12, 13)):
            raise PixConfigError("Telefone deve ter DDD + número (ex.: 11 99999-9999)")
        return "+" + digits
    if tipo == "email":
        chave = chave.lower()
        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", chave) or len(chave) > 77:
            raise PixConfigError("E-mail inválido")
        return chave
    if tipo == "aleatoria":
        try:
            return str(uuid.UUID(chave)).lower()
        except ValueError:
            raise PixConfigError("Chave aleatória inválida (formato 0000aaaa-00aa-...)")
    raise PixConfigError("Tipo de chave inválido")


def clean_name(nome: str) -> str:
    """Nome do recebedor: sem acentos, maiúsculo, até 25 caracteres."""
    nome = re.sub(r"[^A-Za-z0-9 ]", "", _ascii(nome)).upper().strip()
    if not nome:
        raise PixConfigError("Informe o nome do recebedor")
    return nome[:25]


def clean_city(cidade: str) -> str:
    """Cidade: sem acentos, maiúsculo, até 15 caracteres."""
    cidade = re.sub(r"[^A-Za-z0-9 ]", "", _ascii(cidade)).upper().strip()
    if not cidade:
        raise PixConfigError("Informe a cidade")
    return cidade[:15]


def _field(tag: str, value: str) -> str:
    if len(value) > 99:
        raise PixConfigError(f"Campo {tag} grande demais")
    return f"{tag}{len(value):02d}{value}"


def crc16(payload: str) -> str:
    """CRC16-CCITT (polinômio 0x1021, início 0xFFFF), como pede o BR Code."""
    crc = 0xFFFF
    for byte in payload.encode("utf-8"):
        crc ^= byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) if crc & 0x8000 else (crc << 1)
            crc &= 0xFFFF
    return f"{crc:04X}"


def build_payload(chave: str, nome: str, cidade: str, valor: float, txid: str = "***",
                  descricao: Optional[str] = None) -> str:
    """Código "copia e cola" do Pix estático com valor."""
    if valor <= 0:
        raise PixConfigError("O valor deve ser maior que zero")
    txid = re.sub(r"[^A-Za-z0-9]", "", txid or "")[:25] or "***"
    conta = _field("00", "br.gov.bcb.pix") + _field("01", chave)
    if descricao:
        desc = re.sub(r"[^A-Za-z0-9 ]", "", _ascii(descricao)).strip()
        room = 99 - len(conta) - 4
        if desc and room > 0:
            conta += _field("02", desc[:room])
    payload = (
        _field("00", "01")
        + _field("26", conta)
        + _field("52", "0000")
        + _field("53", "986")
        + _field("54", f"{valor:.2f}")
        + _field("58", "BR")
        + _field("59", clean_name(nome))
        + _field("60", clean_city(cidade))
        + _field("62", _field("05", txid))
        + "6304"
    )
    return payload + crc16(payload)
