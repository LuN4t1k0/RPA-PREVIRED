# PRD — Automatización de Descarga de Planillas Pagadas desde Previred

## 1. Nombre del producto

**Previred Downloader Bot**

## 2. Resumen ejecutivo

Se requiere desarrollar una herramienta interna que automatice la descarga de planillas previsionales pagadas desde Previred para múltiples empresas y múltiples períodos históricos.

Actualmente, una persona debe ingresar manualmente a Previred, seleccionar empresa por empresa, buscar los períodos disponibles y descargar las planillas previsionales correspondientes. El proceso es altamente repetitivo, consume tiempo operativo y genera errores humanos por fatiga.

La solución propuesta es un robot de automatización de navegador, de tipo RPA semi-asistido, donde el usuario inicia sesión manualmente en Previred y luego el sistema automatiza la navegación, descarga, almacenamiento, trazabilidad y control de errores.

---

## 3. Problema a resolver

### Situación actual

Una persona realiza manualmente las siguientes acciones:

1. Ingresa a Previred.
2. Selecciona una empresa.
3. Entra al módulo de Remuneraciones.
4. Accede a Imprimir documentos.
5. Selecciona Planillas Pagadas.
6. Selecciona período.
7. Descarga las planillas previsionales.
8. Repite el proceso por cada empresa y por cada período disponible.

### Dolor principal

El proceso es:

- repetitivo;
- propenso a errores;
- lento;
- difícil de auditar;
- dependiente de una persona;
- poco escalable cuando existen muchas empresas o muchos períodos históricos.

### Impacto

Los errores pueden generar:

- períodos no descargados;
- archivos duplicados;
- archivos mal nombrados;
- planillas guardadas en carpetas incorrectas;
- pérdida de trazabilidad;
- retrabajo operativo.

---

## 4. Objetivo del producto

Automatizar la descarga ordenada y trazable de planillas pagadas desde Previred, reduciendo el trabajo manual y disminuyendo errores humanos.

---

## 5. Objetivos específicos

1. Permitir cargar un listado de empresas a procesar.
2. Permitir definir un rango de períodos por empresa.
3. Automatizar la navegación dentro de Previred una vez iniciada la sesión.
4. Descargar las planillas pagadas disponibles por empresa y período.
5. Guardar los documentos con una estructura estándar de carpetas y nombres.
6. Registrar el resultado de cada intento de descarga.
7. Permitir reintentar solamente los casos fallidos.
8. Evitar duplicidad de archivos ya descargados.
9. Generar un reporte final de ejecución.
10. Mantener trazabilidad sobre errores, períodos sin información y documentos descargados correctamente.

---

## 6. Alcance funcional

### Incluido en el MVP

El MVP debe permitir:

- iniciar el navegador automatizado;
- esperar que el usuario realice login manual en Previred;
- leer empresas desde un archivo de entrada;
- seleccionar empresa en Previred;
- ingresar al módulo Remuneraciones;
- navegar hacia Imprimir documentos > Planillas Pagadas;
- recorrer períodos definidos;
- descargar archivos PDF disponibles;
- guardar archivos en carpetas por empresa y período;
- registrar logs de ejecución;
- generar reporte CSV o Excel;
- marcar estados: OK, SIN_DATOS, ERROR, OMITIDO;
- reanudar ejecución desde el último punto procesado.

### Fuera del MVP

No se considera en la primera versión:

- automatizar el login completo;
- resolver captcha;
- saltar doble factor de autenticación;
- extraer cookies manualmente para simular sesión;
- consumir endpoints internos no documentados de Previred;
- modificar información en Previred;
- subir nóminas;
- pagar cotizaciones;
- procesar contablemente los PDF;
- leer el contenido completo de los PDF con OCR.

---

## 7. Enfoque recomendado

La solución debe ser un RPA semi-asistido.

### Flujo general

```text
Usuario abre el bot
        ↓
Bot abre navegador controlado
        ↓
Usuario inicia sesión manualmente en Previred
        ↓
Usuario confirma que ya está dentro del portal
        ↓
Bot toma control de la navegación
        ↓
Bot procesa empresas y períodos
        ↓
Bot descarga planillas
        ↓
Bot guarda archivos
        ↓
Bot genera reporte final