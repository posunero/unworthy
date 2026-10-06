"""Cross-check the bounded action inventory and build the reviewed semantics.

The independent WAT check counts the direct local-1 equality/inequality guards.
It does not claim all comparisons of all dynamic fields are action selectors.
"""
import argparse
import csv
import gzip
import hashlib
import json
from pathlib import Path
import sys

from action_semantics import definitions
from recover_action_surface import entry_functions, readable, selector_path, SELECTOR


def wat_selectors(module):
    rows = sorted(csv.DictReader((module / 'function-index.csv').open(encoding='utf-8')),
                  key=lambda r: int(r['wat_line']))
    ranges = [(r['retained_debug_name'], int(r['wat_line']), int(rows[i+1]['wat_line']) if i+1<len(rows) else 10**12)
              for i,r in enumerate(rows) if r['retained_debug_name']=='on_action' or r['retained_debug_name'].startswith('on_action_shared(')]
    found = {name:set() for name,_,_ in ranges}
    history = []
    index = 0
    with (module / 'main.wat').open(encoding='utf-8') as source:
        for n,line in enumerate(source,1):
            while index<len(ranges) and n>=ranges[index][2]:
                index += 1
                history = []
            if index>=len(ranges):
                break
            if n<ranges[index][1]:
                continue
            line=line.strip()
            history=(history+[line])[-3:]
            if len(history)==3 and history[0]=='local.get 1' and history[1].startswith('i32.const ') and history[2] in ('i32.eq','i32.ne'):
                found[ranges[index][0]].add(int(history[1].split()[1]) & 0xffffffff)
    return found


def build(root, surface_path, output_dir):
    raw=surface_path.read_bytes()
    surface=json.loads(gzip.decompress(raw) if surface_path.suffix=='.gz' else raw)
    semantics=definitions()
    names_path=output_dir/'action-name-evidence.json'
    if names_path.exists():
        for key,evidence in json.loads(names_path.read_text(encoding='utf-8')).items():
            names={e['name'] for e in evidence}
            semantics[key]['sourceNameCandidates']=sorted(names)
            semantics[key]['sourceNameEvidence']=evidence
            if len(names)==1:
                semantics[key]['sourceName']=next(iter(names))
    if set(semantics) != set(surface['explicitEntryVerbs']):
        raise ValueError('Reviewed definitions do not cover exactly the inventoried selectors')
    output_dir.mkdir(parents=True,exist_ok=True)
    normalized_entrypoints=set()
    for number,module_info in enumerate(surface['modules'],1):
        module=root/'modules'/module_info['module']
        wat=wat_selectors(module)
        for entry in module_info['entrypoints']:
            if set(entry['selectors'])!=wat[entry['function']]:
                raise ValueError(f'C/WAT selector disagreement: {module.name}: {entry["function"]}')
            entry['watSelectorsVerified']=True
        for row,text in entry_functions(module):
            if row['retained_debug_name']=='on_action':
                normalized=readable(text,module.name).replace('w2c_'+module.name.replace('_','__'),'MODULE')
                digest=hashlib.sha256(normalized.encode()).hexdigest()
                module_info['normalizedExportedEntrypointSha256']=digest
                normalized_entrypoints.add(digest)
        if number%10==0:
            print(f'Independently checked WAT {number}/{len(surface["modules"])}',flush=True)
    reference=root/'modules'/'AshenBoneyard_245eeecf8bdc'
    for row,text in entry_functions(reference):
        text=readable(text,reference.name)
        for value in set(int(m[1]) for m in SELECTOR.finditer(text)):
            path=selector_path(text,value)
            entry=semantics[str(value)]
            entry['sourceFunction']=row['retained_debug_name']
            entry['sourceCLine']=int(row['c_line'])+path['boundaryLine']-1
            entry['sourceWatLine']=int(row['wat_line'])
            entry['observedInModuleCount']=len({v['module'] for v in surface['explicitEntryVerbs'][str(value)]})
    audit={'scope':surface['scope'], 'sourceModuleCount':len(surface['modules']),
           'explicitEntrySelectorCount':len(semantics),
           'namedHandlerOccurrences':sum(len(m['internalActionHandlers']) for m in surface['modules']),
           'distinctNamedHandlerFunctions':len({h['function'] for m in surface['modules'] for h in m['internalActionHandlers']}),
           'cWatSelectorAgreement':True,
           'selectorsWithRetainedNames':sum('sourceName' in v for v in semantics.values()),
           'normalizedExportedEntrypointImplementations':len(normalized_entrypoints),
           'fullSemanticRecovery':False,
           'reason':'Input schemas and explicit entry branches are finite; world-state-dependent dispatch, arbitrary String IDs and event subscribers do not have unique context-free outcomes.',
           'modules':surface['modules']}
    (output_dir/'source-action-audit.json.gz').write_bytes(gzip.compress((json.dumps(audit,indent=2)+'\n').encode(),mtime=0))
    (output_dir/'action-semantics-107842.json').write_text(json.dumps(semantics,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:v for k,v in audit.items() if k!='modules'},indent=2),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--modules',type=Path,required=True)
    parser.add_argument('--surface',type=Path,required=True)
    parser.add_argument('--output-dir',type=Path,required=True)
    args=parser.parse_args()
    build(args.modules,args.surface,args.output_dir)
