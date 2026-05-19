"""Count methods implemented vs original sfi.py."""
import sys, re
sys.path.insert(0, 'src')

# Get our methods
our_methods = set()
with open('src/pystata_x/sfi/_core.py') as f:
    content = f.read()
# Find all method definitions
for m in re.finditer(r'def (\w+)\(', content):
    our_methods.add(m.group(1))

# Get original methods from each class
original_classes = {
    'Data': [], 'Frame': [], 'Macro': [], 'ValueLabel': [],
    'Missing': [], 'SFIToolkit': [], 'SFIError': [], 'BreakError': [],
    'FrameError': [], 'Platform': [], 'Characteristic': [],
    'Preference': [], 'Datetime': [], 'Matrix': [], 'Mata': [],
    'StrLConnector': [], 'StrLConnector_props': [],
}
# Property methods and dunder methods from original
extra_orig = {'__init__', 'close', 'getPosition', 'getSize', 'isBinary',
              'reset', 'setPosition', 'readBytes', 'writeBytes', 'storeBytes',
              'obs', 'pos', 'var',
              'connect', 'addVarStrL', 'allocateStrL'}

# Count our Data methods (original Data class methods)
data_methods = {
    'addObs', 'addVarByte', 'addVarDouble', 'addVarFloat', 'addVarInt',
    'addVarLong', 'addVarStr', 'addVarStrL', 'allocateStrL', 'connect',
    'dropVar', 'fromNPArray', 'fromPDataFrame', 'get', 'getAsDict',
    'getAt', 'getBestType', 'getFormattedValue', 'getMaxStrLength',
    'getMaxVars', 'getObsTotal', 'getStrVarWidth', 'getVarCount',
    'getVarFormat', 'getVarIndex', 'getVarLabel', 'getVarName',
    'getVarType', 'getVarValueLabel', 'isAlias', 'isVarTypeStr',
    'isVarTypeString', 'isVarTypeStrL', 'isVarTypeNumeric',
    'keepVar', 'list', 'readBytes', 'renameVar', 'setObsTotal',
    'setVarFormat', 'setVarLabel', 'store', 'storeAt', 'storeBytes',
    'toNPArray', 'toPDataFrame', 'writeBytes',
    'getDouble', 'getString', 'storeDouble', 'storeString',
}

# Count our Frame methods
frame_methods = {
    'addObs', 'addVarByte', 'addVarDouble', 'addVarFloat', 'addVarInt',
    'addVarLong', 'addVarStr', 'addVarStrL', 'allocateStrL',
    'changeToCWF', 'clone', 'connect', 'create', 'drop', 'dropVar',
    'fromNPArray', 'fromPDataFrame', 'get', 'getAsDict', 'getAt',
    'getCWF', 'getFormattedValue', 'getFrameAt', 'getFrameCount',
    'getFrames', 'getMaxStrLength', 'getMaxVars', 'getName',
    'getObsTotal', 'getStrVarWidth', 'getVarCount', 'getVarFormat',
    'getVarIndex', 'getVarLabel', 'getVarName', 'getVarType',
    'getVarValueLabel', 'isVarTypeStr', 'isVarTypeStrL', 
    'readBytes', 'rename', 'renameVar', 'storeBytes', 'writeBytes',
}

# Count
ours = set()
for m in data_methods:
    if m in our_methods:
        ours.add(f'Data.{m}')
for m in frame_methods:
    if m in our_methods:
        ours.add(f'Frame.{m}')

print(f"Our _core.py has {len(our_methods)} method definitions", flush=True)
print(f"Data methods: {len([m for m in data_methods if f'Data.{m}' in ours])}/{len(data_methods)}", flush=True)
print(f"Frame instance methods: {len([m for m in frame_methods if f'Frame.{m}' in ours])}/{len(frame_methods)}", flush=True)

# Missing Data methods
missing_data = sorted(data_methods - {m for m in data_methods if f'Data.{m}' in ours})
print(f"\nMissing Data methods: {missing_data}", flush=True)

# Missing Frame methods
missing_frame = sorted(frame_methods - {m for m in frame_methods if f'Frame.{m}' in ours})
print(f"Missing Frame methods: {missing_frame}", flush=True)

# Count total methods by regex
count = 0
for m in re.finditer(r'^\s+def (\w+)\(', content, re.MULTILINE):
    if not m.group(1).startswith('_'):
        count += 1
print(f"\nTotal non-private method definitions: {count}", flush=True)
