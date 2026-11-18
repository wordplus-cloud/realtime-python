"""Every python block of the README and the docs compiles, and what it takes from the package is there.

Each block is compiled as py_compile compiles a file, a module of its own (an async route's `await` at its top allowed,
and a block that returns outside a function compiled as one's body). Then, read from its tree:

- each name it imports from wordplus_realtime and its modules, and each module a string names
  (`include("wordplus_realtime.django.routes")`, `INSTALLED_APPS`), is there;
- each call of a chain from the server's `realtime` (or the class, `Realtime.from_environment()`), and of a function
  it imported from the package, binds to the parameters of what it calls, keywords by their names, and is followed
  through what each method answers (`realtime.call(name).permit(user, publish=True)`).

The app's own names, and what a block keeps in a variable of its own, are the app's, as the prose says. A block that is a
part of something larger says so after its language, ```python fragment, and is not compiled.
"""

import ast
import importlib
import importlib.util
import inspect
import pathlib
import re
import textwrap
import typing

from wordplus_realtime import Realtime

ROOT = pathlib.Path(__file__).parent.parent
FILES = [ROOT / "README.md", *sorted((ROOT / "docs").glob("*.md")), *sorted((ROOT / "docs").glob("*/*.md"))]
PACKAGE = "wordplus_realtime"


def blocks():
    """Each python block: its page, the line its code starts on, its code, and whether it is marked a fragment."""
    found = []
    for file in FILES:
        lines = file.read_text().split("\n")
        i = 0
        while i < len(lines):
            opened = re.match(r"^(\s*)```(\w*)(.*)$", lines[i])
            if not opened:
                i += 1
                continue
            end = i + 1
            while end < len(lines) and lines[end].strip() != "```":
                end += 1
            if opened[2] == "python":
                indent = opened[1]
                code = "\n".join(line[len(indent):] if line.startswith(indent) else line.lstrip() for line in lines[i + 1:end])
                fragment = re.search(r"(^|\s)fragment(\s|$)", opened[3]) is not None
                found.append({"page": str(file.relative_to(ROOT)), "line": i + 2, "code": textwrap.dedent(code), "fragment": fragment})
            i = end + 1
    return found


def compiled(block):
    """The block's tree and how many lines its code moved down (1 when it is a function's body), or a SyntaxError."""
    code = block["code"]
    flags = ast.PyCF_ALLOW_TOP_LEVEL_AWAIT
    try:
        compile(code, block["page"], "exec", flags=flags, dont_inherit=True)
        return ast.parse(code), 0
    except SyntaxError as error:
        if "outside function" not in str(error.msg):
            return error, 0
    body = "async def body():\n" + textwrap.indent(code, "    ")
    try:
        compile(body, block["page"], "exec", flags=flags, dont_inherit=True)
    except SyntaxError as error:
        error.lineno = (error.lineno or 1) - 1
        return error, 0
    return ast.parse(body), 1


def test_every_block_compiles():
    every = blocks()
    assert len(every) > 90
    failed = []
    for block in every:
        if block["fragment"]:
            continue
        tree, _ = compiled(block)
        if isinstance(tree, SyntaxError):
            failed.append(f"{block['page']}:{block['line'] + (tree.lineno or 1) - 1} {tree.msg}")
    assert failed == []


def test_few_blocks_are_fragments():
    # The parts of something larger, not compiled. Another one is a choice, not a way around these tests.
    assert [f"{b['page']}:{b['line']}" for b in blocks() if b["fragment"]] == []


def _classes(hint):
    """The package's classes a return annotation names, a union's included."""
    options = typing.get_args(hint) if typing.get_origin(hint) is typing.Union else (hint,)
    return [one for one in options if inspect.isclass(one) and one.__module__.startswith(PACKAGE)]


def _bind(target, call, bound_to_class):
    """Whether a call's arguments fit what it calls: a TypeError's words when they don't, None when they do or can't be told."""
    if any(isinstance(a, ast.Starred) for a in call.args) or any(k.arg is None for k in call.keywords):
        return None
    try:
        signature = inspect.signature(target)
    except (TypeError, ValueError):
        return None
    args = [None] * len(call.args)
    try:
        signature.bind(*([None] if bound_to_class else []), *args, **{k.arg: None for k in call.keywords})
    except TypeError as error:
        return str(error)
    return None


class _Chains(ast.NodeVisitor):
    """Follows each chain from `realtime` or `Realtime`, and the calls of what the block imported from the package."""

    def __init__(self, imported):
        self.imported = imported
        self.failed = []
        self.calls = 0
        self.known = {}

    def classes(self, node):
        """The package's classes a node is, when the chain tells; [] when it doesn't."""
        if id(node) in self.known:
            return self.known[id(node)]
        found = []
        if isinstance(node, ast.Name) and node.id in ("realtime", "Realtime"):
            found = [Realtime]
        elif isinstance(node, ast.Attribute):
            # A property (realtime.keys), read on what is before it.
            for cls in self.classes(node.value):
                static = inspect.getattr_static(cls, node.attr, None)
                if isinstance(static, property) and static.fget:
                    found += _classes(typing.get_type_hints(static.fget).get("return"))
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            found = self.method(node)
        self.known[id(node)] = found
        return found

    def method(self, call):
        name = call.func.attr
        owners = self.classes(call.func.value)
        if not owners:
            return []
        self.calls += 1
        methods = [(cls, inspect.getattr_static(cls, name, None)) for cls in owners]
        methods = [(cls, getattr(cls, name)) for cls, static in methods if static is not None and callable(getattr(cls, name)) and not name.startswith("_")]
        if not methods:
            self.failed.append((call, "no " + "|".join(cls.__name__ for cls in owners) + "." + name + "()"))
            return []
        fits = []
        why = None
        for cls, target in methods:
            static = inspect.getattr_static(cls, name)
            why = _bind(target, call, not isinstance(static, (staticmethod, classmethod)))
            if why is None:
                fits.append(target)
        if not fits:
            self.failed.append((call, f"{name}(): {why}"))
            return []
        return [cls for target in fits for cls in _classes(typing.get_type_hints(target).get("return"))]

    def visit_Call(self, node):
        if isinstance(node.func, ast.Attribute):
            self.classes(node)
        elif isinstance(node.func, ast.Name) and callable(self.imported.get(node.func.id)):
            self.calls += 1
            why = _bind(self.imported[node.func.id], node, False)
            if why:
                self.failed.append((node, f"{node.func.id}(): {why}"))
        self.generic_visit(node)


def _made_when_asked(module, name):
    """A name the module makes when first asked (wordplus_realtime.django's `realtime`, from Django's settings)."""
    try:
        getattr(module, name)
    except AttributeError:
        return False
    except Exception:
        return True
    return True


def test_what_the_blocks_take_from_the_package_is_there():
    failed = []
    calls = 0
    for block in blocks():
        if block["fragment"]:
            continue
        tree, moved = compiled(block)
        if isinstance(tree, SyntaxError):
            continue
        at = lambda node: f"{block['page']}:{block['line'] + node.lineno - 1 - moved}"
        imported = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and (node.module or "").split(".")[0] == PACKAGE:
                if importlib.util.find_spec(node.module) is None:
                    failed.append(f"{at(node)} no {node.module}")
                    continue
                module = importlib.import_module(node.module)
                for alias in node.names:
                    if alias.name in vars(module):
                        imported[alias.asname or alias.name] = vars(module)[alias.name]
                    elif _made_when_asked(module, alias.name):
                        pass
                    elif importlib.util.find_spec(f"{node.module}.{alias.name}") is None:
                        failed.append(f"{at(node)} no {node.module}.{alias.name}")
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.split(".")[0] == PACKAGE and importlib.util.find_spec(alias.name) is None:
                        failed.append(f"{at(node)} no {alias.name}")
            elif isinstance(node, ast.Constant) and isinstance(node.value, str) and re.fullmatch(rf"{PACKAGE}(\.\w+)+", node.value):
                if importlib.util.find_spec(node.value) is None:
                    failed.append(f"{at(node)} no {node.value}")
        chains = _Chains(imported)
        chains.visit(tree)
        calls += chains.calls
        failed += [f"{at(node)} {why}" for node, why in chains.failed]
    assert calls > 100
    assert failed == []
