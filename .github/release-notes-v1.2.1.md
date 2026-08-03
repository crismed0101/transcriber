# Transcriber v1.2.1

Versión de mantenimiento. **No cambia nada de lo que ves ni de cómo se usa**: es
reorganización interna del código.

Si ya tenés la 1.2.0 funcionando, actualizar es opcional.

## Instalación

Si ya tenés Transcriber instalado, la app te avisa sola y se encarga. Si no:

```powershell
irm https://raw.githubusercontent.com/crismed0101/transcriber/master/install.ps1 | iex
```

O bajá el `.exe` de abajo y hacé doble clic.

## Qué cambió por dentro

El archivo principal tenía 2.561 líneas y una sola clase con trece
responsabilidades mezcladas: construir la ventana, los estilos, los hilos de
trabajo, los diálogos, la integración con Windows, las actualizaciones, la
grabación, la cola de archivos, el texto y el historial.

Ahora cada cosa vive donde corresponde:

| Módulo | De qué se ocupa |
|---|---|
| `theme` | Colores, estilos e iconos |
| `workers` | Los hilos: cargar el modelo, transcribir, actualizar |
| `dialogs` | Ventanas secundarias |
| `win32` | Instancia única y atajo global |
| `widgets` | Piezas de interfaz reutilizables |
| `update_controller` | El ciclo completo de actualización |

El peor caso era la barra de progreso: **once métodos distintos** la manipulaban,
cada uno armando a mano su combinación de opciones, y ninguno era responsable de su
estado. Ahora tiene un único dueño que expone los cuatro modos que la app necesita.

También se eliminaron duplicaciones: el patrón de las carpetas de sesión estaba
escrito en dos lugares, y había doce repeticiones del mismo bloque para escribir en
el editor sin disparar eventos.

## Por qué te lo cuento si no lo vas a notar

Porque es lo que hace que el próximo arreglo sea rápido y seguro en vez de
arriesgado. Un archivo de 2.500 líneas donde todo se toca con todo es donde los
errores se esconden.

Todo verificado con 148 pruebas automáticas más un banco de pruebas que construye la
interfaz real y la ejercita de punta a punta.
