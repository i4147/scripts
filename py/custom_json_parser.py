def parse_with_warning(file_path):
    duplicates = []

    def handle_pairs(pairs):
        seen = set()
        for key, value in pairs:
            if key in seen:
                duplicates.append(key)
            seen.add(key)
        return dict(pairs)

    data = json.loads(content, object_pairs_hook=handle_pairs)
    if duplicates:
        print(f"Warning: Duplicate keys found: {set(duplicates)}")
    return data
