import base64
import os
import struct
from cryptography.hazmat.primitives.asymmetric import x25519
from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives.hashes import SHA256
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives import hmac


CHARSET = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"


def bech32_decode(bech):
    if (any(ord(x) < 33 or ord(x) > 126 for x in bech)) or (bech.lower() != bech and bech.upper() != bech):
        return None, None
    bech = bech.lower()
    pos = bech.rfind("1")
    if pos < 1 or pos + 7 > len(bech) or len(bech) > 90:
        return None, None
    hrp = bech[:pos]
    data = []
    for c in bech[pos + 1 :]:
        if c not in CHARSET:
            return None, None
        data.append(CHARSET.index(c))

    
    acc = 0
    bits = 0
    ret = bytearray()
    for value in data[:-6]:  
        acc = (acc << 5) | value
        bits += 5
        while bits >= 8:
            bits -= 8
            ret.append((acc >> bits) & 0xFF)
    return hrp, bytes(ret)



def b64_encode(data: bytes) -> str:
    return base64.b64encode(data).decode("utf-8").rstrip("=")


def b64_decode(data: str) -> bytes:
    missing_padding = len(data) % 4
    if missing_padding:
        data += "=" * (4 - missing_padding)
    return base64.b64decode(data)



def encrypt_age(recipient_str: str, payload: bytes) -> bytes:
    
    hrp, pub_bytes = bech32_decode(recipient_str)
    if hrp != "age" or len(pub_bytes) != 32:
        raise ValueError("Invalid age public key format.")
    recipient_key = x25519.X25519PublicKey.from_public_bytes(pub_bytes)

    
    ephemeral_share = x25519.X25519PrivateKey.generate()
    ephemeral_pub_bytes = ephemeral_share.public_key().public_bytes_raw()
    file_key = os.urandom(16)

    
    shared_secret = ephemeral_share.exchange(recipient_key)

    
    salt = ephemeral_pub_bytes + pub_bytes
    hkdf = HKDF(
        algorithm=SHA256(),
        length=32,
        salt=salt,
        info=b"age-encryption.org/v1/X25519",
    )
    wrap_key = hkdf.derive(shared_secret)

    
    cipher = ChaCha20Poly1305(wrap_key)
    encrypted_file_key = cipher.encrypt(b"\x00" * 12, file_key, b"")

    
    ephemeral_b64 = b64_encode(ephemeral_pub_bytes)
    enc_file_key_b64 = b64_encode(encrypted_file_key)

    header = "age-encryption.org/v1\n"
    header += f"-> X25519 {ephemeral_b64}\n{enc_file_key_b64}\n"
    header += "---"

    
    hkdf_mac = HKDF(
        algorithm=SHA256(),
        length=32,
        salt=None,
        info=b"age-encryption.org/v1/mac",
    )
    hmac_key = hkdf_mac.derive(file_key)

    h = hmac.HMAC(hmac_key, hashes.SHA256())
    h.update(header.encode("utf-8"))
    header_mac = h.finalize()

    
    full_header = header.encode("utf-8") + b" " + b64_encode(header_mac).encode("utf-8") + b"\n"

    
    stream_nonce = os.urandom(16)
    hkdf_payload = HKDF(
        algorithm=SHA256(),
        length=32,
        salt=stream_nonce,
        info=b"age-encryption.org/v1/chacha20-poly1305",
    )
    payload_key = hkdf_payload.derive(file_key)

    
    chunk_size = 64 * 1024
    encrypted_payload = bytearray()

    
    nonce_structure = struct.pack(">Q", 0) + b"\x01"  
    cipher_payload = ChaCha20Poly1305(payload_key)
    encrypted_chunk = cipher_payload.encrypt(nonce_structure, payload, b"")
    encrypted_payload.extend(encrypted_chunk)

    return bytes(full_header + stream_nonce + encrypted_payload)


def decrypt_age(identity_priv_hex: str, encrypted_bytes: bytes) -> bytes:
    
    lines = encrypted_bytes.split(b"\n")
    if lines[0] != b"age-encryption.org/v1":
        raise ValueError("Unsupported or invalid format protocol.")

    
    header_end_idx = 0
    for idx, line in enumerate(lines):
        if line.startswith(b"---"):
            header_end_idx = idx
            break

    
    header_body = b"\n".join(lines[:header_end_idx]) + b"\n---"
    mac_line = lines[header_end_idx].split(b" ")
    provided_mac = b64_decode(mac_line[1].decode("utf-8"))

    
    stanza_info = lines[1].decode("utf-8").split(" ")
    ephemeral_pub_bytes = b64_decode(stanza_info[2])
    encrypted_file_key = b64_decode(lines[2].decode("utf-8"))

    
    priv_bytes = bytes.fromhex(identity_priv_hex)
    identity_key = x25519.X25519PrivateKey.from_private_bytes(priv_bytes)
    pub_bytes = identity_key.public_key().public_bytes_raw()

    
    ephemeral_pub_obj = x25519.X25519PublicKey.from_public_bytes(ephemeral_pub_bytes)
    shared_secret = identity_key.exchange(ephemeral_pub_obj)

    salt = ephemeral_pub_bytes + pub_bytes
    hkdf = HKDF(
        algorithm=SHA256(),
        length=32,
        salt=salt,
        info=b"age-encryption.org/v1/X25519",
    )
    wrap_key = hkdf.derive(shared_secret)

    
    cipher = ChaCha20Poly1305(wrap_key)
    file_key = cipher.decrypt(b"\x00" * 12, encrypted_file_key, b"")

    
    hkdf_mac = HKDF(
        algorithm=SHA256(),
        length=32,
        salt=None,
        info=b"age-encryption.org/v1/mac",
    )
    hmac_key = hkdf_mac.derive(file_key)
    h = hmac.HMAC(hmac_key, hashes.SHA256())
    h.update(header_body)
    h.verify(provided_mac)

    
    
    payload_start = len(header_body) + 1 + len(mac_line[1]) + 2
    stream_nonce = encrypted_bytes[payload_start : payload_start + 16]
    ciphertext_body = encrypted_bytes[payload_start + 16 :]

    
    hkdf_payload = HKDF(
        algorithm=SHA256(),
        length=32,
        salt=stream_nonce,
        info=b"age-encryption.org/v1/chacha20-poly1305",
    )
    payload_key = hkdf_payload.derive(file_key)

    
    nonce_structure = struct.pack(">Q", 0) + b"\x01"
    cipher_payload = ChaCha20Poly1305(payload_key)
    decrypted_payload = cipher_payload.decrypt(nonce_structure, ciphertext_body, b"")

    return decrypted_payload



if __name__ == "__main__":
    
    
    priv_hex = "2b41315b8109bfda10174c67db1a1343714b62f6b8b15d03a116bc92d0ff124d"
    pub_bech32 = "age1ant79mvdh6scg398szwskr9w76vdyw33y49p68t603pqp3sk6u8sntk69w"

    secret_message = b"This is a port payload verifying the age specification works smoothly!"
    print(f"Original Text: {secret_message.decode()}\n")

    
    encrypted_packet = encrypt_age(pub_bech32, secret_message)
    print("--- ENCRYPTED FILE OUTPUT STREAM ---")
    print(encrypted_packet[:250].decode("utf-8", errors="replace") + "...\n")

    
    recovered_message = decrypt_age(priv_hex, encrypted_packet)
    print(f"Decrypted Result Match: {recovered_message == secret_message}")
    print(f"Recovered Content: {recovered_message.decode()}")
