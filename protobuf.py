"""
Low-level protobuf decoding utilities for Stormgate replay files.
"""

import struct
import zlib
from typing import Any, Dict, List, Optional, Tuple


def gzip_header_len(data: bytes) -> int:
    """
    Return the length of the gzip header for a gzip stream.
    Stormgate .SGReplay files appear to store a gzip header followed by a raw deflate stream.
    """
    # RFC 1952 header: ID1 ID2 CM FLG MTIME(4) XFL OS
    if len(data) < 10:
        raise ValueError("Not enough data for gzip header")
    if data[0:2] != b'\x1f\x8b':
        raise ValueError("Missing gzip magic")
    if data[2] != 8:
        raise ValueError("Unsupported gzip compression method")

    flg = data[3]
    pos = 10

    # FEXTRA
    if flg & 0x04:
        if pos + 2 > len(data):
            raise ValueError("Truncated gzip extra length")
        xlen = struct.unpack('<H', data[pos:pos+2])[0]
        pos += 2
        if pos + xlen > len(data):
            raise ValueError("Truncated gzip extra data")
        pos += xlen

    # FNAME (zero-terminated)
    if flg & 0x08:
        while pos < len(data) and data[pos] != 0:
            pos += 1
        pos += 1

    # FCOMMENT (zero-terminated)
    if flg & 0x10:
        while pos < len(data) and data[pos] != 0:
            pos += 1
        pos += 1

    # FHCRC
    if flg & 0x02:
        pos += 2

    if pos > len(data):
        raise ValueError("Truncated gzip header")
    return pos


def decode_varint(data: bytes, pos: int) -> Tuple[int, int]:
    """Decode a variable-length integer from the data."""
    result = 0
    shift = 0
    while pos < len(data):
        b = data[pos]
        result |= (b & 0x7f) << shift
        pos += 1
        if (b & 0x80) == 0:
            break
        shift += 7
    return result, pos


def _decode_message_internal(data: bytes, depth: int = 0, *, end_group_field: Optional[int] = None) -> Tuple[Optional[Dict], int]:
    """
    Decode a protobuf message into our best-effort field structure.
    Returns (decoded_dict, bytes_consumed).

    - Varints store 'v' as actual int, 't' as 'v'.
    - Fixed64 store 'v' as 8-byte raw (for coordinates), 't' as 'q'.
    - Length-delimited store 'v' as decoded structure or raw bytes, 't' as 'm' or 'b'.
    - Start group / end group store 't' as 'g' with 'v' as list of sub-messages.
    """
    if depth > 100:
        return None, 0

    result: Dict[str, Any] = {}
    pos = 0
    length = len(data)

    while pos < length:
        tag_start = pos
        tag, pos = decode_varint(data, pos)
        if pos > length:
            break
        field_number = tag >> 3
        wire_type = tag & 0x07

        # End group marker - stop parsing this group
        if wire_type == 4:  # END_GROUP
            if end_group_field is not None and field_number == end_group_field:
                return result, pos
            # Unexpected end group - might be corrupted
            return result, tag_start

        value: Any = None

        if wire_type == 0:  # VARINT
            value, pos = decode_varint(data, pos)
            entry = {'t': 'v', 'v': value}
        elif wire_type == 1:  # FIXED64
            if pos + 8 > length:
                break
            value = data[pos:pos+8]
            pos += 8
            entry = {'t': 'q', 'v': value}
        elif wire_type == 5:  # FIXED32
            if pos + 4 > length:
                break
            value = data[pos:pos+4]
            pos += 4
            entry = {'t': 'f', 'v': value}
        elif wire_type == 2:  # LENGTH_DELIMITED
            sub_len, pos = decode_varint(data, pos)
            if pos + sub_len > length:
                break
            sub_data = data[pos:pos+sub_len]
            pos += sub_len
            # Try to decode as nested message
            try:
                nested, consumed = _decode_message_internal(sub_data, depth + 1)
                if nested is not None and consumed == len(sub_data):
                    entry = {'t': 'm', 'v': nested}
                else:
                    # Try as string
                    try:
                        s = sub_data.decode('utf-8')
                        entry = {'t': 's', 'v': s}
                    except:
                        entry = {'t': 'b', 'v': sub_data}
            except:
                entry = {'t': 'b', 'v': sub_data}
        elif wire_type == 3:  # START_GROUP
            # Parse until END_GROUP with same field number
            remaining = data[pos:]
            nested, consumed = _decode_message_internal(remaining, depth + 1, end_group_field=field_number)
            if nested is not None:
                pos += consumed
                entry = {'t': 'g', 'v': nested}
            else:
                break
        else:
            # Unknown wire type
            break

        fn = str(field_number)
        if fn in result:
            # Convert to list if not already
            if not isinstance(result[fn], list):
                result[fn] = [result[fn]]
            result[fn].append(entry)
        else:
            result[fn] = entry

    return result, pos


def decode_message(data: bytes) -> Optional[Dict]:
    """
    Decode a protobuf message, returning the decoded structure or None on failure.
    """
    result, _ = _decode_message_internal(data)
    return result


def get_nested(msg: Dict, *path) -> Any:
    """Navigate through nested protobuf structure using the given path.

    This handles the specific protobuf structure where fields are stored as:
    {field_num: [{'t': type, 'v': value}, ...]}

    Path elements can be integers or strings - both are tried since the decoder
    stores field numbers as strings but callers often use integers.
    """
    current = msg
    for p in path:
        if not isinstance(current, dict):
            return None
        # Try both integer and string versions of the key
        key = p
        if p not in current:
            key = str(p) if isinstance(p, int) else int(p) if isinstance(p, str) and p.isdigit() else None
            if key is None or key not in current:
                return None
        vals = current[key]
        if not vals:
            return None
        entry = vals[0] if isinstance(vals, list) else vals
        if isinstance(entry, dict):
            if entry.get('t') == 'm':
                current = entry['v']
            elif entry.get('t') in ('v', 's', 'q', 'f', 'g'):
                # Return value for varint, string, fixed64, fixed32, group
                return entry['v']
            else:
                return entry
        else:
            return entry
    return current


def find_all_strings(obj: Any, depth: int = 0) -> List[str]:
    """Recursively find all strings in a decoded protobuf structure."""
    if depth > 50:
        return []
    strings = []
    if isinstance(obj, dict):
        if obj.get('t') == 's' and 'v' in obj:
            strings.append(obj['v'])
        for v in obj.values():
            strings.extend(find_all_strings(v, depth + 1))
    elif isinstance(obj, list):
        for item in obj:
            strings.extend(find_all_strings(item, depth + 1))
    return strings


def simplify_protobuf(obj: Any, depth: int = 0, *, include_bytes: bool = False, bytes_hex_limit: int = 64) -> Any:
    """Convert parsed protobuf structure to a simpler JSON-friendly format.

    By default, raw byte blobs are represented as {'_bytes': N} to keep output small.
    Set include_bytes=True to also include a (truncated) hex preview for reverse engineering.
    """
    if depth > 20:
        return None
    if isinstance(obj, dict):
        if 't' in obj:
            # This is a typed value
            t = obj['t']
            if t == 'v':
                return obj['v']
            elif t == 's':
                return obj['v']
            elif t == 'm':
                return simplify_protobuf(obj['v'], depth + 1, include_bytes=include_bytes, bytes_hex_limit=bytes_hex_limit)
            elif t == 'g':
                return simplify_protobuf(obj['v'], depth + 1, include_bytes=include_bytes, bytes_hex_limit=bytes_hex_limit)
            elif t == 'b':
                n = obj.get('len', 0)
                if not include_bytes:
                    return {'_bytes': n}
                raw = obj.get('raw') or b''
                preview = raw[:bytes_hex_limit]
                return {
                    '_bytes': len(raw) if raw else n,
                    '_hex': preview.hex(),
                    '_hex_truncated': (len(raw) > bytes_hex_limit) if raw else (n > bytes_hex_limit),
                }
            elif t == 'f32':
                return {'_f32': obj.get('f'), '_i32': obj.get('i')}
            elif t == 'f64':
                return {'_f64': obj.get('d'), '_i64': obj.get('i')}
            else:
                return obj
        else:
            # This is a field dict
            result = {}
            for k, v in obj.items():
                if isinstance(v, list):
                    simplified = [simplify_protobuf(item, depth + 1, include_bytes=include_bytes, bytes_hex_limit=bytes_hex_limit) for item in v]
                    # If single item, unwrap
                    if len(simplified) == 1:
                        result[str(k)] = simplified[0]
                    else:
                        result[str(k)] = simplified
                else:
                    result[str(k)] = simplify_protobuf(v, depth + 1, include_bytes=include_bytes, bytes_hex_limit=bytes_hex_limit)
            return result
    elif isinstance(obj, list):
        return [simplify_protobuf(item, depth + 1, include_bytes=include_bytes, bytes_hex_limit=bytes_hex_limit) for item in obj]
    else:
        return obj


def pb_get(d: Dict, key: int, default=None):
    """Get a value from a protobuf dict, trying both int and string keys."""
    if not isinstance(d, dict):
        return default
    if key in d:
        return d[key]
    str_key = str(key)
    if str_key in d:
        return d[str_key]
    return default


def pb_has(d: Dict, key: int) -> bool:
    """Check if a protobuf dict has a key (trying both int and string)."""
    if not isinstance(d, dict):
        return False
    return key in d or str(key) in d


def u64_to_i64(val: int) -> int:
    """Convert unsigned 64-bit int to signed."""
    if val >= (1 << 63):
        return val - (1 << 64)
    return val


def fixed_to_world(raw) -> Optional[float]:
    """Convert a fixed64 coordinate to world units.

    Accepts either raw bytes (8 bytes) or an already-decoded int.
    """
    if raw is None:
        return None
    if isinstance(raw, bytes):
        if len(raw) != 8:
            return None
        val = struct.unpack('<Q', raw)[0]
    elif isinstance(raw, int):
        val = raw
    else:
        return None
    signed = u64_to_i64(val)
    return signed / 4096.0
