code = open('src/api.py').read()

if '/analyze/advanced' not in code:
    endpoint = '''
@app.get("/analyze/advanced", summary="Análisis avanzado de mercados", tags=["Analysis"])
@limiter.limit("10/minute")
def analyze_advanced(request: Request, api_key: str = Depends(verify_api_key)):
    """Analiza Handicap Asiático, Goles por Equipo, Marcador Exacto"""
    import subprocess
    import sys
    try:
        result = subprocess.run(
            [sys.executable, "src/advanced_markets.py"],
            capture_output=True,
            text=True,
            timeout=60,
            cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        )
        
        if result.returncode == 0:
            lines = result.stdout.strip().split('\n')
            json_start = None
            for i, line in enumerate(lines):
                if line.strip().startswith('['):
                    json_start = i
                    break
            
            if json_start is not None:
                json_output = '\n'.join(lines[json_start:])
                import json
                data = json.loads(json_output)
                return {"status": "success", "matches": data}
        
        return {"status": "error", "message": "Error en análisis", "details": result.stderr}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

'''
    
    code = code.replace('if __name__ == "__main__":', endpoint + 'if __name__ == "__main__":')
    open('src/api.py', 'w').write(code)
    print('✅ Endpoint de mercados avanzados agregado')
else:
    print('✅ Ya existe')
