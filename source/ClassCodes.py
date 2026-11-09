# Short display codes for coral class names (display only: the class name stored in the
# project and in the dictionary is never changed).
#
#   Genus_species        -> first letter of the genus + first three of the species  (Acropora_cervicornis = ACER)
#   Genus_sp.            -> first four letters of the genus                          (Agaricia_sp. = AGAR)
#   Names not in either form (Empty, "Modern A", ...) are shown as they are.

# names that do not follow the rules above
CODE_OVERRIDES = {
    "Digitate_Porites": "PDIG",
}


def class_code(name):

    if name in CODE_OVERRIDES:
        return CODE_OVERRIDES[name]

    parts = name.split("_")
    if len(parts) != 2 or not parts[0] or not parts[1]:
        return name

    genus, species = parts
    if species.lower().rstrip(".") in ("sp", "spp"):
        return genus[:4].upper()

    return (genus[0] + species[:3]).upper()


def class_codes(names):
    """
    Maps every name to its code. If two different names would get the same code, both
    keep their full name so that two classes are never shown as the same thing.
    """

    codes = {name: class_code(name) for name in names}

    seen = {}
    for name, code in codes.items():
        seen.setdefault(code, []).append(name)

    for code, owners in seen.items():
        if len(owners) > 1:
            for name in owners:
                codes[name] = name

    return codes
