import pathlib

code = open('src/api.py').read()

# Agregar imports si no existen
if 'from slowapi' not in code:
    # Agregar después de los imports de FastAPI
    code = code.replace(
        'from fastapi import FastAPI',
        'from fastapi import FastAPI, Request\nfrom slowapi import Limiter, _rate_limit_exceeded_handler\nfrom slowapi.util import get_remote_address\nfrom slowapi.errors import RateLimitExceeded'
    )
    
    # Agregar limiter después de app = FastAPI
    code = code.replace(
        'app = FastAPI(',
        'limiter = Limiter(key_func=get_remote_address)\napp = FastAPI('
    )
    
    # Agregar handler de errores
    code = code.replace(
        'app.include_router(analizar_router)',
        'app.state.limiter = limiter\napp.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)\napp.include_router(analizar_router)'
    )
    
    # Agregar decoradores a endpoints protegidos
    code = code.replace(
        '@app.get("/picks/latest"',
        '@limiter.limit("10/minute")\n@app.get("/picks/latest"'
    )
    
    code = code.replace(
        '@app.get("/stats"',
        '@limiter.limit("20/minute")\n@app.get("/stats"'
    )
    
    code = code.replace(
        '@app.get("/history"',
        '@limiter.limit("20/minute")\n@app.get("/history"'
    )
    
    pathlib.Path('src/api.py').write_text(code)
    print('✅ Rate limiting agregado')
else:
    print('✅ Ya existe')
