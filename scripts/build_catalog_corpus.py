"""Index shipped ability/command definitions by exact map runtime hash.

Stores deltas against the reference catalog to avoid 98 copies of shared data.
Defined command slots are not a claim of in-match availability or success.
"""
import argparse
import gzip
import hashlib
import json
from pathlib import Path


def compact(raw):
    output={}
    for key,value in raw['archetypes'].items():
        info=value[1]
        entry={k:info[k] for k in ('id','__base_type') if k in info}
        if isinstance(info.get('commands'),list):
            entry['commands']=[{k:v for k,v in command.items()
                               if k in ('id','unit','upgrade','button','entity','ability','morph_to')}
                              for command in info['commands']]
        output[key]=entry
    return output


def build(content,reference_path,output):
    reference=json.loads(reference_path.read_bytes())
    base=reference['archetypes']
    maps={}
    for folder in sorted((content/'PublishedMaps').iterdir()):
        if not (folder/'main.wasm').exists():
            continue
        build=json.loads((folder/'build.json').read_bytes())
        if build['version']!='1.0.107842':
            raise ValueError(f'Unexpected map build: {folder.name}')
        raw=(folder/'runtime_session.json').read_bytes()
        definitions=compact(json.loads(raw))
        runtime_hash=json.loads((folder/'_checksum.json').read_bytes())['runtime_hash']
        if runtime_hash in maps:
            raise ValueError('Duplicate map runtime hash; explicit alias handling required')
        slots=sum(min(30,len(v.get('commands',[]))) for v in definitions.values() if 'Ability' in v.get('__base_type',''))
        maps[runtime_hash]={
            'map':folder.name,'build':107842,'mapRuntimeHash':runtime_hash,
            'runtimeSessionSha256':hashlib.sha256(raw).hexdigest(),
            'wasmSha256':hashlib.sha256((folder/'main.wasm').read_bytes()).hexdigest(),
            'archetypeCount':len(definitions),'definedAbilityCommandSlots':slots,
            'overrides':{key:value for key,value in definitions.items() if base.get(key)!=value},
            'removed':[key for key in base if key not in definitions]}
        if len(maps)%10==0:
            print(f'Indexed {len(maps)} exact map catalogs',flush=True)
    data={'build':107842,'baseMapRuntimeHash':reference['mapRuntimeHash'],
          'baseCatalogSha256':hashlib.sha256(reference_path.read_bytes()).hexdigest(),
          'baseArchetypesSha256':hashlib.sha256(json.dumps(base,sort_keys=True,separators=(',',':')).encode()).hexdigest(),
          'scope':'Shipped runtime archetypes and defined ability command slots, not runtime eligibility or outcomes.',
          'maps':maps}
    output.write_bytes(gzip.compress((json.dumps(data,sort_keys=True)+'\n').encode(),mtime=0))
    print(f'{len(maps)} maps; {output.stat().st_size} compressed bytes; {sum(v["definedAbilityCommandSlots"] for v in maps.values())} map-specific command slots',flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--content',type=Path,required=True)
    parser.add_argument('--reference',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    build(args.content,args.reference,args.output)
