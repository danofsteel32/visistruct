"""Source for the `VisiStruct` class.

Would ideally like to remove the rich dependency but still support the
rich console protocol.
"""

import itertools
import operator
import os
import re
from dataclasses import dataclass
from functools import partial, reduce
from typing import Any, Generator, List, Optional, Tuple, Union

import construct as c
from rich.console import Console, ConsoleOptions, RenderResult
from rich.text import Text

DEBUG = int(os.getenv("DEBUG", 0))

NUMBER_TYPES = {
    # unsigned big
    ">B": "Int8ub",
    ">H": "Int16ub",
    ">L": "Int32ub",
    ">Q": "Int32ub",
    # signed big
    ">b": "Int8sb",
    ">h": "Int16sb",
    ">l": "Int32sb",
    ">q": "Int64sb",
    # unsigned big
    "<B": "Int8ul",
    "<H": "Int16ul",
    "<L": "Int32ul",
    "<Q": "Int64ul",
    # signed little
    "<b": "Int8sl",
    "<h": "Int16sl",
    "<l": "Int32sl",
    "<q": "Int64sl",
    # unsigned native
    "=B": "Int8un",
    "=H": "Int16un",
    "=L": "Int32un",
    "=Q": "Int32un",
    # signed  native
    "=b": "Int8sn",
    "=h": "Int16sn",
    "=l": "Int32sn",
    "=q": "Int64sn",
    # floats
    ">e": "Float16b",
    "<e": "Float16l",
    "=e": "Float16n",
    ">f": "Float32b",
    "<f": "Float32l",
    "=f": "Float32n",
    ">d": "Float64b",
    "<d": "Float64l",
    "=d": "Float64n",
}


def tokens(text: str) -> Generator[Tuple[str, str], None, None]:
    """Hacky regex based parser."""
    TOKEN_RX = r"""(?xm)
        (?P<nonbuild>   \+nonbuild        )|
        (?P<docs>       \+docs            )|
        (?P<type>       [^<\s]\w+[^>\s]   )|
        (?P<name>       \s\w+\s           )|
        (?P<open>       [<]               )|
        (?P<close>      [>]               )|
        (               \#.$              )|
        (               \s+               )
    """
    for match in re.finditer(TOKEN_RX, text):
        if match.lastgroup:
            if match.lastgroup == "name":
                yield (match.lastgroup, match[0].strip())
                continue
            yield (match.lastgroup, match[0])


@dataclass
class Field:
    """Holds data about each field in the Construct."""

    name: str
    type: str
    length: int
    value: Any
    parent: str = ""
    nested: int = 0
    offset: int = 0
    color: str = ""

    def _make_string(self) -> str:
        """Created the formatted string used by __str__ and __rich__ methods."""
        indentation = "  " * (self.nested + 1)
        s = (
            f"{indentation}{self.name} {self.type} : {self.value} | "
            f"sz={self.length} offset={self.offset}"
        )
        return s

    def __str__(self) -> str:
        return self._make_string()

    def __rich__(self) -> Text:
        text = Text(self._make_string())
        if self.color:
            text.stylize(f"{self.color}")
        return text


class VisiStruct:
    """Visualize a Construct.

    Given a Construct and either some bytes that can build it or an already
    parsed construct, try to work out the type, size, and offsets of every
    subconstruct.

    Note:
        - set DEBUG=1 to print details for every SubConstruct
    """

    def __init__(
        self,
        format: c.Construct,
        raw: Optional[bytes] = None,
        parsed: Union[c.Container, c.ListContainer, None] = None,
    ):
        self.format = format
        if not raw and not parsed:
            raise Exception("Either raw or parsed required")
        self._raw = raw
        self._parsed = parsed
        self.fields: List[Field] = []

    @property
    def raw(self) -> Optional[bytes]:
        """Result of calling format.build()."""
        if not self._raw:
            if self._parsed:
                self._raw = self.format.build(self._parsed)
        return self._raw

    @property
    def parsed(self) -> Union[c.Container, c.ListContainer]:
        """Result of calling format.parse()."""
        if not self._parsed:
            if self._raw:
                self._parsed = self.format.parse(self.raw)
        return self._parsed

    def create_fields(
        self,
        subcon: Optional[c.Construct] = None,
        namespace: Optional[List[Union[str, int]]] = None,
        nested: int = 0,
    ) -> List[Field]:
        """Called recursively until all subcons parsed."""
        fields = []
        subcons = subcon if subcon else self.format.subcons
        for sub in subcons:
            types = []
            name = ""
            parent = ""
            value = None
            for kind, text in tokens(str(sub)):
                if kind == "type" and text != "Renamed":
                    types.append(text)
                elif kind == "name":
                    name = text
                    if namespace:
                        # call self.parsed.getitem(n) for n in namespace
                        value = reduce(operator.getitem, namespace, self.parsed)
                        # walk backwards through the namespace until hit a string
                        # we do this because the last element in namespace can be
                        # an integer representing the index of an array.
                        for _name in reversed(namespace):
                            if isinstance(_name, str):
                                parent = _name
                                break
                        else:
                            raise ValueError("No strings in namespace?")

                        # transforms to get the actual value not container
                        if isinstance(value, c.Container):
                            value = value[name]
                        if isinstance(value, c.ListContainer):
                            value = [v for v in value]
                    else:
                        value = self.parsed[name]

            if isinstance(value, c.EnumIntegerString):
                value = str(value)

            if DEBUG:
                print()
                print(f"SUB      : {sub}")
                print(f"NAME     : {name}")
                print(f"TYPES    : {types}")
                print(f"VALUE    : {value} {type(value)}")
                print(f"NAMESPACE: {namespace} nested={nested}")

            # by this point we know what (name, value, parent, nested) are so
            # set them here and only worry about setting the length and type below
            p_field = partial(
                Field, name=name, value=value, parent=parent, nested=nested
            )

            if "Const" in types:
                field = p_field(type=" ".join(types), length=sub.sizeof())
                fields.append(field)

            elif "FormatField" in types and "Array" not in types:
                if "Enum" in types:
                    f_type = sub.subcon.subcon.fmtstr
                    f_type = f"Enum({NUMBER_TYPES[f_type]})"
                    length = sub.subcon.subcon.length
                else:
                    f_type = NUMBER_TYPES[sub.subcon.fmtstr]
                    length = sub.subcon.length
                field = p_field(type=f_type, length=length)
                fields.append(field)

            elif "StringEncoded" in types:
                enc = sub.subcon.encoding
                if "NullTerminated" in types:
                    f_type = "CString"
                    length = (
                        len(self.parsed[name].encode(enc))
                        + c.possiblestringencodings[enc]
                    )
                elif "FixedSized" in types:
                    f_type = "PaddedString"
                    length = sub.subcon.sizeof()
                elif "Prefixed" in types:
                    f_type = "PascalString"
                    length = len(self.parsed[name].encode(enc)) + 1  # always 1?
                field = p_field(type=f_type, length=length)
                fields.append(field)

            elif types == ["Struct"]:
                if not namespace:
                    namespace = [name]
                else:
                    namespace.append(name)
                nested += 1
                fields.extend(self.create_fields(sub.subcon.subcons, namespace, nested))
                # reset namespace and nest level
                namespace = None
                nested = 0

            elif "Array" in types and "FormatField" not in types:
                _len = self.parsed[sub.subcon.count._Path__field]
                namespace = [name]
                nested += 1
                for idx in range(_len):
                    _namespace = namespace + [idx]
                    sub_fields = self.create_fields(
                        sub.subcon.subcon.subcons, namespace=_namespace, nested=nested
                    )
                    fields.extend(sub_fields)
                # reset namespace and nest level
                namespace = None
                nested = 0

            # array of simple types
            elif "Array" in types and "FormatField" in types:
                f_type = f"Array[{NUMBER_TYPES[sub.subcon.subcon.fmtstr]}]"
                length = sub.count * sub.subcon.subcon.length
                field = p_field(type=f_type, length=length)
                fields.append(field)

            else:
                print("UNKNOWN?")
                print(sub)
                print(f" name: {name}")
                print(f" types: {types}")
                print(f" value: {value}")

        # Set offsets and colors
        color_wheel = itertools.cycle(
            ["cyan", "green", "blue", "yellow", "purple", "red"]
        )
        offset = 0
        for f in fields:
            offset += f.length
            f.offset = offset
            f.color = next(color_wheel)
        self.fields = fields
        return fields

    def chunk_bytes(self, chunk_size: int) -> list:
        if not self.raw:
            raise Exception("raw is None")

        fields = iter(self.fields)
        field = next(fields)

        as_hex = self.raw.hex()
        num_rows = len(self.raw) // chunk_size

        # add an extra row if not divide cleanly by chunk_size
        # pad with .. for every extra byte in extra row
        padded = len(as_hex)
        if len(self.raw) % chunk_size:
            num_rows += 1
            pad = num_rows * chunk_size - len(self.raw)
            as_hex += ".." * (pad)
            padded = len(as_hex)
            padded -= pad * 2

        out = []
        n = 0
        while n < (len(as_hex) - 1):
            if n // 2 > field.offset - 1 and n > 0:
                try:
                    field = next(fields)
                except StopIteration:
                    pass
            text = Text(f" {as_hex[n : n + 2]} ")
            if n < padded:
                text.stylize(f"{field.color}")
            out.append(text)
            # print(n, text, padded)
            n += 2
        return [out[i : i + chunk_size] for i in range(0, len(out), chunk_size)]

    def __str__(self) -> str:
        fields = self.fields if self.fields else self.create_fields()
        parent = ""
        text = "Container:\n"
        for field in fields:
            indentation = "  " * field.nested
            if field.parent and field.parent != parent:
                text += f"{indentation}{field.parent}:\n"
                parent = field.parent
            text += f"{field}\n"
        # return text.strip()
        return text

    def __rich_console__(self, console: Console, opts: ConsoleOptions) -> RenderResult:
        fields = self.fields if self.fields else self.create_fields()

        width, _ = console.size
        width = width // 8

        parent = ""
        yield Text("Container:", style="bold")
        for field in fields:
            indentation = "  " * field.nested
            if field.parent and field.parent != parent:
                yield Text(f"{indentation}{field.parent}:", style="bold")
                parent = field.parent
            yield field
        for chunk in self.chunk_bytes(width):
            text = Text()
            [text.append(c) for c in chunk]
            yield text
