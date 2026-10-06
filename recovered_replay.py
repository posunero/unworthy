"""Build-specific, schema-based replay export and source-traced action labels.

Both the recording envelope and actions use recovered build-107842 descriptors.
"""
import argparse
from collections import Counter
import hashlib
import gzip
import json
from functools import lru_cache
from pathlib import Path
import struct
import zlib

from google.protobuf import descriptor_pb2, descriptor_pool, message_factory

SCHEMA = Path(__file__).parent / 'assets/protocols/ls_types-107842.pb'
ROUTER_SCHEMA = SCHEMA.with_name('cf_ls_router-107842.pb')
CATALOG = SCHEMA.with_name('ashen-boneyard-107842.json')
SEMANTICS = SCHEMA.with_name('action-semantics-107842.json')
CATALOG_CORPUS = SCHEMA.with_name('map-catalogs-107842.json.gz')
BOT_OPTIONS = ('currentlyActive','buildWorkers','maintainSupply','buildStructures','buildArmy','buildExpansion')


@lru_cache(maxsize=1)
def message_classes():
    pool = descriptor_pool.DescriptorPool()
    pool.AddSerializedFile(descriptor_pb2.DESCRIPTOR.serialized_pb)
    pool.AddSerializedFile(SCHEMA.read_bytes())
    pool.AddSerializedFile(ROUTER_SCHEMA.read_bytes())

    def cls(name):
        descriptor = pool.FindMessageTypeByName(name)
        if hasattr(message_factory, 'GetMessageClass'):
            return message_factory.GetMessageClass(descriptor)
        return message_factory.MessageFactory(pool).GetPrototype(descriptor)

    return cls('cf_ls_router.GameAction'), cls('ls_types.SPRecordingFooter'), cls('ls_types.NetAction')


def as_dict(message):
    """Include proto3 defaults but preserve optional-field and oneof presence."""
    result = {}
    present = {field.name for field, _ in message.ListFields()}
    for f in message.DESCRIPTOR.fields:
        if f.containing_oneof and f.name not in present:
            continue
        value = getattr(message, f.name)
        def convert(v):
            if f.type == f.TYPE_MESSAGE:
                return as_dict(v)
            if f.type == f.TYPE_ENUM:
                enum = f.enum_type.values_by_number.get(v)
                return enum.name if enum else v
            if f.type == f.TYPE_BYTES:
                return {'hex': v.hex()}
            return v
        repeated = f.is_repeated if hasattr(f, 'is_repeated') else f.label == f.LABEL_REPEATED
        if repeated:
            result[f.name] = [convert(v) for v in value]
        elif f.type != f.TYPE_MESSAGE or f.name in present:
            result[f.name] = convert(value)
    return result


def has_unknown_fields(message):
    original = type(message)()
    original.CopyFrom(message)
    clean = type(message)()
    clean.CopyFrom(message)
    clean.DiscardUnknownFields()
    # Older protobuf runtimes can retain stale nested byte-size caches after
    # DiscardUnknownFields. Copy both trees before comparing serializations.
    normalized = type(message)()
    normalized.CopyFrom(clean)
    return normalized.SerializeToString() != original.SerializeToString()


def varint(data, pos):
    value = 0
    for shift in range(0, 70, 7):
        if pos >= len(data):
            raise ValueError('Truncated record length')
        byte = data[pos]
        pos += 1
        if shift == 63 and byte > 1:
            raise ValueError('Varint overflow')
        value |= (byte & 127) << shift
        if byte < 128:
            return value, pos
    raise ValueError('Varint overflow')


class SelectionTracker:
    def __init__(self):
        self.selections = {}
        self.control_groups = {}

    def apply(self, participant, kind, payload):
        if kind in ('setControlGroup', 'modifyControlGroup'):
            key = (participant, payload.get('controlGroupIndex', 0))
            if key[1] > 10:
                return {'controlGroupIndexAccepted': False,
                        'controlGroupRejection': 'Native participant dispatcher rejects indices above 10 (0x1800c9110)'}
            previous, known = self.control_groups.get(key, ([], False))
            if kind == 'setControlGroup':
                entities, known = list(payload['entityId']), True
            else:
                entities = [entity for entity in previous if entity not in payload['toRemoveEntityId']]
                entities += [entity for entity in payload['entityId'] if entity not in entities]
            self.control_groups[key] = (entities, known)
            return {'controlGroupEntityIds': list(entities),
                    'controlGroupEstablishedByRecordedSet': known,
                    'controlGroupIndexAccepted': True}
        key = (participant, payload.get('selectionIndex', 0))
        if kind == 'setSelection':
            self.selections[key] = (list(payload['entityId']), True)
        elif kind == 'modifySelection':
            previous, known = self.selections.get(key, ([], False))
            removed = set(payload['toRemoveEntityId'])
            entities = [entity for entity in previous if entity not in removed]
            for entity in payload['toAddEntityId']:
                if entity not in entities:
                    entities.append(entity)
            self.selections[key] = (entities, known)
        if kind in ('selectionOrder', 'mapAction'):
            entities, known = self.selections.get(key, ([], False))
            return {'selectionEntityIds': list(entities),
                    'selectionEstablishedByRecordedSet': known}
        return {}


@lru_cache(maxsize=1)
def load_catalog():
    catalog = json.loads(CATALOG.read_text(encoding='utf-8'))
    catalog['mapVerbs'] = json.loads(SEMANTICS.read_text(encoding='utf-8'))
    catalog['semanticsReferenceModule'] = 'AshenBoneyard_245eeecf8bdc'
    return catalog


@lru_cache(maxsize=1)
def load_catalog_corpus():
    corpus = json.loads(gzip.decompress(CATALOG_CORPUS.read_bytes()))
    canonical = json.dumps(load_catalog()['archetypes'],sort_keys=True,separators=(',',':')).encode()
    if corpus['baseArchetypesSha256'] != hashlib.sha256(canonical).hexdigest():
        raise ValueError('Catalog corpus does not match its reference catalog')
    return corpus


@lru_cache(maxsize=4)
def catalog_for_hash(runtime_hash):
    reference = load_catalog()
    if runtime_hash == reference['mapRuntimeHash']:
        return reference
    entry = load_catalog_corpus()['maps'].get(runtime_hash)
    if entry is None:
        return None
    archetypes = dict(reference['archetypes'])
    for key in entry['removed']:
        archetypes.pop(key, None)
    archetypes.update(entry['overrides'])
    if len(archetypes) != entry['archetypeCount']:
        raise ValueError('Catalog corpus archetype count mismatch')
    result = {k:v for k,v in reference.items() if k not in ('archetypes','map','mapRuntimeHash')}
    result.update({k:v for k,v in entry.items() if k not in ('overrides','removed')})
    result['archetypes'] = archetypes
    return result


def map_payload(payload, mode):
    """Expose source-established field roles without manufacturing missing state."""
    fields = {
        'ui': {'kind':'commandStringId','data':'dataStringId','subject':'player'},
        'widget': {'subject':'widgetEntityId','kind':'commandStringId','data':'dataStringId'},
        'entity_vm': {'subject':'entityId','kind':'commandStringId','data':'numericData'},
        'chat_notification': {'data':'textStringId'},
        'sequence_custom': {'subject':'sequencePlayerId','kind':'sequenceArchetypeId','data':'eventStringId'},
        'sequence': {'subject':'sequencePlayerId','kind':'sequenceArchetypeId'},
        'transmission': {'subject':'transmissionPlayerId','kind':'transmissionArchetypeId'},
        'cancel': {'subject':'entityId','data':'queueIndex'},
        'cargo': {'subject':'carrierEntityId','data':'cargoEntityId'},
        'item': {'kind':'itemEntityId','data':'orderData','subject':'targetEntityId'},
        'ability': {'data':'orderData','subject':'targetEntityId','kind':'targetKind'},
        'smart': {'data':'orderData','subject':'targetEntityId','kind':'targetKind'},
        'single_smart': {'subject':'entityId'},
        'spawn': {'kind':'entityKind','subject':'spawnSubject','data':'rawAngle'},
        'participant_subject': {'subject':'participantEntityId'},
        'participant_index': {'data':'participantIndex'},
        'player': {'data':'playerEntityId'},
        'subject': {'subject':'subject'},
        'ping': {'subject':'targetEntityId','kind':'pingKind','data':'data'},
        'bot_options': {'data':'rawOptions'},
    }
    result = {label:payload[key] for key,label in fields.get(mode,{}).items() if key in payload}
    if mode == 'single_smart':
        result['queued'] = bool(payload.get('data', 0))
    if mode == 'bot_options':
        result['enabled'] = bool(payload.get('data', 0) & 1)
        result['options'] = {name:bool(payload.get('data',0) & (1<<i)) for i,name in enumerate(BOT_OPTIONS)}
        result['uninterpretedOptionBits'] = payload.get('data',0) & ~63
    if mode == 'camera':
        def signed(value):
            value &= 0xffffffff
            return value if value < 2**31 else value-2**32
        for key,label in [('subject','headingDegrees'),('kind','pitchDegrees')]:
            if key in payload:
                numerator = signed(payload[key]) * 2**28
                q = (abs(numerator) // 45) * (-1 if numerator < 0 else 1)
                result[label] = signed(q) * 45 / 2**28
        if 'data' in payload:
            result['zoomWorld'] = signed(payload['data'] << 14) / 16384
    return result


def native_participant_dispatch(kind, payload):
    """Reconstruct the map-call arguments made by native 0x1800c9110.

This describes a dispatch request after native validity gates, not proof those
gates passed. isAI is preserved in the record but is not read in this bridge.
"""
    if kind in ('setSelection','modifySelection'):
        return {'verb':580466764,'operation':'selection update then participant_selection_changed',
                'selectionIndex':payload.get('selectionIndex',0)}
    if kind == 'selectionOrder':
        queued,smart=bool(payload.get('queued',False)),bool(payload.get('smart',False))
        verb=(307192056 if queued else 2626128676) if smart else (3322138414 if queued else 2472102578)
        return {'verb':verb,'data':payload['orderType'],'subject':payload['targetEntityId'],
                'kind':payload['targetEntityKind'],'position':payload.get('position',{'x':0,'y':0}),
                'selectionIndex':payload.get('selectionIndex',0),
                'isAIUsedByThisBridge':False}
    if kind == 'mapAction':
        return {key:payload.get(key,0) for key in ('verb','data','subject','kind','x','y','selectionIndex')}
    if kind == 'setBotOptions':
        return {'verb':3926104316,'data':sum((1<<i) for i,name in enumerate(BOT_OPTIONS) if payload.get(name,False))}
    if kind in ('setControlGroup','modifyControlGroup'):
        return {'operation':kind,'index':payload.get('controlGroupIndex',0),
                'staticIndexAccepted':payload.get('controlGroupIndex',0)<=10,
                'verb':None}
    return None


def resolve_order(order, catalog):
    """Mirror from_order_data: first existing archetype at offsets 0..29."""
    for index in range(catalog['maxCommandIndexExclusive']):
        key = str((order - index) & 0xffffffff)
        entry = catalog['archetypes'].get(key)
        if entry is not None:
            result = {'archetypeId': int(key), 'name': entry['id'],
                      'baseType': entry['__base_type'], 'commandIndex': index,
                      'isAbilityArchetype': 'Ability' in entry['__base_type']}
            commands = entry.get('commands', [])
            if index < len(commands):
                result['command'] = commands[index]
            return result
    return None


def annotate(event, catalog):
    """Describe intent only; never turn a command into a simulated outcome."""
    command = event.get('commandType')
    event['category'] = 'system'
    event['description'] = event['actionType'] or 'Unrecognized action'
    if not command:
        if event['actionType'] == 'chat':
            event['category'] = 'chat'
            event['description'] = event['decoded']['chat']['text']
        return
    payload = event['decoded']['participantAction'][command]
    event['description'] = command
    event['category'] = 'selection' if 'Selection' in command or 'ControlGroup' in command else 'system'
    if command not in ('selectionOrder', 'mapAction'):
        return
    if command == 'selectionOrder':
        event['category'] = 'gameplay_command'
        event['description'] = 'Smart/context order' if payload.get('smart') else 'Selection order'
        event['queued'] = payload.get('queued', False)
        code = payload['orderType']
        position = payload.get('position')
        smart = payload.get('smart', False)
        event['abilityExecutionRequested'] = True
    else:
        code = payload.get('data', 0)
        verb = catalog['mapVerbs'].get(str(payload['verb'])) if catalog else None
        event['mapVerbRecognized'] = verb is not None
        event['mapVerbNamed'] = bool(verb and verb['name'])
        event['description'] = (verb and verb['name']) or f"Map action {payload['verb']}"
        event['category'] = (verb or {}).get('category', 'unresolved_map_action')
        if verb:
            event['mapVerbEvidence'] = verb
            event['interpretationStatus'] = verb['status']
            event['runtimeRequirements'] = verb.get('requires', [])
            event['interpretedPayload'] = map_payload(payload, verb.get('payloadMode'))
        mode = (verb or {}).get('payloadMode')
        event['abilityExecutionRequested'] = payload['verb'] in (
            2472102578,3322138414,1432744753,2626128676,307192056,
            815962355,81781465,1304751467,1756538168,2407219556,3534171667)
        smart = mode in ('smart', 'single_smart')
        event['queued'] = payload['verb'] in (3322138414,307192056,1756538168) or (mode == 'single_smart' and bool(payload.get('data',0)))
        position = {'x': payload['x'], 'y': payload['y']} if 'x' in payload and 'y' in payload else None
        if payload['verb'] == 3703223256 and catalog:
            event['description'] = f"Cancel production queue item {payload.get('data', 0)} on entity {payload.get('subject', 0)}"
        if mode not in ('ability','smart','item'):
            code = None  # data in UI/chat/cancel messages is NOT an ability ID
    if position and catalog:
        event['positionWorld'] = {axis: value / catalog['coordinateScale'] for axis, value in position.items()}
    if code is not None and catalog:
        resolved = resolve_order(code, catalog)
        event['orderResolved'] = bool(resolved and resolved['isAbilityArchetype']) or (code == 0 and smart)
        if resolved:
            event['abilityCommand'] = resolved
            target = resolved.get('command', {}).get('unit') or resolved.get('command', {}).get('upgrade')
            event['description'] += f": {resolved['name']} [{resolved['commandIndex']}]"
            if target and target != 'emptyRef':
                event['description'] += f" → {target}"
        elif code:
            event['description'] += f" (unresolved order {code})"


def read_container(path):
    data = Path(path).read_bytes()
    if len(data) < 20:
        raise ValueError('Truncated recording header')
    header = dict(zip(('magic', 'version', 'data_offset', 'changelist', 'footer_length'), struct.unpack('<5I', data[:20])))
    if header['changelist'] != 107842:
        raise ValueError('Recovered schema is validated only for build 107842')
    if (header['magic'], header['version'], header['data_offset']) != (0xE3B0A49D, 2, 20):
        raise ValueError('Unsupported recording header')
    footer_length = header['footer_length']
    if footer_length > len(data) - 20:
        raise ValueError('Footer length exceeds recording size')
    end = len(data) - footer_length
    decoder = zlib.decompressobj(16 + zlib.MAX_WBITS)
    try:
        raw = decoder.decompress(data[20:end]) + decoder.flush()
    except zlib.error as exc:
        raise ValueError(f'Invalid gzip stream: {exc}') from exc
    if not decoder.eof or decoder.unused_data:
        raise ValueError('Truncated gzip stream or unexpected bytes before footer')
    return header, raw, data[end:], hashlib.sha256(data).hexdigest()


def export_recovered(path):
    header, raw_data, footer_bytes, source_hash = read_container(path)
    Record, Footer, NetAction = message_classes()
    footer = Footer()
    footer.ParseFromString(footer_bytes)
    catalog = catalog_for_hash(footer.mapRuntimeHash)
    tracker, counts, events = SelectionTracker(), Counter(), []
    pos = 0
    while pos < len(raw_data):
        offset = pos
        length, pos = varint(raw_data, pos)
        if not length or length >= 2**31 or pos + length > len(raw_data):
            raise ValueError(f'Invalid record length at decompressed offset {offset}')
        raw = raw_data[pos:pos + length]
        pos += length
        record = Record()
        record.ParseFromString(raw)
        action = NetAction()
        action.ParseFromString(record.netaction.bytes)
        kind = action.WhichOneof('Action')
        event = {'index': len(events), 'decompressedOffset': offset,
                 'rawHex': raw.hex(), 'timestampTicks': record.timeStamp,
                 'clientId': record.clientID, 'actionType': kind,
                 'decoded': as_dict(action),
                 'hasUnknownFields': has_unknown_fields(record) or has_unknown_fields(action)}
        counts[kind or 'unrecognized'] += 1
        if kind == 'participantAction':
            participant = action.participantAction
            command = participant.WhichOneof('ParticipantAction')
            event['participantId'] = participant.participantId
            event['commandType'] = command
            if command:
                payload = as_dict(getattr(participant, command))
                event['nativeDispatch'] = native_participant_dispatch(command,payload)
                event.update(tracker.apply(participant.participantId, command, payload))
        annotate(event, catalog)
        events.append(event)
    names = {e['clientId']: e['decoded']['bootstrap'].get('displayName', {}).get('userName')
             for e in events if e['actionType'] == 'bootstrap'}
    for event in events:
        event['clientName'] = names.get(event['clientId'])
    return {'header': header,
            'sourceSha256': source_hash,
            'schemaSha256': hashlib.sha256(SCHEMA.read_bytes()).hexdigest(),
            'routerSchemaSha256': hashlib.sha256(ROUTER_SCHEMA.read_bytes()).hexdigest(),
            'catalogMatched': catalog is not None,
            'catalogSourceMap': catalog['map'] if catalog else None,
            'semanticsReferenceModule': catalog['semanticsReferenceModule'] if catalog else None,
            'footer': as_dict(footer), 'footerRawHex': footer_bytes.hex(),
            'footerHasUnknownFields': has_unknown_fields(footer),
            'coverage': {'records': len(events), 'decompressedBytesConsumed': pos,
                         'recordsWithUnknownFields': sum(e['hasUnknownFields'] for e in events),
                         'actionTypes': dict(counts),
                         'commandTypes': dict(Counter(e['commandType'] for e in events if 'commandType' in e)),
                         'categories': dict(Counter(e['category'] for e in events)),
                         'semanticCoverageAvailable': catalog is not None,
                         'unresolvedOrders': sum(e.get('orderResolved') is False for e in events) if catalog else None,
                         'unnamedMapActions': sum(e.get('mapVerbNamed') is False for e in events)},
            'limitations': [
                'Named protocol fields do not establish command outcomes or entity types.',
                'Selection lists reflect recorded updates; simulation may remove dead entities.',
                'Timestamps are router recording ticks; they are not simulation-step indices.',
                'Catalog semantics apply only to the exact matching mapRuntimeHash.',
                'Recognized handlers, UI string hashes, and smart-order outcomes may remain unresolved.',
            ], 'events': events}


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument('replay', type=Path)
    cli.add_argument('--output', required=True, type=Path)
    cli.add_argument('--text', type=Path, help='Also write a readable timeline')
    args = cli.parse_args()
    result = export_recovered(args.replay)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2), encoding='utf-8')
    if args.text:
        lines = [f"{result['footer']['mapName']} — build {result['header']['changelist']}",
                 'Recording timestamps in raw ticks. Commands describe intent, not successful outcomes.', '']
        for event in result['events']:
            who = event['clientName'] or f"client {event['clientId']}"
            selected = event.get('selectionEntityIds')
            suffix = f" | recorded selection: {selected}" if selected is not None else ''
            if event.get('queued'):
                suffix += ' | queued'
            if 'positionWorld' in event:
                suffix += f" | position: {event['positionWorld']}"
            lines.append(f"{event['timestampTicks']:>8}  {who:16}  [{event['category']}] {event['description']}{suffix}")
        args.text.parent.mkdir(parents=True, exist_ok=True)
        args.text.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print(json.dumps({'footer': result['footer'], 'coverage': result['coverage']}, indent=2))


if __name__ == '__main__':
    main()
