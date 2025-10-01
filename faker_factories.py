import os, random
from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, Callable, Optional, Set, Tuple
from faker import Faker

_LOCALE = os.getenv("FAKER_LOCALE", "en_US")
_SEED = int(os.getenv("SEED","42"))
faker = Faker(_LOCALE)
faker.seed_instance(_SEED)
random.seed(_SEED)

# Registry to ensure uniqueness when requested
_UNIQUE_REG: Dict[Tuple[str,str], Set[Any]] = {}

def reset_uniques():
    """Clear uniqueness registry and Faker's internal unique cache."""
    _UNIQUE_REG.clear()
    try:
        faker.unique.clear()
    except Exception:
        pass

def coerce_decimal(min_v=0, max_v=1000, places=2):
    scale = 10**places
    return Decimal(random.randint(int(min_v*scale), int(max_v*scale))) / scale

TYPE_MAP: Dict[str, Callable[[], Any]] = {
    "varchar": lambda: faker.text(max_nb_chars=20).strip(),
    "char":    lambda: faker.pystr(min_chars=1, max_chars=8),
    "text":    lambda: faker.paragraph(nb_sentences=3),
    "int":     lambda: random.randint(0, 10000),
    "bigint":  lambda: random.randint(0, 10**9),
    "decimal": lambda: coerce_decimal(0, 10000, 2),
    "float":   lambda: random.random()*1000,
    "double":  lambda: random.random()*1000,
    "date":    lambda: faker.date_between(start_date="-3y", end_date="+30d"),
    "datetime":lambda: faker.date_time_between(start_date="-3y", end_date="now"),
    "timestamp":lambda: faker.date_time_between(start_date="-3y", end_date="now"),
    "time":    lambda: faker.time_object(),
    "bool":    lambda: random.choice([0,1]),
}

def _ensure_unique(table: Optional[str], column: str, value_fn, max_tries=20):
    """
    Try to generate a unique value for (table, column).
    Falls back to appending a counter suffix if collisions persist.
    """
    key = (table or "_global", column)
    seen = _UNIQUE_REG.setdefault(key, set())
    for _ in range(max_tries):
        val = value_fn()
        if val not in seen:
            seen.add(val)
            return val
    # fallback: force uniqueness by suffix
    base = value_fn()
    suffix = 1
    candidate = f"{base}-{suffix}"
    while candidate in seen:
        suffix += 1
        candidate = f"{base}-{suffix}"
    seen.add(candidate)
    return candidate

def value_for(column: str, data_type: str, *, unique: bool=False, table: Optional[str]=None):
    c, dt = column.lower(), data_type.lower()

    # Semantic generators
    if c in ("first_name","firstname","fname","given_name"):
        return faker.first_name()
    if c in ("last_name","lastname","lname","surname","family_name"):
        return faker.last_name()
    if c in ("full_name","name","customer_name","contact_name"):
        return faker.name()
    if "email" in c:
        gen = (lambda: faker.unique.email()) if unique else (lambda: faker.email())
        return _ensure_unique(table, c, gen) if unique else gen()
    if c in ("username","user_name","login","account"):
        gen = (lambda: faker.unique.user_name()) if unique else (lambda: faker.user_name())
        return _ensure_unique(table, c, gen) if unique else gen()
    if c in ("sku","product_code","item_code","code"):
        def make_sku():
            return f"{faker.bothify(text='???-########')}".upper()
        return _ensure_unique(table, c, make_sku) if unique else make_sku()
    if "phone" in c or c in ("msisdn",):
        return faker.phone_number()
    if c in ("city","town"):
        return faker.city()
    if c in ("country",):
        return faker.country()
    if c in ("address","street","street_address","addr_line1"):
        return faker.street_address()
    if c in ("postal_code","zipcode","zip"):
        return faker.postcode()
    if c in ("url","website","homepage"):
        return faker.url()
    if c in ("password","passwd","hashed_password"):
        return faker.password(length=12)
    if c in ("created_at","createdon","created_date","inserted_at"):
        return faker.date_time_between(start_date="-3y", end_date="-1y")
    if c in ("updated_at","modified_at","updatedon","modifiedon","last_modified"):
        return faker.date_time_between(start_date="-12m", end_date="now")

    # Type-driven fallback
    for k,v in TYPE_MAP.items():
        if dt.startswith(k):
            return _ensure_unique(table, c, v) if unique else v()

    # Generic small text
    gen = lambda: faker.text(max_nb_chars=16).strip()
    return _ensure_unique(table, c, gen) if unique else gen()

def fix_enum(_, enum_options):
    """Choose a valid ENUM value from the column's options."""
    return random.choice(enum_options)
