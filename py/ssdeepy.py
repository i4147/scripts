import hashlib


def calculate_hash(data, hash_function="sha256") -> str:
    hasher = hashlib.new(hash_function)
    hasher.update(data.encode("utf-8"))
    return hasher.hexdigest()


def compare_hashes(hash1: str, hash2: str) -> int:
    if not hash1 or not hash2:
        return 0
    length = min(len(hash1), len(hash2))
    match_count = 0
    for i in range(length):
        if hash1[i] == hash2[i]:
            match_count += 1
    return int((match_count / length) * 100)


def ssdeep_simplified(data1: str, data2: str) -> int:
    hash1 = calculate_hash(data1)
    hash2 = calculate_hash(data2)
    score = compare_hashes(hash1, hash2)
    return score


if __name__ == "__main__":
    data1 = "This is a test string."
    data2 = "This is a test string!"
    data3 = "Completely different string."
    score12 = ssdeep_simplified(data1, data2)
    score13 = ssdeep_simplified(data1, data3)
    print(f"SSDEEP-like score between '{data1}' and '{data2}': {score12}")
    print(f"SSDEEP-like score between '{data1}' and '{data3}': {score13}")
