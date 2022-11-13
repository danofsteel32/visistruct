"""Tests for the `VisiStruct` class.

Move fixtures to an example_structs.py and then can use them multiple ways
"""
import os
import random
from functools import partial
from typing import Tuple

import construct as c
import pytest
from rich.console import Console

from visistruct import VisiStruct

PRINT = int(os.getenv("PRINT", 0))
console = Console(color_system="256")


@pytest.fixture
def all_string_types_struct() -> Tuple[c.Struct, bytes]:
    """Generate a struct containing all string types and all encodings."""
    encodings = {"ascii": 1, "u16": 2, "u32": 4, "u8": 1}
    default_sz = 40
    string_types = [
        (c.CString, "cstring"),
        (partial(c.PaddedString, default_sz), "paddedstring"),
        (partial(c.PascalString, c.VarInt), "pascalstring"),
    ]
    mapping = {}
    for s_type, name in string_types:
        for enc in encodings:
            mapping[f"{name}_{enc}"] = s_type(enc)
    format = c.Struct(**mapping)
    args = {k: "=QWERTY=" for k in mapping}
    return format, format.build(args)


@pytest.fixture
def simple_struct() -> Tuple[c.Struct, bytes]:
    """Simple struct with a few types and a single nested struct."""
    format = c.Struct(
        "my_header" / c.Const(b"FAKE"),
        "my_int" / c.Int32ul,
        "my_string" / c.CString("ascii"),
        "my_enum" / c.Enum(c.Int8ul, ONE=1, TWO=2, THREE=3),
        # nested inner struct
        "my_inner"
        / c.Struct(
            "my_id" / c.Int16ul,
            "my_value" / c.Enum(c.Int32ul, HOT=1, COLD=2, JUST_RIGHT=3),
        ),
    )
    args = dict(
        my_int=17,
        my_string="helloworld",
        my_enum="ONE",
        my_inner=dict(my_id=3, my_value="HOT"),
    )
    return format, format.build(args)


@pytest.fixture
def heavily_nested() -> Tuple[c.Struct, bytes]:
    format = c.Struct(
        "top_value" / c.Int32sl,
        "one" / c.Struct(
            "one_value" / c.Int32sl,
            "two" / c.Struct(
                "two_value" / c.Int32sl,
                "three" / c.Struct(
                    "three_value" / c.Int32sl,
                    "bottom" / c.Int32sl
                )
            )
        )
    )
    args = dict(
        top_value=0,
        one=dict(
            one_value=1,
            two=dict(
                two_value=2,
                three=dict(
                    three_value=3,
                    bottom=32
                )
            )
        )
    )
    return format, format.build(args)


@pytest.fixture
def array_struct():
    format = c.Struct(
        "sz_custom_array" / c.Int32sb,
        "custom_array"
        / c.Array(
            c.this.sz_custom_array,
            c.Struct(
                "a_flag" / c.Enum(c.Int8sb, ONE=1, TWO=2, THREE=3, FOUR=4),
                "nested_custom_array" / c.Float32l[3],
            ),
        ),
    )
    custom_array = []
    for n in range(4):
        custom_array.append(
            dict(
                a_flag=n + 1,
                nested_custom_array=[random.uniform(-10, 10) for _ in range(3)]
            )
        )
    args = dict(
        sz_custom_array=4,
        custom_array=custom_array
    )
    return format, format.build(args)


def test_array(array_struct):
    format, raw = array_struct
    v = VisiStruct(format, raw)
    if PRINT:
        console.print(v)
        print()
        print(v)


def test_heavily_nested(heavily_nested):
    format, raw = heavily_nested
    v = VisiStruct(format, raw)
    v.create_fields()
    # TODO check correct parent and level of nested
    # for field in v.fields:
    #     print(field)
    assert len(v.fields) == 5
    if PRINT:
        console.print(v)
        print()
        print(v)


def test_simple(simple_struct):
    format, raw = simple_struct
    v = VisiStruct(format, raw)
    v.create_fields()
    # for field in v.fields:
    #     print(field)
    assert len(v.fields) == 6
    if PRINT:
        console.print(v)
        print()
        print(v)


def test_strings(all_string_types_struct):
    format, raw = all_string_types_struct
    decodings = {"u32": "utf-32", "u16": "utf-16", "u8": "utf-8", "ascii": "ascii"}
    v = VisiStruct(format, raw)

    offset = 0
    for field in v.create_fields():
        dec = decodings[field.name.split("_")[-1]]
        b = raw[offset : offset + field.length]
        offset = field.offset
        # print(field)
        if field.type == "PascalString":
            b = b[1:]  # length prefixed
        to_string = b.decode(dec)  # valuable to know actually decodes
        # remove trailing null bytes so we can compare to expected value
        to_string = to_string.replace("\x00", "")

        assert to_string == field.value
        # print(len(b), b, " | ", to_string)
        # print(field.name, field.value, to_string, len(to_string))
    assert len(raw) == offset
    assert len(v.fields) == 12  # 3 string types * 4 encodings
    if PRINT:
        console.print(v)
        print()
        print(v)
