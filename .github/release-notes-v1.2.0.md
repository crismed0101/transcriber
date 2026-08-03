# Transcriber v1.2.0

Versión de corrección profunda. Se arreglaron fallos que hacían perder trabajo sin
avisar, y ahora la app se adapta sola al equipo en vez de fallar cuando la
configuración elegida no sirve.

**Actualizar es recomendado para todos**, vengas de la versión que vengas. El
instalador migra tus transcripciones automáticamente (ver "Tus archivos se movieron
solos"), y a partir de esta versión la app avisa sola cuando hay una nueva.

## Instalación

Un solo comando en PowerShell:

```powershell
irm https://raw.githubusercontent.com/crismed0101/transcriber/master/install.ps1 | iex
```

O bajá el `.exe` de abajo y hacé doble clic. Instala por usuario, sin pedir permisos de
administrador.

> Windows puede advertir "Windows protegió su PC" porque la app no está firmada
> digitalmente: **Más información** → **Ejecutar de todas formas**.

## Lo que se arreglaba a los golpes y ahora funciona

### Salir desde la bandeja ya no descarta la grabación

Si grababas con la app minimizada y salías desde el icono de la bandeja, la
grabación se perdía al instante, sin preguntar nada. El diálogo de confirmación
existía pero era inalcanzable por ese camino. Ahora pregunta siempre, y si decidís
descartar, borra el audio temporal en vez de dejarlo ocupando espacio.

### Se acabaron las grabaciones fantasma

Cuando fallaba la escritura del audio (disco lleno, carpeta sin permisos), la app
quedaba en un estado en el que el siguiente intento **mostraba todo normal pero no
grababa nada**: punto rojo, cronómetro corriendo, y al detener, "Sin audio
detectado". Podías perder media hora de reunión. Como el tercer intento volvía a
funcionar, el problema parecía aleatorio.

### Un disco lleno ya no apila decenas de diálogos

El aviso de error de escritura se volvía a mostrar dos veces por segundo mientras lo
leías. Ahora aparece una sola vez y la grabación se detiene ordenadamente.

### La app ya no se cierra sola sin explicación

Si la carpeta de destino no estaba disponible (OneDrive sin conexión, disco lleno),
la app desaparecía de golpe al subir un archivo. Ahora te dice qué pasó. Lo mismo
si el equipo no tiene audio disponible: antes ni abría; ahora arranca con la
grabación deshabilitada y podés seguir transcribiendo archivos.

## Tus archivos se movieron solos

Si usás OneDrive, las transcripciones anteriores estaban yendo a una carpeta
`Documentos` **que no era la que ves en el Explorador**. Guardabas, y después no
encontrabas nada.

La app ahora le pregunta a Windows dónde está tu carpeta Documentos de verdad, y al
abrirse por primera vez **migra sola** lo que había en la ubicación vieja. No tenés
que hacer nada.

## Nuevo: elegir el modelo, y degradación automática

Apareció el desplegable **Modelo**:

| Opción | Para qué |
|---|---|
| `Automatico` | elige el mejor que tu equipo aguanta (por defecto) |
| `tiny` … `large-v3` | forzás uno concreto |

Lo importante es lo que pasa cuando algo no funciona: si la configuración elegida no
carga —GPU sin CUDA, drivers viejos, modelo que no entra en memoria— la app **baja
sola al siguiente escalón** hasta encontrar uno que ande, y te lo dice en el
recuadro de arriba. Antes, en esa situación, simplemente mostraba un error y no se
podía transcribir.

También detecta si tu placa NVIDIA necesita un driver más nuevo y te lo explica, en
vez de fallar más adelante con un mensaje incomprensible.

## Nuevo: se actualiza sola

De acá en adelante no hace falta volver a instalar a mano. La app consulta una vez por
día si hay versión nueva y te avisa, con tres opciones: **Actualizar**, **Ahora no** u
**Omitir esta versión**.

Si aceptás, descarga el instalador mostrando el progreso, **verifica que el archivo no
venga alterado** comparando su firma SHA256, y recién ahí lo ejecuta. Si la verificación
falla, borra el archivo y no instala nada.

Nunca interrumpe: si estás grabando o transcribiendo, el aviso espera. También podés
buscar actualizaciones cuando quieras desde el menú del icono de la bandeja.

## Otras mejoras

- **`Ctrl+Shift+R` ahora sí funciona con la app minimizada**, que era el caso para el
  que servía. Antes solo respondía con la ventana enfocada, aunque la documentación
  dijera lo contrario.
- **Cancelar responde durante la descarga del modelo.** Antes se quedaba en
  "Cancelando..." hasta que terminaran de bajar los 3 GB.
- **La app ya no borra modelos de otros proyectos.** La limpieza de caché tocaba las
  carpetas compartidas de HuggingFace y podía obligar a otro programa tuyo a
  redescargar 3 GB.
- **La ventana se adapta al tamaño de tu pantalla**, en vez de usar una medida fija
  que se salía en pantallas chicas.
- **Diagnóstico incorporado:** `Transcriber.exe --selftest` desde una consola verifica
  la instalación y deja un informe. Útil si necesitás reportar un problema.
- **Menú "Acerca de"** en la bandeja, con la versión y dónde están tus archivos.
- El ejecutable ahora tiene información de versión y editor en Propiedades.

## Notas técnicas

- Requiere `ctranslate2 >= 4.6.3` para las placas GeForce RTX 50xx (Blackwell): es la
  primera versión compilada con CUDA 12.8, que es lo que genera los kernels de esa
  arquitectura.
- El instalador limpia la carpeta de la versión anterior antes de copiar, para evitar
  bibliotecas viejas conviviendo con las nuevas.
- El paquete adelgazó ~100 MB: se dejó de incluir `ffprobe.exe`, que nunca se usaba.

## Tus datos

Ni la instalación ni la desinstalación tocan tus transcripciones. Siguen en
`Documentos\Transcriber\`, y los modelos y ajustes en `%LOCALAPPDATA%\Transcriber\`.
