"""Normalización, formato y validación de RUT chilenos."""

from __future__ import annotations

import re


def limpiar_rut(value: str) -> str:
    """Retorna solo cuerpo y dígito verificador, en mayúsculas."""
    limpio = re.sub(r"[.\-\s]", "", str(value)).upper()
    if not re.fullmatch(r"\d{1,8}[0-9K]", limpio):
        raise ValueError("RUT inválido. Revisa el número y dígito verificador.")
    return limpio


def normalizar_rut(value: str) -> str:
    """Retorna el formato canónico sin puntos: 12345678-5."""
    limpio = limpiar_rut(value)
    return f"{limpio[:-1]}-{limpio[-1]}"


def formatear_rut(value: str) -> str:
    """Retorna el formato de presentación: 12.345.678-5."""
    limpio = limpiar_rut(value)
    cuerpo, dv = limpio[:-1], limpio[-1]
    cuerpo_formateado = f"{int(cuerpo):,}".replace(",", ".")
    return f"{cuerpo_formateado}-{dv}"


def es_rut_valido(value: str) -> bool:
    try:
        limpio = limpiar_rut(value)
    except ValueError:
        return False

    cuerpo, dv = limpio[:-1], limpio[-1]
    if int(cuerpo) == 0:
        return False

    suma = 0
    multiplicador = 2
    for digito in reversed(cuerpo):
        suma += int(digito) * multiplicador
        multiplicador = 2 if multiplicador == 7 else multiplicador + 1

    resultado = 11 - (suma % 11)
    esperado = "0" if resultado == 11 else "K" if resultado == 10 else str(resultado)
    return dv == esperado


def validar_rut(value: str) -> str:
    """Valida el dígito verificador y retorna el formato canónico."""
    if not es_rut_valido(value):
        raise ValueError("RUT inválido. Revisa el número y dígito verificador.")
    return normalizar_rut(value)
