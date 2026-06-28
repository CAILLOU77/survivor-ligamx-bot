import pathlib
api_code = open("src/api.py").read()
if "/dashboard" not in api_code:
    code = """
"""
    api_code = api_code.replace("if __name__", code + "\nif __name__")
    pathlib.Path("src/api.py").write_text(api_code)
    print("OK")
