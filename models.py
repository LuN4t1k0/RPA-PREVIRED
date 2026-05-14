from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class Estado(str, Enum):
    OK = "OK"
    SIN_DATOS = "SIN_DATOS"
    ERROR = "ERROR"
    OMITIDO = "OMITIDO"


@dataclass
class Nomina:
    nombre: str
    slug: str


@dataclass
class Empresa:
    rut: str
    nombre: str
    nominas_por_periodo: dict = field(default_factory=dict)  # {"yyyy-mm": [Nomina]}


@dataclass
class Planilla:
    rut_empresa: str
    periodo: str
    nomina: str
    institucion: str
    folio: str
    estado: Estado
    ruta_archivo: Optional[str] = None
    error_msg: Optional[str] = None


@dataclass
class BotMessage:
    tipo: str  # "progreso_empresa", "planilla", "fin", "error_login", "error_fatal"
    datos: dict = field(default_factory=dict)
