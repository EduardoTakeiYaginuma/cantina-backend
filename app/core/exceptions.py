# app/core/exceptions.py
"""
Centralized exception handlers for the FastAPI application.
"""
from fastapi import Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError


def _traduzir_mensagem(err: dict) -> str:
    tipo = err.get("type", "")
    ctx = err.get("ctx", {})
    traducoes = {
        "missing": "Campo obrigatório",
        "greater_than": f"Deve ser maior que {ctx.get('gt', '')}",
        "greater_than_equal": f"Deve ser maior ou igual a {ctx.get('ge', '')}",
        "less_than": f"Deve ser menor que {ctx.get('lt', '')}",
        "less_than_equal": f"Deve ser menor ou igual a {ctx.get('le', '')}",
        "string_type": "Deve ser um texto",
        "string_too_short": f"Mínimo de {ctx.get('min_length', '')} caracteres",
        "string_too_long": f"Máximo de {ctx.get('max_length', '')} caracteres",
        "int_type": "Deve ser um número inteiro",
        "int_parsing": "Valor inválido para número inteiro",
        "float_type": "Deve ser um número decimal",
        "float_parsing": "Valor inválido para número decimal",
        "bool_type": "Deve ser verdadeiro ou falso",
        "enum": f"Valor inválido. Opções: {ctx.get('expected', '')}",
        "value_error": err.get("msg", "Valor inválido"),
        "json_invalid": "JSON inválido",
        "extra_forbidden": "Campo não permitido",
    }
    return traducoes.get(tipo, err.get("msg", "Valor inválido"))


async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """
    Handler para erros de validação do Pydantic.
    Transforma o formato padrão em um mais amigável e retorna status 400.

    Args:
        request: Request object
        exc: RequestValidationError exception

    Returns:
        JSONResponse com formato customizado e status 400
    """
    errors = []
    for err in exc.errors():
        loc = err.get("loc", [])
        field = loc[-1] if loc else "body"
        errors.append({
            "field": field,
            "message": _traduzir_mensagem(err),
            "type": err.get("type"),
            "input": err.get("input")
        })

    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={
            "error": "validation_error",
            "message": "Dados de entrada inválidos",
            "details": errors
        }
    )


async def integrity_error_handler(request: Request, exc: IntegrityError) -> JSONResponse:
    """
    Handler para erros de integridade do banco de dados (ex: unique constraint).

    Args:
        request: Request object
        exc: IntegrityError exception

    Returns:
        JSONResponse com status 409 (Conflict)
    """
    return JSONResponse(
        status_code=status.HTTP_409_CONFLICT,
        content={
            "error": "database_integrity_error",
            "message": "Conflito de dados (possível violação de constraint)",
            "details": str(exc.orig) if hasattr(exc, 'orig') else str(exc)
        }
    )


async def general_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """
    Handler genérico para exceções não tratadas.

    Args:
        request: Request object
        exc: Exception

    Returns:
        JSONResponse com status 500
    """
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "error": "internal_server_error",
            "message": "Erro interno do servidor",
            "details": str(exc)
        }
    )


def register_exception_handlers(app) -> None:
    """
    Registra todos os exception handlers na aplicação FastAPI.

    Args:
        app: FastAPI application instance
    """
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(IntegrityError, integrity_error_handler)
    # Descomente a linha abaixo se quiser capturar todas as exceções não tratadas
    # app.add_exception_handler(Exception, general_exception_handler)
