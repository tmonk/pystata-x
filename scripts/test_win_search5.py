"""Check for sfi.pyd or _bist_ exposed via pystata package."""
import ctypes
import os
import sys

stata_dir = r'C:\Program Files\StataNow19'

# Check pystata Python package
pystata_dir = os.path.join(stata_dir, 'utilities', 'pystata')
print(f'Checking pystata Python package at: {pystata_dir}')
if os.path.isdir(pystata_dir):
    for root, dirs, files in os.walk(pystata_dir):
        for fname in files:
            if fname.endswith('.pyd') or fname.endswith('.dll') or fname == '__init__.py' or fname == 'sfi.py':
                print(f'  {os.path.relpath(os.path.join(root, fname), pystata_dir)}')

# Try to import sfi from Stata's Python
stata_python = os.path.join(stata_dir, 'utilities', 'Python311')
if os.path.isdir(stata_python):
    print(f'\nStata Python directory: {stata_python}')
    for fname in sorted(os.listdir(stata_python)):
        if 'sfi' in fname.lower() or 'stata' in fname.lower() or fname == 'python.exe':
            print(f'  {fname}')

# Check for Python37 or other versions  
for ver in ['Python311', 'Python310', 'Python39', 'Python38', 'Python37', 'Python312']:
    pydir = os.path.join(stata_dir, 'utilities', ver)
    if os.path.isdir(pydir):
        print(f'\n{ver} contents:')
        for fname in sorted(os.listdir(pydir)):
            if 'sfi' in fname.lower() or 'stata' in fname.lower() or fname.endswith('.pyd'):
                print(f'  {fname}')

# Check the Python site-packages for sfi
site_packages = os.path.join(os.environ.get('LOCALAPPDATA', r'C:\Users\tom\AppData\Local'), 'Programs', 'Python', 'Python312', 'Lib', 'site-packages')
print(f'\nChecking site-packages for sfi:')
if os.path.isdir(site_packages):
    for item in os.listdir(site_packages):
        if 'sfi' in item.lower() or 'stata' in item.lower():
            print(f'  {item}')
            fpath = os.path.join(site_packages, item)
            if os.path.isdir(fpath):
                for sub in os.listdir(fpath):
                    print(f'    {sub}')
