"""Import properly licensed normalized nutrition data; never manufacture citations.
Usage: python scripts/import_reference.py nutrients input.json
       python scripts/import_reference.py targets input.json
This validates shape, provenance and units, but NOT scientific authenticity.
"""
import argparse
import json
import math
import os
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from backend.app.schemas import Target


def validate(data,kind):
    if not isinstance(data,list) or not data:
        raise ValueError('Input must be a non-empty JSON array')
    seen=set()
    for row in data:
        if not all(row.get(key) for key in ('source','source_url','retrieved_on')):
            raise ValueError('Every record needs source, source_url and retrieved_on')
        if not str(row['source_url']).startswith('https://'):
            raise ValueError('Use an HTTPS provenance URL')
        if kind=='nutrients':
            for key in ('id','name','name_en','category','allergens','vegetarian','halal_compatible','near_expiry_days','per_100g'):
                if key not in row:raise ValueError('Missing '+key)
            if row['id'] in seen:raise ValueError('Duplicate ingredient ID')
            seen.add(row['id'])
            for key in ('kcal','protein','carbs','fat'):
                value=row['per_100g'].get(key)
                if not isinstance(value,(int,float)) or not math.isfinite(value) or value<0:raise ValueError('Invalid '+key)
            if not isinstance(row['allergens'],list):raise ValueError('allergens must be an array')
        else:
            Target.model_validate(row['meal_target'])
            if not 1<=row['age_min']<=row['age_max']<=110:raise ValueError('Invalid age interval')
            if row['sex'] not in ('female','male','any'):raise ValueError('Invalid sex')
            if not isinstance(row.get('tags',[]),list):raise ValueError('tags must be an array')
    return data


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('kind',choices=['nutrients','targets']);p.add_argument('file',type=Path);args=p.parse_args()
    data=validate(json.loads(args.file.read_text(encoding='utf-8')),args.kind)
    directory=ROOT/'data';directory.mkdir(exist_ok=True)
    destination=directory/('nutrition_overrides.json' if args.kind=='nutrients' else 'target_standards.json')
    temporary=destination.with_suffix('.tmp');temporary.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8');os.replace(temporary,destination)
    print(f'Imported {len(data)} records into {destination}. Back up this private data directory.')


if __name__=='__main__':main()
