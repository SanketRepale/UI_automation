import re
content = open('src/ui_automation/api.py').read()
matches = list(re.finditer(r'@api\.post\("/api/settings"', content))
print([m.start() for m in matches])
m = matches[-1]
print(repr(content[m.start()-50:m.start()+100]))