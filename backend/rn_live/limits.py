from starlette.exceptions import HTTPException
from starlette.responses import JSONResponse


class BodyLimit:
    """Limita la recepción antes de que el parser multipart llene temporales."""

    def __init__(self, app, settings):
        self.app, self.settings = app, settings

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        limit = self.settings.max_upload_bytes + 65536  # cabeceras y campos multipart
        headers = dict(scope.get('headers', []))
        try:
            length = int(headers.get(b'content-length', b'0'))
        except ValueError:
            length = 0
        if length > limit:
            return await JSONResponse({'detail':'El archivo supera el límite permitido'}, status_code=413)(scope, receive, send)
        received = 0

        async def limited_receive():
            nonlocal received
            message = await receive()
            received += len(message.get('body', b''))
            if received > limit:
                raise HTTPException(413, 'El archivo supera el límite permitido')
            return message

        await self.app(scope, limited_receive, send)
