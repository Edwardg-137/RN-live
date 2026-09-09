# RN-live

Aplicación privada para preparar y revisar grabaciones de discursos, debates y entrevistas en español.

**Estado: primera entrega del MVP.** Incluye subida, reproductor, edición temporal de transcripción y hablantes, persistencia y worker local. La verificación de afirmaciones, búsqueda de fuentes y detección de falacias todavía no están implementadas.

## Ejecutar con Docker

Requisitos: Docker con contenedores Linux y Docker Compose.

```powershell
docker compose up -d --build
```

Abrir http://localhost:8080. Solo se publica ese puerto en la interfaz local. PostgreSQL y la API permanecen en la red interna de Docker. Los archivos, la base y los modelos se conservan en volúmenes.

El worker incluye faster-whisper para una voz. El primer uso descarga el modelo multilingüe `small`; necesita internet, espacio y memoria. Se puede cambiar `RN_WHISPER_MODEL` en `.env`. La prueba técnica ejecutada utiliza `tiny` sobre silencio y no certifica precisión con discursos reales.

Para diarización de varias voces:

1. Copiar `.env.example` como `.env`.
2. Aceptar las condiciones de [pyannote community-1](https://huggingface.co/pyannote/speaker-diarization-community-1) y configurar `RN_HF_TOKEN` localmente.
3. Establecer `RN_INSTALL_AUDIO=true` y reconstruir con `docker compose up -d --build`. El extra instala PyTorch y pyannote; es una descarga considerable. Esta integración no se ha validado con credenciales y grabaciones reales.

Para detener los servicios sin borrar datos: `docker compose stop`. Para consultar problemas: `docker compose logs --tail 100 worker api`.

## Desarrollo en Windows o Linux

Requisitos: Python 3.12+, uv, Node 24 y FFmpeg/ffprobe en PATH para procesar audio o validar MP3/MP4.

```powershell
uv sync --extra dev --extra transcription
npm --prefix frontend ci
```

Ejecutar en tres terminales, desde la raíz:

```powershell
uv run uvicorn rn_live.app:app --host 127.0.0.1 --port 8000
uv run python -m rn_live.worker
npm --prefix frontend run dev
```

En desarrollo se usa SQLite por defecto en `data/rn-live.db`; Docker usa PostgreSQL. La documentación interactiva de la API está disponible en http://127.0.0.1:8000/docs durante desarrollo. El worker y la API deben usar la misma configuración y almacenamiento. Si usas `uv run` después de instalar extras, conserva esos extras al sincronizar o ejecuta directamente los binarios de `.venv`.

## Pruebas

```powershell
uv run --extra dev pytest backend/tests -q
npm --prefix frontend test
npm --prefix frontend run build
```

Con Docker levantado y Edge instalado:

```powershell
npm --prefix frontend run test:e2e
```

El test de navegador crea una grabación WAV sintética y la elimina al terminar. `backend/tests/smoke_media.py` verifica MP3, MP4, extracción y audio retrasado dentro del contenedor. `smoke_transcription.py` verifica el recorrido real de faster-whisper con silencio y descarga el modelo tiny.

## OpenRouter

El adaptador de LLM está preparado para OpenRouter, pero el flujo de verificación todavía no lo invoca. Para probarlo localmente, crea una clave en OpenRouter y configura en `.env`:

```dotenv
OPENROUTER_API_KEY=tu_clave_local
OPENROUTER_MODEL=openrouter/free
OPENROUTER_FREE_ONLY=true
```

La clave solo se lee en el backend. En modo gratuito se bloquean modelos de pago y no existe fallback automático a uno de pago. OpenRouter puede limitar los modelos gratuitos; sus cuotas y disponibilidad no están bajo control de RN-live.

## Límites actuales

- Piloto de un usuario, sin autenticación pública. No exponer directamente a internet.
- Archivos MP4 H.264/AAC, MP3 y WAV PCM, máximo 60 minutos y 1 GB por defecto.
- Hasta cuatro hablantes; nombres y roles manuales. La fusión/eliminación de etiquetas requiere reasignar segmentos mediante API; la interfaz permite añadir y editar etiquetas.
- Cancelar impide publicar resultados, pero no interrumpe inmediatamente una inferencia ya iniciada. El worker queda ocupado hasta que esa llamada termine.
- Volver a transcribir reemplaza los segmentos al finalizar. Todavía no hay historial de revisiones anteriores ni versiones de análisis.
- La precisión de transcripción y diarización, y los umbrales de la propuesta, siguen pendientes de evaluación con muestras reales.

La documentación oficial reside en `docs/`, siguiendo `docs/general_instructions.md`. Esa carpeta continúa excluida de Git por la configuración preexistente; debe conservarse/copiarse por separado mientras se mantenga esa regla.
