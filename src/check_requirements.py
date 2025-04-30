req_modules = {
    'base64',
    'copy',
    'datetime',
    'filecmp',
    'hashlib',
    'json',
    'logger',
    'logging',
    'os',
    'pandas',
    'queue',
    'shutil',
    'sqlitedict',
    'sys',
    'threading',
    'time',
    'tkinter',
    'ttkwidgets',
    'traceback',
    'typing',
    'winsound',
}

all_ok = True

for name in req_modules:
    try:
        mod = __import__(name)
    except ModuleNotFoundError:
        print(f'Missing module: "{name}"')
        all_ok = False

if all_ok:
    print('Everything is OK')
