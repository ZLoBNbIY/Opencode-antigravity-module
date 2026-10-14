"""Pure-Python DeepSeekHashV1 PoW solver; no WASM/runtime downloads required.

The permutation and challenge format are based on the MIT-licensed
shaohuahuawww/deepseek-pow project. See deepseek-plugin/NOTICE.md.
"""
import base64
import json
import struct

_MASK = 0xFFFFFFFFFFFFFFFF
_RC = (
    0x0000000000000001, 0x0000000000008082, 0x800000000000808A, 0x8000000080008000,
    0x000000000000808B, 0x0000000080000001, 0x8000000080008081, 0x8000000000008009,
    0x000000000000008A, 0x0000000000000088, 0x0000000080008009, 0x000000008000000A,
    0x000000008000808B, 0x800000000000008B, 0x8000000000008089, 0x8000000000008003,
    0x8000000000008002, 0x8000000000000080, 0x000000000000800A, 0x800000008000000A,
    0x8000000080008081, 0x8000000000008080, 0x0000000080000001, 0x8000000080008008,
)
_PI = (0, 6, 12, 18, 24, 3, 9, 10, 16, 22, 1, 7, 13, 19, 20, 4, 5, 11, 17, 23, 2, 8, 14, 15, 21)
_RHO = (0, 44, 43, 21, 14, 28, 20, 3, 45, 61, 1, 6, 25, 8, 18, 27, 36, 10, 15, 56, 62, 55, 39, 41, 2)


def _rotl(value, count):
    if not count:
        return value
    return ((value << count) | (value >> (64 - count))) & _MASK


def deepseek_hash_v1(data):
    """DeepSeekHashV1: SHA3 sponge using Keccak-f rounds 1..23 (skip round 0)."""
    rate, state = 136, [0] * 25
    offset = 0
    while offset + rate <= len(data):
        for lane in range(rate // 8):
            state[lane] ^= struct.unpack_from("<Q", data, offset + lane * 8)[0]
        _permute(state)
        offset += rate
    block = bytearray(rate)
    remaining = len(data) - offset
    block[:remaining] = data[offset:]
    block[remaining] = 0x06
    block[-1] |= 0x80
    for lane in range(rate // 8):
        state[lane] ^= struct.unpack_from("<Q", block, lane * 8)[0]
    _permute(state)
    return struct.pack("<4Q", *state[:4])


def _permute(state):
    a = state[:]
    for round_index in range(1, 24):
        columns = [a[x] ^ a[x + 5] ^ a[x + 10] ^ a[x + 15] ^ a[x + 20] for x in range(5)]
        delta = [columns[(x - 1) % 5] ^ _rotl(columns[(x + 1) % 5], 1) for x in range(5)]
        for x in range(5):
            for index in range(x, 25, 5):
                a[index] ^= delta[x]
        b = [_rotl(a[_PI[i]], _RHO[i]) for i in range(25)]
        for y in range(5):
            row = y * 5
            for x in range(5):
                a[row + x] = b[row + x] ^ ((~b[row + (x + 1) % 5] & _MASK) & b[row + (x + 2) % 5])
        a[0] ^= _RC[round_index]
    state[:] = a


def solve_pow(challenge, cancel=None):
    if not isinstance(challenge, dict) or challenge.get("algorithm") != "DeepSeekHashV1":
        raise ValueError("Unsupported DeepSeek proof-of-work challenge")
    difficulty = challenge.get("difficulty")
    if not isinstance(difficulty, int) or isinstance(difficulty, bool) or not 0 < difficulty <= 1_000_000:
        raise ValueError("Invalid DeepSeek proof-of-work difficulty")
    try:
        target = bytes.fromhex(challenge["challenge"])
        prefix = f"{challenge['salt']}_{challenge['expire_at']}_".encode("utf-8")
        signature = challenge["signature"]
        target_path = challenge.get("target_path", "/api/v0/chat/completion")
    except (KeyError, TypeError, ValueError):
        raise ValueError("Invalid DeepSeek proof-of-work challenge") from None
    if len(target) != 32 or not isinstance(signature, str) or not signature or target_path != "/api/v0/chat/completion":
        raise ValueError("Invalid DeepSeek proof-of-work target")
    for answer in range(difficulty):
        if answer % 1024 == 0 and cancel is not None and cancel.is_set():
            raise InterruptedError("cancelled")
        if deepseek_hash_v1(prefix + str(answer).encode("ascii")) == target:
            payload = {
                "algorithm": challenge["algorithm"], "challenge": challenge["challenge"],
                "salt": challenge["salt"], "answer": answer, "signature": signature,
                "target_path": target_path,
            }
            return base64.b64encode(json.dumps(payload, separators=(",", ":")).encode()).decode("ascii")
    raise ValueError("DeepSeek proof-of-work challenge expired or had no solution")
