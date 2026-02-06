# app/core/exceptions.py
"""
Centralized exception handlers for the FastAPI application.
"""
from fastapi import Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError


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
            "message": err.get("msg"),
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
