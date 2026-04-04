#!/usr/bin/env python3
"""config_merge - deep merge configuration files (JSON/INI/env) with conflict detection."""

import argparse, sys, os, json, re, configparser, io

def detect_format(path):
    ext = os.path.splitext(path)[1].lower()
    fmt_map = {".json": "json", ".ini": "ini", ".cfg": "ini", ".conf": "ini",
               ".env": "env", ".properties": "properties"}
    if ext in fmt_map:
        return fmt_map[ext]
    with open(path) as f:
        first = f.read(100).strip()
    if first.startswith("{") or first.startswith("["):
        return "json"
    if "=" in first and not first.startswith("#"):
        return "env"
    return "json"

def load_file(path, fmt=None):
    if not fmt:
        fmt = detect_format(path)
    with open(path) as f:
        content = f.read()

    if fmt == "json":
        return json.loads(content), fmt
    elif fmt == "ini":
        cp = configparser.ConfigParser()
        cp.read_string(content)
        data = {}
        for section in cp.sections():
            data[section] = dict(cp[section])
        if cp.defaults():
            data["DEFAULT"] = dict(cp.defaults())
        return data, fmt
    elif fmt in ("env", "properties"):
        data = {}
        for line in content.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                k, v = line.split("=", 1)
                data[k.strip()] = v.strip().strip('"').strip("'")
        return data, fmt
    return {}, fmt

def deep_merge(base, override, path="", conflicts=None):
    if conflicts is None:
        conflicts = []
    result = dict(base)
    for k, v in override.items():
        if k in result:
            if isinstance(result[k], dict) and isinstance(v, dict):
                result[k] = deep_merge(result[k], v, f"{path}.{k}", conflicts)
            elif result[k] != v:
                conflicts.append({
                    "path": f"{path}.{k}".lstrip("."),
                    "base": result[k],
                    "override": v
                })
                result[k] = v
        else:
            result[k] = v
    return result

def serialize(data, fmt):
    if fmt == "json":
        return json.dumps(data, indent=2)
    elif fmt == "ini":
        cp = configparser.ConfigParser()
        for section, values in data.items():
            if section == "DEFAULT":
                for k, v in values.items():
                    cp.defaults()[k] = str(v)
            else:
                cp[section] = {k: str(v) for k, v in values.items()}
        buf = io.StringIO()
        cp.write(buf)
        return buf.getvalue()
    elif fmt in ("env", "properties"):
        lines = []
        for k, v in sorted(data.items()):
            if isinstance(v, dict):
                for sk, sv in sorted(v.items()):
                    lines.append(f"{k}_{sk}={sv}")
            else:
                lines.append(f"{k}={v}")
        return "\n".join(lines)
    return json.dumps(data, indent=2)

def cmd_merge(args):
    files = args.files
    if len(files) < 2:
        print("  Need at least 2 files to merge")
        return

    result, fmt = load_file(files[0], args.format)
    all_conflicts = []

    for f in files[1:]:
        data, _ = load_file(f, args.format)
        conflicts = []
        result = deep_merge(result, data, "", conflicts)
        all_conflicts.extend(conflicts)

    out_fmt = args.output_format or fmt

    if all_conflicts and not args.quiet:
        print(f"  ⚠ {len(all_conflicts)} conflict(s):\n", file=sys.stderr)
        for c in all_conflicts:
            print(f"  {c['path']}: {c['base']} → {c['override']}", file=sys.stderr)
        print(file=sys.stderr)

    output = serialize(result, out_fmt)
    if args.output:
        with open(args.output, "w") as f:
            f.write(output)
        print(f"  ✅ Merged {len(files)} files → {args.output}")
    else:
        print(output)

def cmd_diff(args):
    data1, _ = load_file(args.file1, args.format)
    data2, _ = load_file(args.file2, args.format)

    def flat(d, prefix=""):
        items = {}
        for k, v in d.items():
            key = f"{prefix}.{k}" if prefix else k
            if isinstance(v, dict):
                items.update(flat(v, key))
            else:
                items[key] = v
        return items

    f1 = flat(data1)
    f2 = flat(data2)
    all_keys = sorted(set(f1) | set(f2))

    only1, only2, differ, same = 0, 0, 0, 0
    print(f"\n  Config Diff: {args.file1} ↔ {args.file2}\n")
    for k in all_keys:
        v1 = f1.get(k)
        v2 = f2.get(k)
        if v1 is not None and v2 is None:
            print(f"  \033[31m- {k} = {v1}\033[0m")
            only1 += 1
        elif v1 is None and v2 is not None:
            print(f"  \033[32m+ {k} = {v2}\033[0m")
            only2 += 1
        elif v1 != v2:
            print(f"  \033[33m~ {k}: {v1} → {v2}\033[0m")
            differ += 1
        else:
            same += 1

    print(f"\n  {only1} removed, {only2} added, {differ} changed, {same} identical\n")

def cmd_flatten(args):
    data, _ = load_file(args.file, args.format)

    def flat(d, prefix=""):
        for k, v in d.items():
            key = f"{prefix}.{k}" if prefix else k
            if isinstance(v, dict):
                flat(v, key)
            else:
                if args.env:
                    env_key = key.replace(".", "_").upper()
                    print(f"{env_key}={v}")
                else:
                    print(f"  {key} = {v}")

    flat(data)

def cmd_validate(args):
    for filepath in args.files:
        try:
            data, fmt = load_file(filepath)
            keys = len(data) if isinstance(data, dict) else 0
            print(f"  ✅ {filepath} ({fmt}, {keys} keys)")
        except Exception as e:
            print(f"  ❌ {filepath}: {e}")

def main():
    p = argparse.ArgumentParser(description="Config file merger")
    sp = p.add_subparsers(dest="cmd")

    m = sp.add_parser("merge", help="Deep merge config files")
    m.add_argument("files", nargs="+")
    m.add_argument("-o", "--output", help="Output file")
    m.add_argument("-f", "--format", choices=["json", "ini", "env"])
    m.add_argument("--output-format", choices=["json", "ini", "env"])
    m.add_argument("-q", "--quiet", action="store_true")
    m.set_defaults(func=cmd_merge)

    d = sp.add_parser("diff", help="Diff two config files")
    d.add_argument("file1")
    d.add_argument("file2")
    d.add_argument("-f", "--format", choices=["json", "ini", "env"])
    d.set_defaults(func=cmd_diff)

    fl = sp.add_parser("flatten", help="Flatten nested config")
    fl.add_argument("file")
    fl.add_argument("-f", "--format", choices=["json", "ini", "env"])
    fl.add_argument("--env", action="store_true", help="Output as ENV vars")
    fl.set_defaults(func=cmd_flatten)

    v = sp.add_parser("validate", help="Validate config files")
    v.add_argument("files", nargs="+")
    v.set_defaults(func=cmd_validate)

    args = p.parse_args()
    if not args.cmd:
        p.print_help()
        sys.exit(1)
    args.func(args)

if __name__ == "__main__":
    main()
