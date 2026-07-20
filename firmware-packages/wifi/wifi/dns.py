"""A captive-portal DNS responder: bounded, single-question, never forwarding.

``build_response`` parses one datagram and returns the bytes to send back, or
``None`` to drop it. It answers ``A`` for a fixed allow-list of captive-check
names with the AP address, returns an empty successful answer for ``AAAA``, and
``NXDOMAIN`` for any other name. Every malformed, compressed, multi-question,
extra-record, truncated, unsupported-type, or oversized packet is dropped. It
never sets ``RA`` and never forwards, so it cannot be used as an open resolver.
"""

__all__ = ["MAX_PACKET", "build_response"]

MAX_PACKET = 512  # bytes; larger requests or responses are refused
_MAX_GROWTH = 32  # a response may exceed the request by at most this many bytes
_HEADER = 12

# Names answered with the AP's A record (all lowercase). led-effects.test is the
# canonical alias; the rest are OS captive-portal probe hosts.
_A_NAMES = (
    "led-effects.test",
    "connectivitycheck.gstatic.com",
    "captive.apple.com",
    "www.msftconnecttest.com",
    "www.msftncsi.com",
    "detectportal.firefox.com",
)

_TYPE_A = 1
_TYPE_AAAA = 28
_CLASS_IN = 1


def _ip_bytes(ap_ip: str) -> bytes:
    """Convert a dotted-quad string to four network-order bytes."""
    return bytes(int(part) for part in ap_ip.split("."))


def _read_name(packet: bytes, offset: int) -> tuple:
    """Parse an uncompressed DNS QNAME.

    Returns:
        ``(name, next_offset)`` with ``name`` lowercased and dot-joined, or
        ``(None, -1)`` if the name is compressed, malformed, or runs past the
        packet.
    """
    labels = []
    total = 0
    while True:
        if offset >= len(packet):
            return None, -1
        length = packet[offset]
        if length == 0:
            offset += 1
            break
        if length & 0xC0:  # compression pointer or reserved bits: reject
            return None, -1
        offset += 1
        end = offset + length
        total += length + 1
        if end > len(packet) or total > 253:
            return None, -1
        labels.append(bytes(packet[offset:end]).decode().lower())
        offset = end
    return ".".join(labels), offset


def build_response(packet: bytes, ap_ip: str) -> bytes | None:
    """Build the DNS reply for one query datagram, or ``None`` to drop it.

    Args:
        packet: The received UDP payload.
        ap_ip: Dotted-quad AP address returned for matching ``A`` queries.

    Returns:
        The response bytes, or ``None`` when the packet must be dropped.
    """
    if len(packet) < _HEADER or len(packet) > MAX_PACKET:
        return None

    flags0 = packet[2]
    if flags0 & 0x80:  # QR set: this is a response, not a query
        return None
    if (flags0 >> 3) & 0x0F:  # opcode must be standard QUERY (0)
        return None
    if flags0 & 0x02:  # truncated
        return None

    qd = (packet[4] << 8) | packet[5]
    an = (packet[6] << 8) | packet[7]
    ns = (packet[8] << 8) | packet[9]
    ar = (packet[10] << 8) | packet[11]
    if qd != 1 or an or ns or ar:  # exactly one question, no other records
        return None

    name, offset = _read_name(packet, _HEADER)
    if name is None or offset + 4 > len(packet):
        return None
    qtype = (packet[offset] << 8) | packet[offset + 1]
    qclass = (packet[offset + 2] << 8) | packet[offset + 3]
    offset += 4
    if offset != len(packet):  # trailing bytes / extra records
        return None
    if qclass != _CLASS_IN:
        return None
    if qtype not in (_TYPE_A, _TYPE_AAAA):
        return None

    rd = flags0 & 0x01
    question = packet[_HEADER:offset]
    known = name in _A_NAMES

    header = bytearray(_HEADER)
    header[0] = packet[0]  # echo transaction ID
    header[1] = packet[1]
    header[2] = 0x84 | rd  # QR=1, AA=1, RA=0, opcode 0, copy RD
    if not known:
        header[3] = 0x03  # NXDOMAIN
    else:
        header[3] = 0x00
    header[4] = 0x00  # QDCOUNT = 1
    header[5] = 0x01

    answer = b""
    if known and qtype == _TYPE_A:
        header[7] = 0x01  # ANCOUNT = 1
        answer = (
            b"\xc0\x0c"  # name pointer to the question at offset 12
            b"\x00\x01"  # type A
            b"\x00\x01"  # class IN
            b"\x00\x00\x00\x00"  # TTL 0
            b"\x00\x04" + _ip_bytes(ap_ip)  # RDLENGTH 4
        )
    # AAAA on a known name and every unknown name return no answer records.

    response = bytes(header) + bytes(question) + answer
    if len(response) > MAX_PACKET or len(response) > len(packet) + _MAX_GROWTH:
        return None
    return response
