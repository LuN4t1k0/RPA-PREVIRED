import json
import os
from models import Estado, Planilla


class Checkpoint:
    def __init__(self, path: str = "checkpoint.json"):
        self._path = path
        self._completados: set[str] = self._cargar()

    def _key(self, rut: str, periodo: str, nomina: str, institucion: str) -> str:
        return f"{rut}|{periodo}|{nomina}|{institucion}"

    def _cargar(self) -> set:
        if not os.path.exists(self._path):
            return set()
        with open(self._path) as f:
            return set(json.load(f))

    def _guardar(self):
        with open(self._path, "w") as f:
            json.dump(list(self._completados), f)

    def esta_completo(self, rut: str, periodo: str, nomina: str, institucion: str) -> bool:
        return self._key(rut, periodo, nomina, institucion) in self._completados

    def marcar(self, planilla: Planilla):
        if planilla.estado == Estado.OK:
            self._completados.add(
                self._key(planilla.rut_empresa, planilla.periodo, planilla.nomina, planilla.institucion)
            )
            self._guardar()
