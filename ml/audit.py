"""Read-only image inventory and conservative similarity grouping."""
import argparse
import csv
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps
from scipy.fft import dctn

def phash(image):
    pixels = np.asarray(image.convert('L').resize((32, 32)), dtype=float)
    values = dctn(pixels, norm='ortho')[:8, :8].ravel()
    values[0] = 0
    bits = values > np.median(values[1:])
    return sum(int(b) << i for i, b in enumerate(bits))

def inventory(root):
    rows, invalid = [], []
    for label, name in enumerate(('normal', 'jaundice')):
        directory = root / name
        if not directory.is_dir():
            raise ValueError(f'Missing class directory: {name}')
        for path in sorted(directory.rglob('*')):
            if not path.is_file() or path.suffix.lower() not in ('.jpg', '.jpeg', '.png', '.webp'):
                continue
            try:
                raw = path.read_bytes()
                with Image.open(path) as source:
                    image = ImageOps.exif_transpose(source).convert('RGB')
                    image.load()
                    variants = [image, ImageOps.mirror(image), ImageOps.flip(image), image.rotate(180),
                                image.rotate(90, expand=True), image.rotate(270, expand=True)]
                    hashes = [phash(v) for v in variants]
                    pixel_hash = hashlib.sha256(str(image.size).encode()+image.tobytes()).hexdigest()
                    rows.append(dict(relative_path=path.relative_to(root).as_posix(), label=label,
                                     class_name=name, width=image.width, height=image.height,
                                     file_sha256=hashlib.sha256(raw).hexdigest(), pixel_sha256=pixel_hash,
                                     phashes=hashes))
            except Exception as error:
                invalid.append({'relative_path': path.relative_to(root).as_posix(), 'error': str(error)})
    parent = list(range(len(rows)))
    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i
    def union(i,j):
        parent[find(j)] = find(i)
    near_pairs = 0
    for i, row in enumerate(rows):
        for j in range(i):
            other = rows[j]
            distance = min((row['phashes'][0] ^ h).bit_count() for h in other['phashes'])
            if row['pixel_sha256'] == other['pixel_sha256'] or distance <= 4:
                union(i,j)
                near_pairs += 1
    groups = defaultdict(list)
    for i,row in enumerate(rows):
        groups[find(i)].append(row)
    conflicts = []
    for members in groups.values():
        group_id = hashlib.sha256('|'.join(sorted(m['relative_path'] for m in members)).encode()).hexdigest()[:16]
        conflict = len({r['label'] for r in members}) > 1
        for row in members:
            row['group_id'] = group_id
            row['exclude'] = conflict
            row.pop('phashes')
        if conflict:
            conflicts.append({'group_id':group_id,'size':len(members),'files':[r['relative_path'] for r in members]})
    exact = Counter(r['file_sha256'] for r in rows)
    pixels = Counter(r['pixel_sha256'] for r in rows)
    summary = dict(total_images=len(rows), class_counts=dict(Counter(r['class_name'] for r in rows)),
                   invalid_images=invalid, exact_duplicate_extra_images=sum(n-1 for n in exact.values()),
                   decoded_duplicate_extra_images=sum(n-1 for n in pixels.values()),
                   similarity_pairs=near_pairs, similarity_groups=len(groups),
                   groups_by_class=dict(Counter(m[0]['class_name'] for m in groups.values() if len({r['label'] for r in m})==1)),
                   largest_group=max((len(m) for m in groups.values()),default=0),
                   conflicting_groups=conflicts, excluded_images=sum(r['exclude'] for r in rows),
                   group_method='Exact decoded pixels or 64-bit perceptual hash distance <=4 including rotations/mirrors; connected components.',
                   limitations=['Similarity groups are not patient IDs. Same-baby leakage may remain.',
                                'Folder labels have not been clinically verified.',
                                'Perceptual grouping may merge unrelated photos or miss altered copies.'])
    return rows,summary

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--dataset',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    args.output.mkdir(parents=True,exist_ok=True)
    rows,summary=inventory(args.dataset.resolve())
    (args.output/'audit.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
    if not rows:
        parser.error('No readable images were found in the normal and jaundice folders; inspect audit.json for invalid files.')
    with (args.output/'manifest.csv').open('w',newline='',encoding='utf-8') as file:
        writer=csv.DictWriter(file,fieldnames=list(rows[0]))
        writer.writeheader();writer.writerows(rows)
    print(json.dumps({k:v for k,v in summary.items() if k not in ('invalid_images','conflicting_groups')},indent=2))

if __name__=='__main__':main()
