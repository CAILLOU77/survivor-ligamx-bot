code = open('src/api.py').read()

if '/debug/api-response' not in code:
    endpoint = '''
@app.get("/debug/api-response", summary="Debug: Ver respuesta cruda de The Odds API", tags=["Debug"])
@limiter.limit("2/minute")
def debug_api_response(request: Request):
    """Muestra la respuesta cruda de The Odds API"""
    import subprocess
    import sys
    try:
        result = subprocess.run(
            [sys.executable, "src/debug_api_response.py"],
            capture_output=True,
            text=True,
            timeout=60,
            cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        )
        
        return {
            "status": "success" if result.returncode == 0 else "error",
            "output": result.stdout,
            "errors": result.stderr
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}

'''
    
    code = code.replace('if __name__ == "__main__":', endpoint + 'if __name__ == "__main__":')
    open('src/api.py', 'w').write(code)
    print('✅ Endpoint de debug API agregado')
else:
    print('✅ Ya existe')
