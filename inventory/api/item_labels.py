def _loc(item):
    return f"{item.location.room}{' – ' + item.location.spot if item.location.spot else ''}"


def get_sticker_lines(item_type, item):
    loc = _loc(item)
    qty = f"Qté : {item.quantity}"
    if item_type == 'miniature':
        return [item.type, item.game.name, item.scale, qty, loc]
    if item_type == 'terrain':
        return [item.type, item.game.name, *([item.theater] if item.theater else []), item.scale, qty, loc]
    if item_type == 'tablecloth':
        return [item.type, item.game.name, item.size, *([item.material] if item.material else []), qty, loc]
    if item_type == 'rulebook':
        return [item.name, item.game.name, *(['Supplément'] if item.supplement else []), qty, loc]
    if item_type == 'board_game':
        return [item.name, *([item.universe] if item.universe else []), qty, loc]
    if item_type == 'book':
        return [item.name, *([item.universe] if item.universe else []), *([item.period] if item.period else []), qty, loc]
    if item_type == 'equipment':
        return [item.type, qty, loc]
    if item_type == 'consumable':
        return [item.type, *([item.unit] if item.unit else []), qty, loc]
    return [str(item.id), loc]


def get_list_row(item_type, item):
    """Returns (name, details, qty, location)."""
    loc = _loc(item)
    if item_type == 'miniature':
        return (item.type, f"{item.game.name} · {item.scale}", item.quantity, loc)
    if item_type == 'terrain':
        details = item.game.name
        if item.theater:
            details += f' · {item.theater}'
        details += f' · {item.scale}'
        return (item.type, details, item.quantity, loc)
    if item_type == 'tablecloth':
        details = item.size
        if item.material:
            details += f' · {item.material}'
        return (item.type, details, item.quantity, loc)
    if item_type == 'rulebook':
        details = item.game.name
        if item.supplement:
            details += ' · Supplément'
        return (item.name, details, item.quantity, loc)
    if item_type == 'board_game':
        return (item.name, item.universe or '', item.quantity, loc)
    if item_type == 'book':
        details = ' · '.join(filter(None, [item.universe, item.period]))
        return (item.name, details, item.quantity, loc)
    if item_type == 'equipment':
        return (item.type, '', item.quantity, loc)
    if item_type == 'consumable':
        return (item.type, item.unit or '', item.quantity, loc)
    return (str(item.id), '', item.quantity, loc)
