import pathlib

api_code = open('src/api.py').read()

if '/dashboard' not in api_code:
    dashboard_code = '''

@app.get("/dashboard", summary="Dashboard visual", tags=["Dashboard"])
def dashboard():
    from fastapi.responses import HTMLResponse
    stats = get_metrics()
    html_content = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Survivor LigaMX Dashboard</title>
        <style>
            body { font-family: Arial, sans-serif; max-width: 1200px; margin: 0 auto; padding: 20px; background: #f5f5f5; }
            .header { background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 30px; border-radius: 10px; margin-bottom: 30px; }
            .metrics { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 20px; margin-bottom: 30px; }
            .metric { background: white; padding: 20px; border-radius: 10px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
            .metric h3 { margin: 0; color: #666; font-size: 14px; }
            .metric .value { font-size: 32px; font-weight: bold; color: #333; margin-top: 10px; }
        </style>
    </head>
    <body>
        <div class="header">
            <h1>📊 Survivor LigaMX Premium</h1>
            <p>Dashboard de Rendimiento en Vivo</p>
        </div>
        <div class="metrics">
            <div class="metric">
                <h3>Total Picks</h3>
                <div class="value">""" + str(stats['total_picks']) + """</div>
            </div>
            <div class="metric">
                <h3>Wins</h3>
                <div class="value">""" + str(stats['wins']) + """</div>
            </div>
            <div class="metric">
                <h3>Win Rate</h3>
                <div class="value">""" + f"{stats['win_rate']:.1f}%" + """</div>
            </div>
            <div class="metric">
                <h3>Total Profit</h3>
                <div class="value">""" + f"{stats['total_profit']:.2f}" + """</div>
            </div>
        </div>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content)
'''
    
    # Insertar antes del if __name__
    api_code = api_code.replace('if __name__ == "__main__":', dashboard_code + '\nif __name__ == "__main__":')
    pathlib.Path('src/api.py').write_text(api_code)
    print('✅ Dashboard agregado')
else:
    print('✅ Dashboard ya existe')