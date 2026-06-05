# Security Policy

## Reportar una vulnerabilidad

**No abras un issue público.** Eso expone el problema antes de que se pueda parchar.

Para reporte responsable:

1. Manda email a **rozolusia@gmail.com** con asunto `[security][transcriber] <descripción>`.
2. Incluye:
   - Pasos para reproducir
   - Versión afectada (commit SHA)
   - Impacto estimado

Voy a confirmar la recepción dentro de 72h.

## Alcance

- Manejo de audio capturado (acceso indebido a streams del sistema)
- Manejo de transcripciones (exposición de contenido sensible)
- Cualquier credencial o API key embebida (no debería haber, todas vía env vars)

## Hardening básico

- `.gitignore` excluye archivos de credenciales y `.env`
- Dependencias de Python actualizadas vía Dependabot semanal
