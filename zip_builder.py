import io
import os
import zipfile


def construir_zip(directorio: str) -> io.BytesIO:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for raiz, carpetas, archivos in os.walk(directorio):
            carpetas.sort(key=str.casefold)
            for archivo in sorted(archivos, key=str.casefold):
                if not archivo.lower().endswith(".pdf"):
                    continue
                ruta_abs = os.path.join(raiz, archivo)
                ruta_rel = os.path.relpath(ruta_abs, directorio)
                zf.write(ruta_abs, ruta_rel)
    buffer.seek(0)
    return buffer
