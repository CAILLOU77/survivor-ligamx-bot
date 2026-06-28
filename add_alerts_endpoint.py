code = open('src/api.py').read()

if 'send_high_ev_alerts' not in code:
    # Agregar import
    code = code.replace(
        'from src.database import',
        'from src.telegram_alerts import send_high_ev_alerts\nfrom src.database import'
    )
    
    # Agregar endpoint antes del if __name__
    endpoint = '''
@app.post("/alerts/high-ev", summary="Enviar alertas de picks con EV > 5%", tags=["Alerts"])
@limiter.limit("5/minute")
def alerts_high_ev(request: Request):
    return send_high_ev_alerts()

'''
    
    code = code.replace('if __name__ == "__main__":', endpoint + 'if __name__ == "__main__":')
    
    open('src/api.py', 'w').write(code)
    print('✅ Endpoint de alertas agregado')
else:
    print('✅ Ya existe')
