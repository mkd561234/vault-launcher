"""Pure-Python LZO1X decompressor (Unreal Engine 3 package chunks)."""


def lzo1x_decompress(src, out_len):
    """Pure-python LZO1X-1 decompressor."""
    dst = bytearray()
    ip = 0
    n = len(src)

    def get_len(base, mask_bits_val):
        nonlocal ip
        t = mask_bits_val
        if t == 0:
            while src[ip] == 0:
                t += 255
                ip += 1
            t += base + src[ip]
            ip += 1
        return t

    t = src[ip]
    state = 0
    if t > 17:
        t -= 17
        ip += 1
        dst += src[ip:ip + t]
        ip += t
        state = 4 if t >= 4 else t
    while True:
        t = src[ip]
        ip += 1
        if t < 16:
            if state == 0:
                length = get_len(15, t) + 3 if t == 0 else t + 3
                dst += src[ip:ip + length]
                ip += length
                state = 4
                continue
            elif state < 4:
                # 2-byte match, distance computed from t and next byte
                d = (t >> 2) + (src[ip] << 2) + 1
                ip += 1
                for _ in range(2):
                    dst.append(dst[-d])
                state = t & 3
                dst += src[ip:ip + state]
                ip += state
                continue
            else:
                d = (t >> 2) + (src[ip] << 2) + 2049
                ip += 1
                for _ in range(3):
                    dst.append(dst[-d])
                state = t & 3
                dst += src[ip:ip + state]
                ip += state
                continue
        if t >= 64:
            length = (t >> 5) - 1 + 2
            d = ((t >> 2) & 7) + (src[ip] << 3) + 1
            ip += 1
        elif t >= 32:
            length = get_len(31, t & 31) + 2
            d = (src[ip] >> 2) + (src[ip + 1] << 6) + 1
            ip += 2
        else:  # 16..31
            length = get_len(7, t & 7) + 2
            d = ((t & 8) << 11) + (src[ip] >> 2) + (src[ip + 1] << 6)
            ip += 2
            if d == 0:
                break  # end of stream
            d += 16384
        st = src[ip - 2] & 3
        start = len(dst) - d
        for i in range(length):
            dst.append(dst[start + i])
        dst += src[ip:ip + st]
        ip += st
        state = st
    return bytes(dst)
