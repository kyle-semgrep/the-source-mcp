"""Tiny protobuf wire-format encoder.

We don't have the `.proto` files for The Source's API, but we've decoded the
relevant request shapes by hand from captured cURLs. These helpers build the
bytes verbatim using the wire format spec:
  https://protobuf.dev/programming-guides/encoding/

Only what's needed for `/knowledge/create` (and easy to extend later).
"""


def _varint(n: int) -> bytes:
    if n < 0:
        raise ValueError("negative varint not supported")
    out = bytearray()
    while n > 0x7F:
        out.append((n & 0x7F) | 0x80)
        n >>= 7
    out.append(n & 0x7F)
    return bytes(out)


def _tag(field: int, wire: int) -> bytes:
    return _varint((field << 3) | wire)


def field_varint(field: int, value: int) -> bytes:
    return _tag(field, 0) + _varint(value)


def field_string(field: int, value: str) -> bytes:
    data = value.encode("utf-8")
    return _tag(field, 2) + _varint(len(data)) + data


def field_bytes(field: int, value: bytes) -> bytes:
    return _tag(field, 2) + _varint(len(value)) + value


def field_submessage(field: int, body: bytes) -> bytes:
    return _tag(field, 2) + _varint(len(body)) + body


def build_create_knowledge(title: str, html_body: str) -> bytes:
    """Build a /api/v1/knowledge/create request body for a draft page.

    Field numbers reverse-engineered from a captured "save as draft" cURL:

      outer:
        field 1  = knowledge sub-message
          field 2  = slug           (string)
          field 4  = title          (string)
          field 7  = type           (varint; 15 == page)
          field 23 = body html      (string)
          field 38 = 3              (unknown — mimicked verbatim)
          field 42 = sub { field 3 = "50" }   (unknown — mimicked verbatim)
        field 47 = 1                (varint — save-as-draft flag)
    """
    inner = (
        field_string(2, title)
        + field_string(4, title)
        + field_varint(7, 15)
        + field_string(23, html_body)
        + field_varint(38, 3)
        + field_submessage(42, field_string(3, "50"))
    )
    return field_submessage(1, inner) + field_varint(47, 1)
