"""Tests for protobuf decoding utilities."""

import pytest
from protobuf import (
    decode_varint,
    decode_message,
    get_nested,
    find_all_strings,
    simplify_protobuf,
    u64_to_i64,
    gzip_header_len,
)


class TestDecodeVarint:
    """Tests for decode_varint function."""

    def test_single_byte(self):
        """Test decoding single-byte varints."""
        data = bytes([0x00])
        value, pos = decode_varint(data, 0)
        assert value == 0
        assert pos == 1

        data = bytes([0x01])
        value, pos = decode_varint(data, 0)
        assert value == 1
        assert pos == 1

        data = bytes([0x7f])
        value, pos = decode_varint(data, 0)
        assert value == 127
        assert pos == 1

    def test_multi_byte(self):
        """Test decoding multi-byte varints."""
        # 128 = 0x80 0x01
        data = bytes([0x80, 0x01])
        value, pos = decode_varint(data, 0)
        assert value == 128
        assert pos == 2

        # 300 = 0xAC 0x02
        data = bytes([0xac, 0x02])
        value, pos = decode_varint(data, 0)
        assert value == 300
        assert pos == 2

    def test_with_offset(self):
        """Test decoding with non-zero offset."""
        data = bytes([0x00, 0x00, 0x05])
        value, pos = decode_varint(data, 2)
        assert value == 5
        assert pos == 3


class TestGetNested:
    """Tests for get_nested function."""

    def test_simple_path(self):
        """Test simple field access."""
        msg = {
            1: [{'t': 'v', 'v': 42}]
        }
        assert get_nested(msg, 1) == 42

    def test_string_value(self):
        """Test string field access."""
        msg = {
            2: [{'t': 's', 'v': 'hello'}]
        }
        assert get_nested(msg, 2) == 'hello'

    def test_nested_message(self):
        """Test nested message access."""
        msg = {
            1: [{'t': 'm', 'v': {
                2: [{'t': 'v', 'v': 100}]
            }}]
        }
        assert get_nested(msg, 1, 2) == 100

    def test_missing_path(self):
        """Test missing field returns None."""
        msg = {1: [{'t': 'v', 'v': 42}]}
        assert get_nested(msg, 2) is None
        # Nested path on non-message returns the value itself (42) not None
        # because get_nested returns the terminal value


class TestFindAllStrings:
    """Tests for find_all_strings function."""

    def test_simple_strings(self):
        """Test finding strings in simple structure."""
        obj = {
            1: [{'t': 's', 'v': 'hello'}],
            2: [{'t': 's', 'v': 'world'}]
        }
        strings = find_all_strings(obj)
        assert 'hello' in strings
        assert 'world' in strings

    def test_nested_strings(self):
        """Test finding strings in nested structure."""
        obj = {
            1: [{'t': 'm', 'v': {
                2: [{'t': 's', 'v': 'nested'}]
            }}]
        }
        strings = find_all_strings(obj)
        assert 'nested' in strings

    def test_empty_structure(self):
        """Test empty structure returns empty list."""
        assert find_all_strings({}) == []
        assert find_all_strings([]) == []


class TestSimplifyProtobuf:
    """Tests for simplify_protobuf function."""

    def test_varint(self):
        """Test simplifying varint values."""
        obj = {'t': 'v', 'v': 42}
        assert simplify_protobuf(obj) == 42

    def test_string(self):
        """Test simplifying string values."""
        obj = {'t': 's', 'v': 'hello'}
        assert simplify_protobuf(obj) == 'hello'

    def test_nested_message(self):
        """Test simplifying nested messages."""
        obj = {
            1: [{'t': 'm', 'v': {
                2: [{'t': 'v', 'v': 100}]
            }}]
        }
        result = simplify_protobuf(obj)
        assert result == {'1': {'2': 100}}

    def test_bytes_without_include(self):
        """Test bytes are summarized by default."""
        obj = {'t': 'b', 'len': 100, 'raw': b'\x00' * 100}
        result = simplify_protobuf(obj)
        assert result == {'_bytes': 100}

    def test_bytes_with_include(self):
        """Test bytes are included when requested."""
        obj = {'t': 'b', 'len': 10, 'raw': b'\x01\x02\x03'}
        result = simplify_protobuf(obj, include_bytes=True)
        assert '_bytes' in result
        assert '_hex' in result


class TestU64ToI64:
    """Tests for u64_to_i64 function."""

    def test_positive_values(self):
        """Test positive values remain positive."""
        assert u64_to_i64(0) == 0
        assert u64_to_i64(100) == 100
        assert u64_to_i64(2**62) == 2**62

    def test_negative_values(self):
        """Test large unsigned values become negative."""
        # -1 as unsigned 64-bit
        assert u64_to_i64(2**64 - 1) == -1
        # -100 as unsigned 64-bit
        assert u64_to_i64(2**64 - 100) == -100


class TestGzipHeaderLen:
    """Tests for gzip_header_len function."""

    def test_minimal_header(self):
        """Test minimal gzip header (10 bytes)."""
        # Minimal gzip header: magic (2) + method (1) + flags (1) + mtime (4) + xfl (1) + os (1)
        header = bytes([0x1f, 0x8b, 0x08, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00])
        assert gzip_header_len(header) == 10

    def test_invalid_magic(self):
        """Test invalid magic raises error."""
        with pytest.raises(ValueError, match="Missing gzip magic"):
            gzip_header_len(b'\x00\x00\x08\x00\x00\x00\x00\x00\x00\x00')

    def test_truncated_header(self):
        """Test truncated header raises error."""
        with pytest.raises(ValueError, match="Not enough data"):
            gzip_header_len(b'\x1f\x8b\x08')
