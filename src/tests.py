import base64
import hashlib
import os
from time import time

p = r'D:\Projects\Python\AutomaticBackup\local_mirror_1.db'
#db = MirrorDataBase(p, reset=True)
# print(len(db.get_keys()))
# for i in range(1000):
#     db.add(i, i)


def encode_stats(stats):
    return base64.b64encode(hashlib.md5(str(stats).encode()).digest())[:8]
    #return hashlib.md5(str(stats).encode()).hexdigest()

# print(sys.getsizeof(encode_stats('sahgahdgjkd hajkgdk jahda ghkjda hkjdg hkjhd gkjhg kjahgkjahd gka h a')))
# print(type(encode_stats('sahgahdgjkd hajkgdk jahda ghkjda hkjdg hkjhd gkjhg kjahgkjahd gka h a')))
# print(encode_stats('sahgahdgjkd hajkgdk jahda ghkjda hkjdg hkjhd gkjhg kjahgkjahd gka h a'))
# print(encode_stats('sahgahdgkd hajkgdk jahda ghkjda hkjdg hkjhd gkjhg kjahgkjahd gka h a'))
#
# #raise SystemExit
#
# d = {}
# l = []
# dir_path = 'D:\\'
#
# print(f'Scanning files from {dir_path}. This may take a while')
# all_paths = set()
# t1 = time()
# for root, dirs, files in os.walk(dir_path):
#     for file in files:
#         abs_path = os.path.join(root, file)
#         if 'RECYCLE' not in abs_path:
#             all_paths.add(abs_path)
#             if len(all_paths) % 5000 == 0:
#                 print(f'{len(all_paths)} files found so far. Average read speed: {int(60 * len(all_paths) / (time() - t1))} files/min')
# print(f'Finished scanning {dir_path} with {len(all_paths)} files in {int((time() - t1) / 60)} minutes')
#
# print('original size', sys.getsizeof(all_paths))
#
# l = [encode_stats(x) for x in all_paths]
# print('original size 2', sys.getsizeof(l))
# print(f'Has duplicate: orig {len(list(d.values())) - len(set(d.values()))}')
#
# for i in range(48):
#     i = 50 - i
#     l2 = [x[:i] for x in l]
#     print(f'Duplicates with i={i}: {len(list(l2)) - len(set(l2))}')
#     print(f'Size i={i}', sys.getsizeof(l2))


def search_empty_dirs(dir_path: str, all_dirs=None, all_files=None, root_call=True):
    empty_dirs = []
    if os.path.isdir(dir_path):
        if root_call:
            all_dirs, all_files = [], []
            for i, (root, dirs, files) in enumerate(os.walk(dir_path), 1):
                all_dirs += [os.path.join(root, d) for d in dirs]
                all_files += [os.path.join(root, f) for f in files]
                if i % 1000 == 0:
                    print(f'{len(all_files)} files scaned so far')
            print(f'Finished searching for contents. Found {len(all_files)} files in {len(all_dirs)} directories')

        if len(all_files):
            sub_dir_names = []
            for d in all_dirs:
                rel_path = os.path.relpath(d, dir_path)
                sub_dir_names.append(rel_path.split(os.path.sep)[0])

            sub_dir_names = list(sorted(set(sub_dir_names)))
            sub_dir_paths = [os.path.join(dir_path, n) for n in sub_dir_names]

            for sub_dir in sub_dir_paths:
                all_dirs_sub_dir = [d for d in all_dirs if d.startswith(sub_dir + os.path.sep) and d != sub_dir]
                all_files_sub_dir = [f for f in all_files if f.startswith(sub_dir + os.path.sep)]
                empty_dirs += search_empty_dirs(sub_dir, all_dirs_sub_dir, all_files_sub_dir, False)

        # Make sure this doesn't delete root folder
        elif not root_call:
            empty_dirs.append(dir_path)

    if root_call:
        print(f'Found {len(empty_dirs)} empty directories')
        for d in empty_dirs:
            print(d)
    return empty_dirs


#db.reset()

# db = MirrorDataBase(p, reset=True)
# t1 = time()
# d = {}
# for i in range(1000):
#     d[i] = i
# db.set(dictionary=d)
# print(time() - t1)

#
# db = MirrorDataBase(p, reset=False)
# for i in range(13):
#     print(db.get(i))
# for i in range(13):
#     print(db.get(i, fallback='FALLBACK'))
#
# print(db.get([1,2,3,12]))
# print(db.get([1,2,3,15], fallback='__1___'))
# print(db.get([1,2,3,15], fallback=None))

if __name__ == '__main__':
    src_dir = r'D:\Van build'
    src_dir = r'N:\BackupPC\D\Backups\Bosch Rexroth Laptop Estagio PFC\50_Electric - Copy'

    p = r'H:\NAS_BACKUP\latest\Rafael\BackupPC\D\Rafael\Projects\Python\Routes\GPS Tools\venv\Lib\site-packages\notebook\static\components\MathJax\jax\output\HTML-CSS\fonts\STIX-Web\Alphabets'
    search_empty_dirs(p)

    t1 = time()
    print('\n'.join(search_empty_dirs(src_dir)))
    print(f'search_empty_dirs3 took {round(time() - t1, 6)}s')


