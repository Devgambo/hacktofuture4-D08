# B32: converted from a print-based scratchpad to proper assertions
# Run with: python -m pytest test_parser.py -v

from server.rsi.parser import parse_file

PY_CODE = '''\
import os
from datetime import datetime

class MyService:
    def __init__(self):
        pass

def process_data():
    pass
'''

JS_CODE = '''\
import React from 'react';
export class App extends React.Component {}
export const doThing = () => {}
'''


def test_python_role_tag():
    res = parse_file(PY_CODE, "src/service.py", "mocksha")
    assert res["file"]["role_tag"] == "source"


def test_python_symbols():
    res = parse_file(PY_CODE, "src/service.py", "mocksha")
    names = [s["symbol_name"] for s in res["symbols"]]
    assert "MyService" in names
    assert "process_data" in names
    # Parser indexes top-level classes/functions only (^class/^def anchored at
    # column 0); indented methods like __init__ are intentionally not indexed.
    assert "__init__" not in names


def test_python_imports():
    res = parse_file(PY_CODE, "src/service.py", "mocksha")
    paths = [i["imported_path"] for i in res["imports"]]
    assert "os" in paths
    assert "datetime" in paths


def test_python_line_count():
    res = parse_file(PY_CODE, "src/service.py", "mocksha")
    # line_count must be > 1 (was always 1 before B1 fix)
    assert res["file"]["line_count"] > 1


def test_python_symbol_start_line():
    res = parse_file(PY_CODE, "src/service.py", "mocksha")
    class_sym = next(s for s in res["symbols"] if s["symbol_name"] == "MyService")
    # MyService is defined after the two import lines, so start_line > 1
    assert class_sym["start_line"] > 1


def test_js_symbols():
    res = parse_file(JS_CODE, "app.jsx", "mocksha")
    names = [s["symbol_name"] for s in res["symbols"]]
    assert "App" in names
    assert "doThing" in names


def test_js_imports():
    res = parse_file(JS_CODE, "app.jsx", "mocksha")
    paths = [i["imported_path"] for i in res["imports"]]
    assert "react" in paths
