def safe_cell(v):
    s='' if v is None else str(v)
    return "'"+s if s[:1] in ('=','+','-','@') else s
