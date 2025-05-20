def convert_size_unit(size: str) -> int:
    """Convert the size string to bytes."""

    units = ["B", "KB", "MB", "GB"]
    val, unit = size.split(" ")
    val = float(val.replace(",", "."))

    if unit not in units:
        raise ValueError(f"Invalid size unit: {unit}")
    return int(val * (1024 ** units.index(unit)))