import re

with open("hyrule_web/templates/base.html", "r") as f:
    text = f.read()

# Replace these links with '#' or remove them
text = text.replace('href="/api/pricing"', 'href="#"')
text = text.replace('href="/api/docs"', 'href="#"')
text = text.replace('href="/docs/x402"', 'href="#"')
text = text.replace('href="/docs/cli"', 'href="#"')
text = text.replace('href="/status"', 'href="#"')
text = text.replace('href="/pgp"', 'href="#"')

# Add dashboard to nav
nav_old = '<a href="/order">Order</a>'
nav_new = '<a href="/order">Order</a><a href="/dashboard">Dashboard</a>'
text = text.replace(nav_old, nav_new)

with open("hyrule_web/templates/base.html", "w") as f:
    f.write(text)
