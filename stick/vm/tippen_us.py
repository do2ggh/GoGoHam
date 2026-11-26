import sys, subprocess
M = {' ': 'spc', '.': 'dot', ',': 'comma', '-': 'minus', '/': 'slash', '>': 'shift-dot', ';': 'semicolon', '|': 'shift-backslash', '=': 'equal', '\n': 'ret', '_': 'shift-minus', '$': 'shift-4', '?': 'shift-slash'}
keys = []
for c in sys.argv[1]:
    if c in M: keys.append(M[c])
    elif c.isdigit(): keys.append(c)
    elif c.isalpha(): keys.append(('shift-' + c.lower()) if c.isupper() else c)
    else: raise SystemExit(c)
subprocess.run(['bash', sys.argv[2]] + [f'sendkey {k}' for k in keys], check=True, stdout=subprocess.DEVNULL)
