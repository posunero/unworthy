"""Inventory explicit replay-entry selectors in recovered wasm2c output.

This is a bounded static inventory, not an emulator or a proof of all runtime
actions. It follows the integer-only selector prefix and stops at a runtime
operation. Internal on_action handlers are listed separately from map entrypoints.
"""
import argparse
import csv
import hashlib
import gzip
import json
from pathlib import Path
import re

SELECTOR = re.compile(r'var_i0 = var_p1;\s+var_i1 = (\d+)u;\s+var_i0 = var_i0 (?:==|!=) var_i1;')


def readable(text, module):
    # Decode symbols only. Do not change hex constants in expressions.
    text = re.sub(r'\b(?:w2c_[A-Za-z0-9_]+)',
                  lambda m: re.sub(r'0x([0-9A-Fa-f]{2})', lambda x: chr(int(x[1], 16)), m[0]), text)
    return text.replace('w2c_' + module.replace('_', '__') + '_', '')


def function_ranges(module):
    rows = sorted(csv.DictReader((module / 'function-index.csv').open(encoding='utf-8')),
                  key=lambda r: int(r['c_line']))
    return [(row, int(row['c_line']), int(rows[i+1]['c_line']) if i+1 < len(rows) else 10**12)
            for i, row in enumerate(rows)]


def entry_functions(module):
    ranges = [(row, start, end) for row, start, end in function_ranges(module)
              if row['retained_debug_name'] == 'on_action' or row['retained_debug_name'].startswith('on_action_shared(')]
    result = []
    if not ranges:
        return result
    i, chunk = 0, []
    with (module / 'main.c').open(encoding='utf-8') as source:
        for line_number, line in enumerate(source, 1):
            while i < len(ranges) and line_number >= ranges[i][2]:
                result.append((ranges[i][0], ''.join(chunk)))
                i, chunk = i+1, []
            if i >= len(ranges):
                break
            if line_number >= ranges[i][1]:
                chunk.append(line)
        if i < len(ranges) and chunk:
            result.append((ranges[i][0], ''.join(chunk)))
    return result


def selector_path(text, value, selector='var_p1'):
    """Follow known comparisons, preserving the runtime-dependent boundary."""
    lines = text.splitlines()
    labels = {line.strip().removesuffix(':;'): i for i, line in enumerate(lines)
              if re.fullmatch(r'\s*var_[BL]\w*:;?', line)}
    pc = next((i for i, line in enumerate(lines[:-1])
               if line.strip() in (f'var_i0 = {selector};', f'{selector} = var_i0;')
               and re.fullmatch(r'\s*var_i1 = \d+u;', lines[i+1])), 0)
    env, visited = {selector: value, 'var_i0': value}, set()
    while pc < len(lines):
        if pc in visited:
            return {'boundaryLine': pc+1, 'reason': 'selector_cycle'}
        visited.add(pc)
        line = lines[pc].strip()
        jump = re.fullmatch(r'if \((var_\w+)\) \{goto (var_\w+);\}', line)
        if jump:
            if jump[1] not in env:
                break
            pc = labels[jump[2]] if env[jump[1]] else pc+1
            continue
        jump = re.fullmatch(r'goto (var_\w+);', line)
        if jump:
            pc = labels[jump[1]]
            continue
        assignment = re.fullmatch(r'(var_\w+) = (.*);', line)
        if assignment:
            target, expr = assignment.groups()
            if re.fullmatch(r'\d+u(?:ll)?', expr):
                env[target] = int(expr.rstrip('ul'))
            elif expr in env:
                env[target] = env[expr]
            elif re.fullmatch(r'var_\w+', expr):
                env.pop(target, None)
            else:
                comparison = re.fullmatch(r'(var_\w+) (==|!=|>|<|>=|<=) (var_\w+)', expr)
                signed = re.fullmatch(r'\(u32\)\(\(s32\)(var_\w+) (>|<|>=|<=) \(s32\)(var_\w+)\)', expr)
                comparison = signed or comparison
                if comparison and comparison[1] in env and comparison[3] in env:
                    left, right = env[comparison[1]], env[comparison[3]]
                    if signed:
                        left = left if left < 2**31 else left-2**32
                        right = right if right < 2**31 else right-2**32
                    env[target] = int({'==': left == right, '!=': left != right,
                                      '>': left > right, '<': left < right,
                                      '>=': left >= right, '<=': left <= right}[comparison[2]])
                else:
                    break
        elif (operation := re.fullmatch(r'(var_\w+) ([&|+\-^])= (var_\w+);', line)):
            target, op, right = operation.groups()
            if target in env and right in env:
                a, b = env[target], env[right]
                env[target] = {'&': a & b, '|': a | b, '+': a+b, '-': a-b, '^': a^b}[op] & 0xffffffff
            else:
                env.pop(target, None)
        elif line and not line.endswith(':;') and line not in ('}', '{'):
            break
        pc += 1
    # Preserve the entry block through its next label for human review. The
    # remainder of a runtime handler is not claimed to have been evaluated.
    end = pc+1
    while end < len(lines) and not re.fullmatch(r'\s*var_[BL]\w*:;?', lines[end]):
        end += 1
    return {'boundaryLine': pc+1, 'reason': 'runtime_boundary',
            'entryBlock': '\n'.join(lines[pc:end])}


def inventory(root, output, evidence=None):
    manifest = json.loads((root / 'manifest.json').read_text(encoding='utf-8'))
    modules, verbs = [], {}
    for index, item in enumerate(manifest['modules']):
        name = item['module']
        module = root / 'modules' / name
        record = {'module': name, 'wasmSha256': item['sha256'], 'entrypoints': [], 'internalActionHandlers': []}
        for row, start, end in function_ranges(module):
            if 'on_action' in row['retained_debug_name'] or 'handle_action' in row['retained_debug_name']:
                record['internalActionHandlers'].append({'function': row['retained_debug_name'], 'cLine': start, 'watLine': int(row['wat_line'])})
        for row, text in entry_functions(module):
            found = sorted(set(int(m[1]) for m in SELECTOR.finditer(text)))
            entry = {'function': row['retained_debug_name'], 'cLine': int(row['c_line']),
                     'watLine': int(row['wat_line']), 'selectors': found,
                     'bodySha256': hashlib.sha256(text.encode()).hexdigest()}
            record['entrypoints'].append(entry)
            if evidence and name.startswith('AshenBoneyard_'):
                evidence.mkdir(parents=True, exist_ok=True)
                simplified = readable(text, name)
                target = evidence / ('map-specific.c' if row['retained_debug_name']=='on_action' else 'shared.c')
                target.write_text(simplified, encoding='utf-8')
                traces = {str(v): selector_path(simplified, v) for v in found}
                target.with_suffix('.paths.json').write_text(json.dumps(traces, indent=2), encoding='utf-8')
            for value in found:
                verbs.setdefault(str(value), []).append({'module': name, 'function': row['retained_debug_name']})
        modules.append(record)
        if (index+1) % 10 == 0:
            print(f'Inventoried {index+1}/{len(manifest["modules"])} modules', flush=True)
    result = {'scope': 'Explicit parameter-1 equality/inequality selectors in recovered map on_action entrypoints and on_action_shared. Not all internal comparisons or dynamic callbacks.',
              'sourceModuleCount': len(manifest['modules']), 'modules': modules,
              'explicitEntryVerbs': dict(sorted(verbs.items(), key=lambda pair:int(pair[0])))}
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(result, indent=2)+'\n').encode()
    output.write_bytes(gzip.compress(payload, mtime=0) if output.suffix == '.gz' else payload)
    print(f'{len(modules)} modules; {len(verbs)} distinct explicit entry selectors', flush=True)


if __name__ == '__main__':
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument('--modules', required=True, type=Path)
    cli.add_argument('--output', required=True, type=Path)
    cli.add_argument('--evidence', type=Path)
    args = cli.parse_args()
    inventory(args.modules, args.output, args.evidence)
