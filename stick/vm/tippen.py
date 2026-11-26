"""Text per QEMU-sendkey tippen (Gast-Tastatur: deutsch)."""
import sys, subprocess
M = {' ': 'spc', '.': 'dot', ',': 'comma', '-': 'slash', '/': 'shift-7', '>': 'shift-less',
     '<': 'less', ';': 'shift-comma', ':': 'shift-dot', '|': 'altgr-less', '_': 'shift-slash',
     '=': 'shift-0', '\n': 'ret', '"': 'shift-2', '*': 'shift-bracket_right', '+': 'bracket_right',
     '&': 'shift-6', '$': 'shift-4', '(': 'shift-8', ')': 'shift-9', '~': 'altgr-bracket_right'}
keys = []
for c in sys.argv[1]:
    if c in M: keys.append(M[c])
    elif c.isdigit(): keys.append(c)
    elif c.isalpha():
        k = {'y': 'z', 'z': 'y'}.get(c.lower(), c.lower())
        keys.append(('shift-' + k) if c.isupper() else k)
    else: raise SystemExit(f'Zeichen fehlt: {c!r}')
subprocess.run(['bash', sys.argv[2]] + [f'sendkey {k}' for k in keys], check=True, stdout=subprocess.DEVNULL)
