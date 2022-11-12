"""The main `VisiStruct` class.

Takes a Construct and either a built bytes array or a parsed Container.
"""

import itertools
import operator
import os
import re
from dataclasses import dataclass
from functools import partial, reduce
from typing import Any, Generator, List, Optional, Tuple, Union

import construct as c
from rich.console import Console
from rich.text import Text

console = Console()

NO_COLOR = os.getenv("NO_COLOR")

FORMAT_CHAR = {
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
    """Used instead of a dict, its just a container."""

    name: str
    type: str
    length: int
    value: Any
    parent: str = ""
    nested: int = 0
    offset: int = 0  # has to be set later
    color: str = ""

    def __rich__(self) -> Text:
        indentation = "  " * self.nested + "  "
        s = f"{indentation}{self.name}: {self.value} (type={self.type} sz={self.length} offset={self.offset})"  # noqa: E501
        text = Text(s)
        if self.color:
            text.style = f"bold {self.color}"
        return text


class VisiStruct:
    """Visualize a Construct.

    Given a Construct and either some bytes that can build it or an already
    parsed construct, try to work out the type, size, and offsets of every
    subconstruct.

    Notes:
        - set NO_COLOR=1 to disable colored output
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
        self.fields: List[Field]

    @property
    def raw(self) -> Optional[bytes]:
        # TODO figure out when and where to raise exc if no parsed and no raw
        if not self._raw:
            if self._parsed:
                self._raw = self.format.build(self._parsed)
        return self._raw

    @property
    def parsed(self) -> Union[c.Container, c.ListContainer]:
        if not self._parsed:
            if self._raw:
                self._parsed = self.format.parse(self.raw)
        return self._parsed

    def create_fields(
        self,
        subcon: Optional[c.Construct] = None,
        namespace: Optional[List] = None,
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
                        # getitem for n in namespace
                        value = reduce(operator.getitem, namespace, self.parsed)
                        if isinstance(value, c.Container):
                            value = value[name]
                        if isinstance(value, c.ListContainer):
                            value = [v for v in value]
                        parent = namespace[-1] if not isinstance(namespace[-1], int) else namespace[0]
                    else:
                        value = self.parsed[name]
            
            if isinstance(value, c.EnumIntegerString):
                value = str(value)

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
                    f_type = "Enum " + FORMAT_CHAR[f_type]
                    length = sub.subcon.subcon.length
                else:
                    f_type = FORMAT_CHAR[sub.subcon.fmtstr]
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
                # TODO figure out how to represent that this is nested
                fields.extend(self.create_fields(sub.subcon.subcons, namespace, nested))
                namespace = None
                nested = 0

            elif "Array" in types and "FormatField" not in types:
                _len = self.parsed[sub.subcon.count._Path__field]
                namespace = [name]
                nested += 1
                for idx in range(_len):
                    _namespace = namespace + [idx]
                    fields.extend(self.create_fields(sub.subcon.subcon.subcons, namespace=_namespace, nested=nested))
                namespace = None
                nested = 0

            elif "Array" in types and "FormatField" in types:
                # console.print()
                # console.print(f"SUB: {sub}")
                # console.print("NAME", name)
                # console.print(f"NAMESPACE: {namespace} {nested}")
                # namespace.append(name)

                f_type = f"Array[{FORMAT_CHAR[sub.subcon.subcon.fmtstr]}]"
                length = sub.count * sub.subcon.subcon.length
                field = p_field(type=f_type, length=length)
                fields.append(field)

            else:
                console.print(sub)
                console.print(f" name: {name}")
                console.print(f" types: {types}")
                console.print(f" value: {value}")

        # Set offsets and colors
        color_wheel = itertools.cycle(
            ["cyan", "green", "blue", "yellow", "purple", "red"]
        )
        offset = 0
        for f in fields:
            offset += f.length
            f.offset = offset
            if not NO_COLOR:
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
            if n < padded and not NO_COLOR:
                text.stylize(f"bold {field.color}")
            out.append(text)
            # print(n, text, padded)
            n += 2
        return [out[i : i + chunk_size] for i in range(0, len(out), chunk_size)]

    def print(self, width: int = 8) -> None:
        # TODO: create a rich.Tree
        # width sets how many bytes to print per line
        fields = self.create_fields()
        parent = ""
        console.print("Container:")
        for field in fields:
            indentation = "  " * field.nested
            if field.parent and field.parent != parent:
                console.print(f"{indentation}{field.parent}:")
                parent = field.parent
            console.print(field)
        if NO_COLOR:
            return
        console.print()
        for chunk in self.chunk_bytes(width):
            text = Text()
            [text.append(c) for c in chunk]
            console.print(text)
