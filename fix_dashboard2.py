import pathlib

api_code = open('src/api.py').read()

if '/dashboard' not in api_code:
    dashboard_code = '''

@app.get("/dashboard", summary="Dashboard visual", tags=["Dashboard"])
def dashboard():
    from fastapi.responses import HTMLResponse
    stats = get_metrics()
    html_content = f"""
    <html>
    <head><title>Survivor LigaMX Dashboard</title></head>
    <body style="font-family: Arial; max-width: 800px; margin: 50px auto; padding: 20px;">
        <h1 style="color: #667eea;">📊 Survivor LigaMX Premium</h1>
        <div style="display: grid; grid-template-columns: repeat(2, 1fr); gap: 20px; margin: 30px 0;">
            <div style="background: white; padding: 20px; border-radius: 10px; box-shadow: 0 2px 4px rgba(0,0,0,0.1);">
                <h3 style="margin: 0; color: #666;">Total Picks</h3>
                <div style="font-size: 32px; font-weight: bold;">{stats['total_picks']}</div>
            </div>
            <div style="background: white; padding: 20px; border-radius: 10px; box-shadow: 0 2px 4px rgba(0,0,0,0.1);">
                <h3 style="margin: 0; color: #666;">Wins</h3>
                <div style="font-size: 32px; font-weight: bold;">{stats['wins']}</div>
            </div>
            <div style="background: white; padding: 20px; border-radius: 10px; box-shadow: 0 2px 4px rgba(0,0,0,0.1);">
                <h3 style="margin: 0; color: #666;">Win Rate</h3>
                <div style="font-size: 32px; font-weight: bold;">{stats['win_rate']:.1f}%</div>
            </div>
            <div style="background: white; padding: 20px; border-radius: 10px; box-shadow: 0 2px 4px rgba(0,0,0,0.1);">
                <h3 style="margin: 0; color: #666;">Total Profit</h3>
                <div style="font-size: 32px; font-weight: bold;">{stats['total_profit']:.2f}</div>
            </div>
        </div>
        <p><a href="/docs">📚 Ver documentación API</a></p>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content)
'''
    
    api_code = api_code.replace('if __name__ == "__main__":', dashboard_code + '\nif __name__ == "__main__":')
    pathlib.Path('src/api.py').write_text(api_code)
    print('✅ Dashboard agregado')
else:
    print('✅ Dashboard ya existe')