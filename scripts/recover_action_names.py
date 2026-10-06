"""Recover retained action-name candidates from the exact analyzed binaries."""
import argparse
import hashlib
import json
from pathlib import Path
import re

from action_semantics import definitions
from build_action_catalog import fnv1a

EXPECTED = {
    'snowplay_dll_UnrealShipping.dll': '9c969b94efc2ddd5900ff4dd4ef73dbb9974592a32bec49f1219c182fa5248fd',
    'Stormgate-Win64-Shipping.exe': 'a41bb5900fbdcdf93822f2052260ce4a3f20c36f0e4f538558fe8be67d3b7a64',
}


def recover(binaries, sdk, output):
    targets=set(map(int,definitions()))
    matches={}
    for filename, expected in EXPECTED.items():
        data=(binaries/filename).read_bytes()
        if hashlib.sha256(data).hexdigest()!=expected:
            raise ValueError(f'Binary hash mismatch: {filename}')
        for pattern,encoding in [(rb'[ -~]{3,160}','ascii'),(rb'(?:[ -~]\x00){3,160}','utf-16le')]:
            for match in re.finditer(pattern,data):
                text=match[0].decode(encoding)
                value=fnv1a(text)
                if value in targets:
                    matches.setdefault(str(value),[]).append({'name':text,'source':filename,'sha256':expected,
                                                             'fileOffset':match.start(),'encoding':encoding,
                                                             'basis':'retained_binary_string_hash_match'})
    for path in sorted(sdk.rglob('*.h')):
        text=path.read_text(encoding='utf-8-sig')
        for match in re.finditer(r'"([^"\n]{1,160})"',text):
            value=fnv1a(match[1])
            if value in targets:
                matches.setdefault(str(value),[]).append({'name':match[1],'source':path.relative_to(sdk).as_posix(),
                                                         'line':text[:match.start()].count('\n')+1,
                                                         'basis':'shipped_header_literal_hash_match'})
    output.write_text(json.dumps(matches,indent=2)+'\n',encoding='utf-8')
    print(f'{len(matches)} selectors have retained binary/header name evidence')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binaries',type=Path,required=True)
    parser.add_argument('--sdk',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    recover(args.binaries,args.sdk,args.output)
