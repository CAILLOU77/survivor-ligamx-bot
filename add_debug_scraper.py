code = open('src/api.py').read()

if '/debug/scraper' not in code:
    endpoint = '''
@app.get("/debug/scraper", summary="Debug: ejecutar scraper con output completo", tags=["Debug"])
@limiter.limit("2/minute")
def debug_scraper(request: Request):
    """Ejecuta el scraper y muestra output completo para debugging"""
    import subprocess
    import sys
    import json
    try:
        result = subprocess.run(
            [sys.executable, "src/debug_scraper.py"],
            capture_output=True,
            text=True,
            timeout=300,
            cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        )
        
        return {
            "status": "success" if result.returncode == 0 else "error",
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}

'''
    
    code = code.replace('if __name__ == "__main__":', endpoint + 'if __name__ == "__main__":')
    open('src/api.py', 'w').write(code)
    print('✅ Endpoint de debug scraper agregado')
else:
    print('✅ Ya existe')
