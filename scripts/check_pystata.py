"""Check if pystata is available via Stata's Python integration."""
import sys, os

# Check Stata's bundled Python paths
stata_path = r'C:\Program Files\StataNow19'
candidate_paths = [
    r'C:\Program Files\StataNow19\utilities\python\3_12\Lib\site-packages',
    r'C:\Program Files\StataNow19\utilities\python\3_11\Lib\site-packages',
    r'C:\Program Files\StataNow19\Python\Lib\site-packages',
    r'C:\Program Files\StataNow19\Python\python.zip',
]

for p in candidate_paths:
    if os.path.exists(p):
        sys.path.insert(0, p)

try:
    import stata_setup
    import pystata
    import sfi as _sfi
    print('pystata/sfi available!')
    print('stata_setup:', stata_setup.__file__)
except ImportError as e:
    print('pystata not available:', e)

# Also search for any stata-related modules
for root, dirs, files in os.walk(stata_path):
    for f in files:
        if f == 'stata_setup.py' or f == 'pystata.py' or f == 'sfi.py':
            print('Found:', os.path.join(root, f))
