import re

with open("hyrule_web/app.py", "r") as f:
    code = f.read()

# adding dashboard
dashboard_code = """
@app.get("/dashboard", response_class=HTMLResponse)
async def page_dashboard(request: Request):
    return _render(request, "dashboard.html")
"""

# replacing index
old_index = """@app.get("/", response_class=HTMLResponse)
async def page_index(request: Request):
    return _render(request, "index.html")"""

new_index = """@app.get("/", response_class=HTMLResponse)
async def page_index(request: Request):
    runtime = {
        "api_ms": 24, "queue": 3, "avg_provision": 58, "live_vms": 1284
    }
    return _render(request, "index.html", runtime=runtime)"""

code = code.replace(old_index, new_index + "\n" + dashboard_code)
with open("hyrule_web/app.py", "w") as f:
    f.write(code)
