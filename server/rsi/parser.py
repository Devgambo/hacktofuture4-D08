import re
from pathlib import Path

# Sensitivity keywords
SENSITIVE_PATHS = {
    "auth", "login", "credentials", "secret", "token", "password",
    "infrastructure", "terraform", "k8s", "aws", "gcp"
}

def _get_role_tag(file_path: str) -> str:
    path_lower = file_path.lower()
    parts = Path(file_path).parts

    # Secrets & Auth
    if any(k in path_lower for k in ["secret", "token", "credential", "auth"]):
        return "secrets"

    # Q1: Test — only match when a path component is exactly "test" / "tests" / "__tests__"
    # or the filename starts/ends with "test_" / "_test" patterns.
    part_names = {p.lower() for p in parts}
    if part_names & {"test", "tests", "__tests__", "spec", "specs"}:
        return "test"
    filename_lower = Path(file_path).name.lower()
    stem_lower = Path(file_path).stem.lower()
    if (
        filename_lower.startswith("test_")
        or stem_lower.endswith("_test")
        or stem_lower.endswith(".test")
        or stem_lower.endswith(".spec")
        or filename_lower.startswith("spec_")
    ):
        return "test"

    # Q2: GitHub CI workflow files → infra, not config
    if ".github/workflows" in file_path.replace("\\", "/"):
        return "infra"

    # Infra config
    if any(k in path_lower for k in [".tf", "dockerfile", "docker-compose", "k8s", ".yml", ".yaml"]):
        if any(infra_word in path_lower for infra_word in ["infra", "deploy", "kubernetes", "helm", "aws", "gcp"]):
            return "infra"
        return "config"

    # Generic Config
    if file_path.endswith((".json", ".toml", ".ini", ".env", ".yaml", ".yml")):
        return "config"

    return "source"

def _is_sensitive(file_path: str, role_tag: str) -> bool:
    if role_tag in ["secrets", "infra"]:
        return True
    path_lower = file_path.lower()
    return any(p in path_lower for p in SENSITIVE_PATHS)

def _get_sensitivity_reason(file_path: str, role_tag: str) -> str:
    """Return a short reason why a file is flagged as sensitive."""
    pl = file_path.lower()
    if role_tag == "secrets":
        if "token" in pl:
            return "Token/API key handling"
        if "password" in pl or "passwd" in pl:
            return "Password handling"
        if "credential" in pl:
            return "Credential management"
        if "auth" in pl:
            return "Authentication logic"
        if "login" in pl:
            return "Login/session handling"
        return "Auth/secrets handling"
    if role_tag == "infra":
        if "terraform" in pl or ".tf" in pl:
            return "Terraform infrastructure code"
        if "docker" in pl:
            return "Docker configuration"
        if "k8s" in pl or "kubernetes" in pl or "helm" in pl:
            return "Kubernetes/Helm config"
        if ".github/workflows" in pl.replace("\\", "/"):
            return "GitHub Actions CI/CD workflow"
        if "aws" in pl:
            return "AWS configuration"
        if "gcp" in pl:
            return "GCP configuration"
        return "Infrastructure configuration"
    # Path-based sensitive keyword
    for kw, reason in [
        ("token",          "Token/API key handling"),
        ("secret",         "Secret/key management"),
        ("password",       "Password handling"),
        ("credential",     "Credential management"),
        ("auth",           "Authentication logic"),
        ("login",          "Login/session handling"),
        ("infrastructure", "Infrastructure code"),
        ("terraform",      "Terraform infrastructure code"),
        ("k8s",            "Kubernetes config"),
        ("aws",            "AWS configuration"),
        ("gcp",            "GCP configuration"),
    ]:
        if kw in pl:
            return reason
    return "Sensitive path pattern"

def _generate_file_desc(file_path: str, role_tag: str, symbols: list[dict]) -> str:
    """Generate a ≤10-word description of a file from its path, role, and symbols."""
    stem = Path(file_path).stem
    parts = Path(file_path).parts

    if role_tag == "test":
        subject = stem
        for prefix in ("test_", "spec_"):
            if subject.startswith(prefix):
                subject = subject[len(prefix):]
                break
        for suffix in ("_test", "_spec"):
            if subject.endswith(suffix):
                subject = subject[: -len(suffix)]
                break
        return f"Tests for {subject}"

    if role_tag == "infra":
        return f"Infrastructure config: {stem}"

    if role_tag == "config":
        return f"Config: {stem}"

    if role_tag == "secrets":
        return f"Sensitive: {stem} auth/credential handling"

    # source — prefer exported symbols (up to 3)
    exported = [s["symbol_name"] for s in symbols if s.get("exports", False)][:3]
    if exported:
        return ", ".join(exported)

    # Fallback: meaningful dir + stem
    skip = {".", "..", "src", "lib", "app", "server", "client", "pkg", "internal"}
    ctx_parts = [p for p in parts[:-1] if p.lower() not in skip]
    context = ctx_parts[-1] if ctx_parts else ""
    if context:
        return f"{context}/{stem} module"
    return f"{stem} module"

def parse_python(content: str) -> tuple[list[dict], list[dict]]:
    """Parse Python file for symbols and imports using regex."""
    symbols = []
    imports = []

    # Classes: class MyClass(Base):
    for match in re.finditer(r"^class\s+([A-Za-z0-9_]+)[\(:]", content, re.MULTILINE):
        # B1: use "\n" (real newline), not "\\n" (literal backslash-n)
        start_line = content[:match.start()].count("\n") + 1
        symbols.append({
            "symbol_name": match.group(1),
            "symbol_type": "class",
            "start_line": start_line,
            "end_line": start_line,
            "exports": True
        })

    # Functions: def my_func():
    for match in re.finditer(r"^(?:async\s+)?def\s+([A-Za-z0-9_]+)\s*\(", content, re.MULTILINE):
        start_line = content[:match.start()].count("\n") + 1
        symbols.append({
            "symbol_name": match.group(1),
            "symbol_type": "function",
            "start_line": start_line,
            "end_line": start_line,
            "exports": not match.group(1).startswith("_")
        })

    # Imports: import x, from x import y
    # B28: strip " as alias" so "import numpy as np" → imported_path="numpy"
    for match in re.finditer(r"^(?:from\s+([A-Za-z0-9_\.]+)\s+)?import\s+(.+)$", content, re.MULTILINE):
        module = match.group(1)
        names = match.group(2)
        if module:
            imports.append({"imported_path": module})
        else:
            for n in names.split(","):
                # Strip "as alias" suffix
                clean = re.split(r"\s+as\s+", n.strip())[0].strip()
                if clean:
                    imports.append({"imported_path": clean})

    return symbols, imports

def parse_js_ts(content: str) -> tuple[list[dict], list[dict]]:
    """Parse JS/TS file for symbols and imports using regex."""
    symbols = []
    imports = []

    # Classes: class MyClass { or export class MyClass
    for match in re.finditer(r"^(?:export\s+)?(?:default\s+)?class\s+([A-Za-z0-9_]+)", content, re.MULTILINE):
        start_line = content[:match.start()].count("\n") + 1
        symbols.append({
            "symbol_name": match.group(1),
            "symbol_type": "class",
            "start_line": start_line,
            "end_line": start_line,
            "exports": "export" in match.group(0)
        })

    # Functions: function myFunc() or export default async function myFunc
    for match in re.finditer(r"^(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s+([A-Za-z0-9_]+)", content, re.MULTILINE):
        start_line = content[:match.start()].count("\n") + 1
        symbols.append({
            "symbol_name": match.group(1),
            "symbol_type": "function",
            "start_line": start_line,
            "end_line": start_line,
            "exports": "export" in match.group(0)
        })

    # Arrow functions / named function expressions:
    # B27: also matches "const foo = function()" and "const foo = async function()"
    for match in re.finditer(
        r"^(?:export\s+)?const\s+([A-Za-z0-9_]+)\s*=\s*(?:async\s+)?(?:function\s*\(|\()",
        content, re.MULTILINE
    ):
        start_line = content[:match.start()].count("\n") + 1
        symbols.append({
            "symbol_name": match.group(1),
            "symbol_type": "function",
            "start_line": start_line,
            "end_line": start_line,
            "exports": "export" in match.group(0)
        })

    # Imports: import { x } from 'y'
    for match in re.finditer(r"import\s+.*from\s+['\"]([^'\"]+)['\"]", content, re.MULTILINE):
        imports.append({"imported_path": match.group(1)})

    return symbols, imports

def parse_file(content: str, file_path: str, sha: str) -> dict:
    """
    Parse a file's content and return its structural RSI data.
    """
    ext = Path(file_path).suffix.lower()
    # B1: count real newlines ("\n"), not literal backslash-n ("\\n")
    line_count = content.count("\n") + 1
    role_tag = _get_role_tag(file_path)

    symbols = []
    imports = []

    if ext == ".py":
        syms, imps = parse_python(content)
        symbols = syms
        imports = imps
    # B26: add .mjs and .cjs alongside .js/.jsx/.ts/.tsx
    elif ext in [".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"]:
        syms, imps = parse_js_ts(content)
        symbols = syms
        imports = imps

    # Attach file_path to children
    for s in symbols:
        s["file_path"] = file_path
    for i in imports:
        i["file_path"] = file_path

    file_desc = _generate_file_desc(file_path, role_tag, symbols)
    is_sensitive = _is_sensitive(file_path, role_tag)

    file_map = {
        "file_path":  file_path,
        "role_tag":   role_tag,
        "language":   ext.lstrip("."),
        "file_sha":   sha,
        "line_count": line_count,
        "file_desc":  file_desc,
    }

    sensitivity = {
        "file_path":          file_path,
        "is_flagged":         is_sensitive,
        "requires_approval":  is_sensitive,
        "owners":             "",
        "sensitivity_reason": _get_sensitivity_reason(file_path, role_tag) if is_sensitive else "",
    }

    return {
        "file":        file_map,
        "symbols":     symbols,
        "imports":     imports,
        "sensitivity": sensitivity,
    }
