import os, json, subprocess

base = r'C:\Users\user\Downloads\basay-grammar\webpage\凱達格蘭（巴賽語） ～從記憶到再生～'

with open(f'{base}/data/dictionary.json', encoding='utf-8') as f:
    data = json.load(f)

valid_slugs = {e['audio']['slug'] for e in data if 'audio' in e and 'slug' in e['audio']}

to_remove = []
for accent in ['ipay', 'hokkien']:
    audio_root = f'{base}/dictionary/audio/{accent}'
    for dirpath, dirs, files in os.walk(audio_root):
        for f in files:
            if f.endswith('.mp3') and f.replace('.mp3', '') not in valid_slugs:
                rel = os.path.relpath(os.path.join(dirpath, f), base)
                to_remove.append(rel)

print('Removing:')
for f in to_remove:
    print(' ', f)

if to_remove:
    subprocess.run(['git', '-C', base, 'rm'] + to_remove)
    subprocess.run(['git', '-C', base, 'commit', '-m', 'Remove obsolete audio files'])
    subprocess.run(['git', '-C', base, 'push'])
else:
    print('No obsolete files found.')
