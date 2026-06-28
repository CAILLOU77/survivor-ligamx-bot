code = open('src/api.py').read()

if '/debug/jornadas' not in code:
    endpoint = '''
@app.get("/debug/jornadas", summary="Debug: ver contenido de jornadas.json", tags=["Debug"])
@limiter.limit("5/minute")
def debug_jornadas(request: Request):
    """Muestra el contenido de jornadas.json para debugging"""
    import json
    try:
        jornadas_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "jornadas.json")
        with open(jornadas_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        # Contar partidos
        if isinstance(data, list):
            count = len(data)
            sample = data[:2] if data else []
        else:
            partidos = data.get('partidos', [])
            count = len(partidos)
            sample = partidos[:2] if partidos else []
        
        return {
            "status": "success",
            "total_partidos": count,
            "sample": sample,
            "structure": "list" if isinstance(data, list) else "dict"
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}

'''
    
    code = code.replace('if __name__ == "__main__":', endpoint + 'if __name__ == "__main__":')
    open('src/api.py', 'w').write(code)
    print('✅ Endpoint de debug agregado')
else:
    print('✅ Ya existe')
