# visistruct

Work in progress visualization and debugging tool for [construct](https://github.com/construct/construct).
Because `construct.Container` does not know anything about the `construct.Construct` it was
created from (valid separation of concerns) there is no way get the actual size and offset
of each field in the `construct.Container`. So to get at that data you need both the
construct and a parsed instance of that construct. That's how `visistruct` works.

To see it in action run: `PRINT=1 python -m pytest -rA tests/`

This will print a fancy color coded version using [rich](https://github.com/Textualize/rich) and
a non colored version.

Here's a screenshot of a simple example:
![Simple](/screenshot.png?raw=true)


- Most important thing to work on right now are tests
    - ~~simple~~
    - ~~deeply nested structs~~
    - Strings: ~~CString~~, ~~PascalString~~, ~~PaddedString~~, GreedyString
    - Arrays: ~~structs~~, ~~nested arrays~~, Strings
    - nonbuild: Probe, Tell, StopIf, If, IfThenElse
    - Adapters
- Then I will work to make it beautiful
