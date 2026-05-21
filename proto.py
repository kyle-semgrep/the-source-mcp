"""Tiny protobuf wire-format encoder + decoder.

We don't have the `.proto` files for The Source's API, but we've decoded the
relevant request/response shapes by hand from captured cURLs. These helpers
build and parse bytes using the wire format spec:
  https://protobuf.dev/programming-guides/encoding/

Scope: only what's needed for /knowledge/create, /announcement/create
(drafts), and /teams/list response parsing. Easy to extend.
"""
from typing import Iterator


# ---------- encoding ----------

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


# ---------- decoding ----------

def _read_varint(data: bytes, i: int) -> tuple[int, int]:
    result, shift = 0, 0
    while True:
        b = data[i]
        i += 1
        result |= (b & 0x7F) << shift
        if not (b & 0x80):
            return result, i
        shift += 7


def iter_fields(data: bytes, start: int = 0, end: int | None = None) -> Iterator[tuple[int, int, object]]:
    """Yield (field_number, wire_type, value) over a serialized message.

    For wire_type 0 (varint), value is an int.
    For wire_type 2 (length-delim), value is bytes.
    For wire types 1 / 5, value is bytes (8 / 4 bytes raw).
    """
    if end is None:
        end = len(data)
    i = start
    while i < end:
        tag, i = _read_varint(data, i)
        field, wire = tag >> 3, tag & 7
        if wire == 0:
            v, i = _read_varint(data, i)
            yield field, wire, v
        elif wire == 2:
            length, i = _read_varint(data, i)
            yield field, wire, data[i:i + length]
            i += length
        elif wire == 1:
            yield field, wire, data[i:i + 8]
            i += 8
        elif wire == 5:
            yield field, wire, data[i:i + 4]
            i += 4
        else:
            raise ValueError(f"unsupported wire type {wire} at offset {i}")


# ---------- request builders ----------

# UUID identifying the calling user's "My Private Pages" container. This was
# captured from Kyle's session and may differ per user; if so we'd need a
# discovery step (call /knowledge/list with no parent and look at the root).
# Hard-coded for now since the repo is single-tenant in practice.
PRIVATE_CONTEXT_UUID = "b630cb89-f55b-44cf-b5da-a1e1142be8ba"


def build_create_announcement_draft(
    title: str,
    html_body: str,
    destination_group_id: str,
    private_context_id: str = PRIVATE_CONTEXT_UUID,
) -> bytes:
    """/api/v1/announcement/create body for a DRAFT post (not published).

    Field map from diffing two captured cURLs (publish vs save-as-draft):
      outer:
        field 1  = announcement sub-message:
          field 2  = slug         (string)
          field 3  = title        (string)
          field 4  = body html    (string)
          field 7  = { field 1 = <private_context_uuid> }
          field 37 = "50"         (icon id; mimicked verbatim)
          field 38 = { field 1 = <destination_group_uuid> }

    The publish variant additionally set field 10 (= a duplicate of the
    private-context UUID) and field 39 (= a nested visibility/notify
    block). Omitting both keeps the announcement in draft state.
    """
    inner = (
        field_string(2, title)
        + field_string(3, title)
        + field_string(4, html_body)
        + field_submessage(7, field_string(1, private_context_id))
        + field_string(37, "50")
        + field_submessage(38, field_string(1, destination_group_id))
    )
    return field_submessage(1, inner)


def build_delete_announcement(announcement_id: str) -> bytes:
    """/api/v1/announcement/delete body. Single field 1 = announcement UUID."""
    return field_string(1, announcement_id)


def build_get_announcement(announcement_id: str) -> bytes:
    """/api/v1/announcement/get body. Single field 1 = announcement UUID."""
    return field_string(1, announcement_id)


def extract_announcement_title(body: bytes) -> str | None:
    """Walk an announcement-shaped protobuf and return the title (field 3
    of the Announcement message). The /announcement/get response wraps the
    Announcement inside an envelope, so we look both at top-level field 3
    and at field 3 of any field-1 sub-message.
    """
    for f, w, v in iter_fields(body):
        if w != 2 or not isinstance(v, bytes):
            continue
        if f == 3:
            try:
                return v.decode("utf-8")
            except UnicodeDecodeError:
                return None
        if f == 1:
            for f2, w2, v2 in iter_fields(v):
                if f2 == 3 and w2 == 2 and isinstance(v2, bytes):
                    try:
                        return v2.decode("utf-8")
                    except UnicodeDecodeError:
                        return None
    return None


def build_list_announcements_draft_only() -> bytes:
    """/api/v1/announcement/list body to fetch only the caller's drafts.

    ListAnnouncementRequest schema (from the JS proto bundle):
      field 10 (bool) = draft_only
    Setting just this scopes the response to drafts visible to the caller
    (the auth layer filters to only the caller's own drafts in practice).
    """
    return field_varint(10, 1)


# ---------- response parsers ----------

def parse_teams_list_response(body: bytes) -> list[dict]:
    """Best-effort parse of /api/v1/teams/list response.

    Each top-level field-1 sub-message represents one team; inside,
    field 1 is the UUID (string) and field 2 is the display name.
    """
    teams: list[dict] = []
    for field, wire, value in iter_fields(body):
        if field != 1 or wire != 2:
            continue
        assert isinstance(value, bytes)
        team: dict[str, str] = {}
        for tf, tw, tv in iter_fields(value):
            if tw != 2 or not isinstance(tv, bytes):
                continue
            if tf == 1 and "uuid" not in team:
                try:
                    team["uuid"] = tv.decode("utf-8")
                except UnicodeDecodeError:
                    pass
            elif tf == 2 and "name" not in team:
                try:
                    team["name"] = tv.decode("utf-8")
                except UnicodeDecodeError:
                    pass
        if "uuid" in team and "name" in team:
            teams.append(team)
    return teams


def parse_list_announcements_response(body: bytes) -> list[dict]:
    """Parse a ListAnnouncementResponse.

    Response shape (from JS proto bundle):
      field 1 = repeated AnnouncementLite
      field 2 = int64 next_start  (pagination cursor; ignored)

    AnnouncementLite (subset we extract):
      field 1  = string  announcement_id
      field 2  = string  title
      field 7  = int64   created (unix seconds)
      field 23 = int64   last_updated (unix seconds)
      field 25 = TeamLite owner_group  { field 1 uuid, field 2 name }
      field 26 = string  body (html)
    """
    out: list[dict] = []
    for field, wire, value in iter_fields(body):
        if field != 1 or wire != 2:
            continue
        assert isinstance(value, bytes)
        d: dict = {}
        for tf, tw, tv in iter_fields(value):
            if tw == 2 and isinstance(tv, bytes):
                if tf == 1:
                    d["id"] = tv.decode("utf-8", errors="replace")
                elif tf == 2:
                    d["title"] = tv.decode("utf-8", errors="replace")
                elif tf == 25:
                    team: dict = {}
                    for gf, gw, gv in iter_fields(tv):
                        if gw == 2 and isinstance(gv, bytes):
                            if gf == 1:
                                team["uuid"] = gv.decode("utf-8", errors="replace")
                            elif gf == 2:
                                team["name"] = gv.decode("utf-8", errors="replace")
                    if team:
                        d["destination"] = team
                elif tf == 26:
                    d["body_html"] = tv.decode("utf-8", errors="replace")
            elif tw == 0:
                if tf == 7:
                    d["created_ts"] = tv
                elif tf == 23:
                    d["last_updated_ts"] = tv
        out.append(d)
    return out
